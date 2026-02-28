"""
Tenant resolution and DB dependencies for database-per-tenant architecture.

Master DB: tenant management only. Never users, companies, branches, items.
Tenant DB: one per tenant; full app schema. Data isolated per tenant.
Legacy/default DB: current DATABASE_URL. No tenant header → use this.

Auth: get_current_user_optional / get_current_user accept internal JWT or (when
SUPABASE_JWT_SECRET set) Supabase JWT. Tenant from token or X-Tenant-* header.
"""
from urllib.parse import urlparse, quote
import time as _time

import logging
import threading
from contextlib import contextmanager
from typing import Generator, Optional, Tuple
from uuid import UUID

from fastapi import Request, Depends, HTTPException, status
from sqlalchemy import create_engine, pool, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.database_master import get_master_db
from app.models.tenant import Tenant
from app.models.user import User
from app.utils.auth_internal import (
    CLAIM_JTI,
    CLAIM_TENANT_SUBDOMAIN,
    decode_token_dual,
    is_token_revoked_in_db,
)

logger = logging.getLogger(__name__)

# RLS session variable name (PostgreSQL). Set on each request so RLS policies can filter by company.
RLS_CLAIM_COMPANY_ID = "jwt.claims.company_id"


def get_effective_company_id_for_user(db: Session, user: User):
    """
    Resolve the company_id for the authenticated user (single-DB multi-company).
    Uses: user's branch assignments (UserBranchRole -> Branch -> company_id), or the single company in DB.
    Returns None if no company can be resolved (caller should handle).
    """
    from app.models.user import UserBranchRole
    from app.models.company import Branch, Company
    ubr = db.query(UserBranchRole).filter(UserBranchRole.user_id == user.id).first()
    if ubr:
        branch = db.query(Branch).filter(Branch.id == ubr.branch_id).first()
        if branch:
            return branch.company_id
    company = db.query(Company).limit(1).first()
    return company.id if company else None


# -----------------------------------------------------------------------------
# Tenant engine pool (Step 2)
# One engine + session factory per tenant database_url. Legacy uses existing
# app DB (SessionLocal); never store legacy URL in pool.
# -----------------------------------------------------------------------------
_tenant_engines: dict[str, object] = {}
_tenant_sessions: dict[str, sessionmaker] = {}
_pool_lock = threading.Lock()

# In-process cache for default tenant (key=url, value=(tenant, expiry_ts)); TTL 10 minutes
_default_tenant_cache: dict = {}
_default_tenant_cache_ttl_seconds = 600

# Supabase: transaction pooler port on db.xxx (IPv6); session pooler on pooler.supabase.com (IPv4).
_SUPABASE_TRANSACTION_POOLER_PORT = "6543"
_SESSION_POOLER_PORT = "5432"


def _supabase_project_ref_from_url(url: str) -> Optional[str]:
    """Extract Supabase project ref from a DB URL (direct or session pooler). Returns None if not Supabase."""
    if not url or not url.strip():
        return None
    try:
        parsed = urlparse(url.strip())
        # Session pooler: postgres.REF@aws-x-region.pooler.supabase.com
        if parsed.username and parsed.username.startswith("postgres."):
            return parsed.username.split(".", 1)[1]
        # Direct: db.REF.supabase.co
        host = parsed.hostname or ""
        if host.startswith("db.") and host.endswith(".supabase.co"):
            return host[3:-14]
    except Exception:
        pass
    return None


def _same_supabase_db(url_a: Optional[str], url_b: Optional[str]) -> bool:
    """True if both URLs point to the same Supabase project (direct vs pooler treated as same)."""
    if not url_a or not url_b:
        return False
    a = (url_a or "").strip()
    b = (url_b or "").strip()
    if a == b:
        return True
    ref_a = _supabase_project_ref_from_url(a)
    ref_b = _supabase_project_ref_from_url(b)
    return ref_a is not None and ref_a == ref_b


def is_tenant_ready_for_invite(tenant: Tenant) -> bool:
    """
    True if an invite can be created for this tenant.
    Single-DB: no database_url → use app DB, allow invite. With database_url → allow if provisioned or same as app DB.
    """
    if not tenant.database_url or not tenant.database_url.strip():
        return True  # Single-DB: use app database for invite and company setup
    if tenant.is_provisioned:
        return True
    app_url = getattr(settings, "database_connection_string", None) or getattr(settings, "DATABASE_URL", None)
    if not app_url:
        return False
    return _same_supabase_db(tenant.database_url, app_url.strip())


def _get_pooler_host() -> Optional[str]:
    """Session pooler host from SUPABASE_POOLER_HOST or from DATABASE_URL (master). Same region = same host for tenants."""
    host = getattr(settings, "SUPABASE_POOLER_HOST", None) or ""
    if host:
        return host.strip()
    master_url = getattr(settings, "database_connection_string", "") or ""
    if "pooler.supabase.com" in str(master_url):
        try:
            parsed = urlparse(master_url)
            if parsed.hostname and "pooler.supabase.com" in parsed.hostname:
                return parsed.hostname
        except Exception:
            pass
    return None


def resolve_tenant_database_url(raw_url: Optional[str]) -> str:
    """
    Resolve tenant DB URL for Render (IPv4). When USE_SUPABASE_POOLER_FOR_TENANTS is true:
    - If we have a session pooler host (from master DATABASE_URL), rewrite db.XXX:5432 to
      postgres.XXX@POOLER_HOST:5432 (Supabase shared pooler in same region routes by PROJECT_REF).
    - Else rewrite to transaction pooler db.XXX:6543 (may be IPv6 and unreachable on Render).
    """
    if not raw_url or not raw_url.strip():
        return raw_url or ""
    url = raw_url.strip()
    if not getattr(settings, "USE_SUPABASE_POOLER_FOR_TENANTS", False):
        return url
    if "db." not in url or ".supabase.co" not in url or ":5432" not in url:
        return url
    pooler_host = _get_pooler_host()
    if pooler_host:
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            if hostname.startswith("db.") and hostname.endswith(".supabase.co"):
                project_ref = hostname[3:-14]
                password = parsed.password or ""
                dbname = (parsed.path or "/postgres").lstrip("/") or "postgres"
                new_user = f"postgres.{project_ref}"
                safe_pass = quote(password, safe=".-_~") if password else ""
                netloc = f"{new_user}:{safe_pass}@{pooler_host}:{_SESSION_POOLER_PORT}"
                new_url = f"{parsed.scheme or 'postgresql'}://{netloc}/{dbname}"
                logger.debug("Using Supabase session pooler (%s) for tenant DB (IPv4).", pooler_host)
                return new_url
        except Exception as e:
            logger.warning("Session pooler rewrite failed, falling back to transaction pooler: %s", e)
    if ".supabase.co:5432" in url or ".supabase.co:5432/" in url:
        url = url.replace(".supabase.co:5432", ".supabase.co:" + _SUPABASE_TRANSACTION_POOLER_PORT)
        logger.debug("Using Supabase transaction pooler (port %s) for tenant DB.", _SUPABASE_TRANSACTION_POOLER_PORT)
    return url


def _session_factory_for_url(database_url: str) -> sessionmaker:
    """Get or create session factory for a tenant database_url. Thread-safe."""
    effective_url = resolve_tenant_database_url(database_url)
    # Use pooler-safe options when connecting via Supabase pooler (session or transaction).
    use_pooler = (
        ":6543" in effective_url
        or "pooler.supabase.com" in effective_url
    )
    connect_args = {
        "connect_timeout": 10,
        "options": "-c statement_timeout=120000",
    }
    if use_pooler:
        connect_args["prepare_threshold"] = None  # Transaction pooler does not support prepared statements
    with _pool_lock:
        if effective_url not in _tenant_sessions:
            engine = create_engine(
                effective_url,
                poolclass=pool.QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args=connect_args,
                echo=settings.DEBUG,
            )
            _tenant_engines[effective_url] = engine
            _tenant_sessions[effective_url] = sessionmaker(
                autocommit=False, autoflush=False, bind=engine
            )
        return _tenant_sessions[effective_url]


def get_tenant_from_header(
    request: Request,
    db: Session = Depends(get_master_db),
) -> Optional[Tenant]:
    """
    Resolve tenant from X-Tenant-Subdomain or X-Tenant-ID header, or from JWT when no header.
    Ensures authenticated tenant users always get the correct DB (tenant isolation).

    - Header present → use it.
    - No header but Bearer token present → use tenant_subdomain from JWT (so Grace/Harte never gets Pharmasight DB).
    - No header, no token → None (legacy/default DB).
    """
    subdomain = request.headers.get("X-Tenant-Subdomain")
    tenant_id_raw = request.headers.get("X-Tenant-ID")

    if not subdomain and not tenant_id_raw:
        auth = request.headers.get("Authorization")
        token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
        if token:
            try:
                payload = decode_token_dual(token)
                if payload:
                    subdomain = (payload.get(CLAIM_TENANT_SUBDOMAIN) or "").strip()
                    if subdomain and subdomain != "__default__":
                        tenant = db.query(Tenant).filter(Tenant.subdomain == subdomain).first()
                        if tenant and (tenant.status or "").lower() not in ("suspended", "cancelled"):
                            return tenant
            except Exception:
                pass
        return None

    tenant = None
    if tenant_id_raw:
        try:
            uid = UUID(str(tenant_id_raw).strip())
            tenant = db.query(Tenant).filter(Tenant.id == uid).first()
        except (ValueError, TypeError):
            pass
    if not tenant and subdomain:
        tenant = db.query(Tenant).filter(Tenant.subdomain == str(subdomain).strip()).first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    # Allow tenant with no database_url (single-DB / re-invited); get_tenant_db will use app DB
    if (tenant.status or "").lower() in ("suspended", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please contact support.",
        )
    return tenant


def get_tenant_db(
    tenant: Optional[Tenant] = Depends(get_tenant_from_header),
) -> Generator[Session, None, None]:
    """
    Yield a DB session for tenant-scoped app data (users, company, branches, items, etc.).

    - No tenant (no header) → LEGACY/DEFAULT DB (current DATABASE_URL). Same as get_db.
    - Tenant resolved → TENANT DB (tenant.database_url). Isolated per tenant.

    Uses MASTER only for resolution; this session is never master.
    """
    if tenant is None or not (tenant.database_url and tenant.database_url.strip()):
        # No tenant header or tenant has no DB URL (single-DB / re-invited legacy): use app DB
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
        return

    # Architecture: tenant.database_url from master DB. If unreachable (e.g. deleted project), use app DB.
    try:
        factory = _session_factory_for_url(tenant.database_url)
        db = factory()
        db.execute(text("SELECT 1"))  # force connection
    except (OperationalError, OSError) as e:
        err_str = str(e)
        if "tenant or user not found" in err_str.lower() or "fatal:" in err_str.lower():
            # Tenant's DB points to deleted/unreachable project (e.g. re-invited legacy). Use app DB.
            logger.info(
                "Tenant %s DB unreachable (e.g. deleted project), using app DB",
                getattr(tenant, "subdomain", None),
            )
            db = SessionLocal()
        else:
            logger.warning(
                "Tenant DB unreachable subdomain=%s: %s",
                getattr(tenant, "subdomain", None),
                e,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tenant database is temporarily unreachable (network or DNS). The URL is read from the master DB; check connectivity to that host.",
            ) from e
    try:
        yield db
    finally:
        db.close()


@contextmanager
def tenant_db_session(tenant: Tenant) -> Generator[Session, None, None]:
    """
    Context manager: yield a DB session for a given tenant's database.

    Use for token-based flows (e.g. onboarding) where tenant comes from token, not header.
    - Raises HTTPException 503 if tenant.database_url is missing (not provisioned).
    - Yields session for TENANT DB only. Caller uses it for users, company, etc.
    """
    if not tenant.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant database not provisioned",
        )
    factory = _session_factory_for_url(tenant.database_url)
    db = factory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def tenant_or_app_db_session(tenant: Tenant) -> Generator[Session, None, None]:
    """
    Yield a DB session for invite/onboarding: tenant's DB if database_url set, else app DB (single-DB).
    Use when creating invites or completing invite so tenants without database_url still work.
    """
    if tenant.database_url and tenant.database_url.strip():
        with tenant_db_session(tenant) as db:
            yield db
    else:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


# -----------------------------------------------------------------------------
# Auth: current user from JWT (internal or Supabase dual-auth)
# -----------------------------------------------------------------------------

def _tenant_from_token_or_header(request: Request, master_db: Session, payload: dict) -> Optional[Tenant]:
    """Resolve tenant from token tenant_subdomain or from X-Tenant-* headers."""
    tenant_subdomain = (payload or {}).get("tenant_subdomain")
    if tenant_subdomain:
        return master_db.query(Tenant).filter(Tenant.subdomain == str(tenant_subdomain).strip()).first()
    subdomain = request.headers.get("X-Tenant-Subdomain")
    tenant_id_raw = request.headers.get("X-Tenant-ID")
    if not subdomain and not tenant_id_raw:
        return None
    tenant = None
    if tenant_id_raw:
        try:
            uid = UUID(str(tenant_id_raw).strip())
            tenant = master_db.query(Tenant).filter(Tenant.id == uid).first()
        except (ValueError, TypeError):
            pass
    if not tenant and subdomain:
        tenant = master_db.query(Tenant).filter(Tenant.subdomain == str(subdomain).strip()).first()
    return tenant


def _get_default_tenant(master_db: Session) -> Optional[Tenant]:
    """Return the tenant whose database_url equals this app's DATABASE_URL (or same Supabase project), or None.
    Uses in-process cache keyed by DATABASE_URL with 10-minute TTL."""
    default_url = settings.database_connection_string
    if not default_url:
        return None
    default_url = default_url.strip()
    now = _time.monotonic()
    with _pool_lock:
        entry = _default_tenant_cache.get(default_url)
        if entry is not None:
            cached_tenant, expiry = entry
            if expiry > now:
                return cached_tenant
            _default_tenant_cache.pop(default_url, None)
    tenants = master_db.query(Tenant).filter(Tenant.database_url.isnot(None)).all()
    result = None
    for t in tenants:
        u = (t.database_url or "").strip()
        if u == default_url or _same_supabase_db(u, default_url):
            result = t
            break
    with _pool_lock:
        _default_tenant_cache[default_url] = (result, now + _default_tenant_cache_ttl_seconds)
    return result


def get_current_user_optional(
    request: Request,
    master_db: Session = Depends(get_master_db),
) -> Generator[Optional[Tuple[User, Session]], None, None]:
    """
    If Authorization: Bearer <token> present and valid (internal or Supabase JWT),
    yield (user, tenant_db_session). Otherwise yield None. Uses app DB when tenant
    missing or tenant DB unreachable (same as get_current_user).
    """
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    if not token:
        yield None
        return
    payload = decode_token_dual(token)
    if not payload or not payload.get("sub"):
        yield None
        return
    try:
        sub = UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        yield None
        return
    result = _resolve_user_and_db_optional(request, master_db, payload, sub)
    if result is None:
        yield None
        return
    user, db = result
    try:
        company_id = get_effective_company_id_for_user(db, user)
        if company_id:
            try:
                db.execute(text(f"SET LOCAL {RLS_CLAIM_COMPANY_ID} = :cid"), {"cid": str(company_id)})
            except Exception as e:
                logger.debug("Could not set RLS GUC %s: %s", RLS_CLAIM_COMPANY_ID, e)
        yield (user, db)
    finally:
        db.close()


def _resolve_user_and_db_for_request(
    request: Request,
    master_db: Session,
    payload: dict,
    sub: UUID,
) -> Tuple[User, Session]:
    """
    Resolve (user, db) for a valid token. Uses tenant DB when available and reachable;
    falls back to app DB for legacy/re-invited users (no tenant or tenant DB unreachable).
    Caller must close db. Raises HTTPException on auth failure.
    """
    tenant = _tenant_from_token_or_header(request, master_db, payload)
    if tenant is None:
        tenant = _get_default_tenant(master_db)
    if tenant and (tenant.status or "").lower() in ("suspended", "cancelled"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    def _lookup_in_db(db: Session) -> Optional[User]:
        if is_token_revoked_in_db(db, payload.get(CLAIM_JTI)):
            return None
        user = db.query(User).filter(User.id == sub, User.deleted_at.is_(None)).first()
        if not user or not user.is_active:
            return None
        return user

    # Prefer app DB when no tenant or tenant has no database_url (single-DB / re-invited legacy)
    if not tenant or not (tenant.database_url and tenant.database_url.strip()):
        db = SessionLocal()
        user = _lookup_in_db(db)
        if user:
            return (user, db)
        db.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try tenant DB; on unreachable (e.g. deleted project), fall back to app DB
    try:
        factory = _session_factory_for_url(tenant.database_url)
        db = factory()
        user = _lookup_in_db(db)
        if user:
            return (user, db)
        db.close()
    except OperationalError as e:
        err_str = str(e)
        if "tenant or user not found" in err_str.lower() or "fatal:" in err_str.lower():
            db = SessionLocal()
            user = _lookup_in_db(db)
            if user:
                return (user, db)
            db.close()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User not found or inactive",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_user_and_db_optional(
    request: Request,
    master_db: Session,
    payload: dict,
    sub: UUID,
) -> Optional[Tuple[User, Session]]:
    """Like _resolve_user_and_db_for_request but returns None instead of raising when user not found."""
    try:
        user, db = _resolve_user_and_db_for_request(request, master_db, payload, sub)
        return (user, db)
    except HTTPException:
        return None


def get_current_user(
    request: Request,
    master_db: Session = Depends(get_master_db),
) -> Generator[Tuple[User, Session], None, None]:
    """
    Require valid JWT; yield (user, tenant_db_session). Uses app DB when tenant
    missing or tenant DB unreachable (e.g. re-invited legacy users). Raises 401 if no/invalid token.
    """
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token_dual(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        sub = UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user, db = _resolve_user_and_db_for_request(request, master_db, payload, sub)
    try:
        # Set RLS session GUC so all queries in this request are scoped to user's company
        company_id = get_effective_company_id_for_user(db, user)
        if company_id:
            try:
                db.execute(text(f"SET LOCAL {RLS_CLAIM_COMPANY_ID} = :cid"), {"cid": str(company_id)})
            except Exception as e:
                logger.debug("Could not set RLS GUC %s: %s", RLS_CLAIM_COMPANY_ID, e)
        # Enforce must_change_password: deny access except to change-password-first-time, logout, auth/me,
        # and read-only company/branch endpoints so branch-select and status bar can load
        if getattr(user, "must_change_password", False):
            path = (request.url.path or "").strip()
            allowed = {
                "/api/users/change-password-first-time",
                "/api/auth/logout",
                "/api/auth/me",
            }
            if path not in allowed:
                # Allow GET company list, GET company by id, company settings, branches by company, and single branch (for branch-select / validateBranchAccess / status bar)
                parts = path.split("/")
                allow_read = (
                    path == "/api/companies"
                    or (path.startswith("/api/companies/") and len(parts) == 4 and "logo" not in path and "settings" not in path and "stamp" not in path)
                    or (path.startswith("/api/companies/") and len(parts) == 5 and path.rstrip("/").endswith("/settings"))
                    or (path.startswith("/api/branches/company/") and len(parts) == 5)
                    or (path.startswith("/api/branches/") and len(parts) == 4)
                )
                if not allow_read:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You must change your password before accessing other resources.",
                    )
        yield (user, db)
    finally:
        db.close()


def get_current_admin(request: Request):
    """
    Require valid admin Bearer token (from admin login). Use for /api/admin/* routes (except auth/login).
    Yields None; used only to enforce authentication.
    """
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from app.services.admin_token_store import is_valid_admin_token
    if not is_valid_admin_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    yield None


def get_tenant_required(
    request: Request,
    db: Session = Depends(get_master_db),
) -> Tenant:
    """Require tenant from header (for storage and tenant-scoped asset paths). Raises 400 if no tenant."""
    tenant = get_tenant_from_header(request, db)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID or X-Tenant-Subdomain required for this request",
        )
    return tenant


def get_tenant_or_default(
    request: Request,
    master_db: Session = Depends(get_master_db),
) -> Tenant:
    """
    Resolve tenant for storage/tenant-scoped ops: from header, or as the default DB tenant.

    Master/default DB can function as a tenant DB for development, testing, and demos.
    When no X-Tenant-* header is sent, look up a tenant in the tenants table whose
    database_url equals this app's DATABASE_URL. That tenant is the "default" and
    provides tenant_id for storage (e.g. tenant-assets/{tenant_id}/stamp.png).

    If no such tenant exists, raises 400 with instructions to add the default DB
    as a tenant (so it can be listed and used for dev/demos).
    """
    tenant = get_tenant_from_header(request, master_db)
    if tenant is not None:
        return tenant
    # No header: use default DB as tenant (reuse cached lookup)
    default_tenant = _get_default_tenant(master_db)
    if default_tenant is None:
        default_url = settings.database_connection_string
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This operation requires a tenant (for storage paths). "
                "Either send X-Tenant-ID or X-Tenant-Subdomain, or add your current database as a tenant "
                "in the tenants table (same database_url as DATABASE_URL) so the default DB can be used for development and demos."
            ),
        )
    if (default_tenant.status or "").lower() in ("suspended", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please contact support.",
        )
    return default_tenant


def _user_has_permission(db: Session, user_id: UUID, permission_name: str) -> bool:
    """True if user has the given permission in any of their branch-role assignments."""
    from app.models.user import UserBranchRole
    from app.models.permission import Permission, RolePermission
    has_perm = db.query(Permission.id).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).join(
        UserBranchRole,
        (UserBranchRole.role_id == RolePermission.role_id)
        & (UserBranchRole.user_id == user_id)
    ).filter(Permission.name == permission_name).first()
    return has_perm is not None


def require_settings_edit(
    user_db: Tuple[User, Session] = Depends(get_current_user),
) -> Tuple[User, Session]:
    """Require authenticated user with settings.edit permission. Yields (user, db)."""
    user, db = user_db
    if not _user_has_permission(db, user.id, "settings.edit"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission settings.edit required",
        )
    return (user, db)


