"""
Tenant resolution and DB dependencies for database-per-tenant architecture.

Master DB: tenant management only. Never users, companies, branches, items.
Tenant DB: one per tenant; full app schema. Data isolated per tenant.
Legacy/default DB: current DATABASE_URL. No tenant header → use this.

Auth: get_current_user_optional / get_current_user accept PharmaSight internal JWT only.
Tenant comes from token claims or X-Tenant-* header (legacy/default DB when none).
"""
from urllib.parse import urlparse, quote
import time as _time

import logging
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Generator, Optional, Tuple
from uuid import UUID

from fastapi import Request, Depends, HTTPException, status
from sqlalchemy import create_engine, pool, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings, normalize_postgres_url
from app.database import SessionLocal
from app.database_master import get_master_db
from app.models.tenant import Tenant
from app.models.user import User
from app.utils.auth_internal import (
    CLAIM_JTI,
    CLAIM_TENANT_SUBDOMAIN,
    decode_internal_token,
)

logger = logging.getLogger(__name__)

# RLS session variable name (PostgreSQL). Set on each request so RLS policies can filter by company.
RLS_CLAIM_COMPANY_ID = "jwt.claims.company_id"


def get_effective_company_id_for_user(db: Session, user: User):
    """
    Resolve the company_id for the authenticated user (single-DB multi-company).
    Uses: user's branch assignments (UserBranchRole -> Branch -> company_id), or the single company in DB.
    Returns None if no company can be resolved (caller should handle).
    Single join query to avoid extra round-trips.
    """
    from app.models.user import UserBranchRole
    from app.models.company import Branch, Company
    row = (
        db.query(Branch.company_id)
        .join(UserBranchRole, UserBranchRole.branch_id == Branch.id)
        .filter(UserBranchRole.user_id == user.id)
        .limit(1)
        .first()
    )
    if row:
        return row[0]
    company = db.query(Company).limit(1).first()
    return company.id if company else None


def require_document_belongs_to_user_company(
    db: Session,
    user: User,
    document,
    document_name: str = "Document",
    request: Optional[Request] = None,
) -> None:
    """
    Enforce that the loaded document belongs to the authenticated user's company.
    Single-DB multi-company: prevents cross-company access (e.g. opening another company's
    invoice). Raises 404 if document is None or document.company_id != user's effective company.
    When request is provided and request.state.effective_company_id is set (by get_current_user),
    uses that value and avoids an extra DB round-trip for tenant validation.
    """
    if document is None:
        raise HTTPException(status_code=404, detail=f"{document_name} not found")
    effective_company_id = (
        getattr(request.state, "effective_company_id", None) if request else None
    )
    if effective_company_id is None:
        effective_company_id = get_effective_company_id_for_user(db, user)
    if effective_company_id is None:
        return
    doc_company_id = getattr(document, "company_id", None)
    if doc_company_id is not None and str(doc_company_id) != str(effective_company_id):
        raise HTTPException(status_code=404, detail=f"{document_name} not found")


def require_company_match(
    resource_company_id: Optional[UUID],
    user_company_id: Optional[UUID],
    *,
    message: str = "Access denied to this resource",
) -> None:
    """
    Centralized 403 when a resource's company_id must match the authenticated user's company.
    Use after fetching a row by primary key to block cross-company ID guessing.
    """
    if user_company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    if resource_company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    if str(resource_company_id) != str(user_company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


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

# Auth resolution cache: (jti, str(sub)) -> (user_id, company_id, tenant_database_url, expiry_ts)
# Populated after full resolve. Long TTL so item search (and other requests) skip ~2s master+tenant resolution.
# Without this, every cache miss pays: master DB (tenant lookup) + tenant DB connection + user lookup.
_auth_resolution_cache: dict = {}
_auth_resolution_cache_ttl_seconds = 300.0  # 5 minutes: keep item search fast for whole POS session


def invalidate_auth_cache_for_user(user_id: UUID) -> None:
    """
    Remove all auth resolution cache entries for this user.
    Call after password change so the next request does a full DB resolution
    and sees must_change_password=False (avoids stale cache showing old flag).
    """
    with _pool_lock:
        keys_to_remove = [
            k for k, v in _auth_resolution_cache.items()
            if v[0] == user_id
        ]
        for k in keys_to_remove:
            _auth_resolution_cache.pop(k, None)


def _stub_user_for_cache(user_id: UUID):
    """Minimal user-like object for cache-hit fast path (e.g. /api/items/search). Avoids DB round-trip."""
    return SimpleNamespace(
        id=user_id,
        is_active=True,
        deleted_at=None,
        must_change_password=False,
    )
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


def _get_pooler_port() -> str:
    """Use 6543 (transaction mode) when master uses it, else 5432 (session mode). Avoids MaxClientsInSessionMode."""
    master_url = getattr(settings, "database_connection_string", "") or ""
    if ":6543" in master_url or "pgbouncer=true" in master_url.lower():
        return _SUPABASE_TRANSACTION_POOLER_PORT
    return _SESSION_POOLER_PORT


def resolve_tenant_database_url(raw_url: Optional[str]) -> str:
    """
    Resolve tenant DB URL for Render (IPv4). When USE_SUPABASE_POOLER_FOR_TENANTS is true:
    - If we have a session pooler host (from master DATABASE_URL), rewrite db.XXX:5432 to
      postgres.XXX@POOLER_HOST:5432 (Supabase shared pooler in same region routes by PROJECT_REF).
    - Else rewrite to transaction pooler db.XXX:6543 (may be IPv6 and unreachable on Render).
    """
    if not raw_url or not raw_url.strip():
        return raw_url or ""
    url = normalize_postgres_url(raw_url.strip())
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
                port = _get_pooler_port()
                netloc = f"{new_user}:{safe_pass}@{pooler_host}:{port}"
                new_url = f"postgresql://{netloc}/{dbname}"
                if port == _SUPABASE_TRANSACTION_POOLER_PORT and "pgbouncer=true" not in new_url.lower():
                    new_url = new_url + ("&pgbouncer=true" if "?" in new_url else "?pgbouncer=true")
                mode = "transaction" if port == _SUPABASE_TRANSACTION_POOLER_PORT else "session"
                logger.debug("Using Supabase %s pooler (%s:%s) for tenant DB (IPv4).", mode, pooler_host, port)
                return new_url
        except Exception as e:
            logger.warning("Session pooler rewrite failed, falling back to transaction pooler: %s", e)
    if ".supabase.co:5432" in url or ".supabase.co:5432/" in url:
        url = url.replace(".supabase.co:5432", ".supabase.co:" + _SUPABASE_TRANSACTION_POOLER_PORT)
        logger.debug("Using Supabase transaction pooler (port %s) for tenant DB.", _SUPABASE_TRANSACTION_POOLER_PORT)
    return normalize_postgres_url(url)


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
    Resolve tenant from X-Tenant-Subdomain or X-Tenant-ID header only.

    Single-DB design: identity is company/branch/user; tenant is only used for storage paths
    (e.g. logo, PDFs). When no header is sent we return None so get_tenant_db uses the app DB.
    We do NOT resolve tenant from JWT when no header is sent, so document and user data
    always come from the same (app) database and company isolation is enforced via
    get_effective_company_id_for_user + RLS/application checks.

    - Header present → resolve tenant (for storage/logo when needed).
    - No header → None (app DB; company scoping via user's branches).
    """
    subdomain = request.headers.get("X-Tenant-Subdomain")
    tenant_id_raw = request.headers.get("X-Tenant-ID")

    if not subdomain and not tenant_id_raw:
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
    If Authorization: Bearer <token> present and valid (internal JWT),
    yield (user, tenant_db_session). Otherwise yield None. Uses app DB when tenant
    missing or tenant DB unreachable (same as get_current_user).
    """
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    if not token:
        yield None
        return
    payload = decode_internal_token(token)
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
    user, db, _tenant = result
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


def _lookup_user_if_not_revoked(db: Session, sub: UUID, jti: Optional[str]) -> Optional[User]:
    """
    Single-query user lookup: return User only if not revoked and active.
    Avoids separate revoked check + user query (one round-trip instead of two).
    """
    jti = jti or ""
    try:
        row = db.execute(
            text(
                "SELECT * FROM users WHERE id = :sub AND deleted_at IS NULL AND is_active = true "
                "AND NOT EXISTS (SELECT 1 FROM revoked_tokens WHERE jti = :jti)"
            ),
            {"sub": str(sub), "jti": jti},
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    # Build User from row and attach to session (single round-trip, no second SELECT)
    data = dict(row._mapping)
    user = User(**{k: data[k] for k in data if hasattr(User, k)})
    db.add(user)
    return user


def _resolve_user_and_db_for_request(
    request: Request,
    master_db: Session,
    payload: dict,
    sub: UUID,
) -> Tuple[User, Session, Optional[Tenant]]:
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
        return _lookup_user_if_not_revoked(db, sub, payload.get(CLAIM_JTI))

    # Prefer app DB when no tenant or tenant has no database_url (single-DB / re-invited legacy)
    if not tenant or not (tenant.database_url and tenant.database_url.strip()):
        db = SessionLocal()
        user = _lookup_in_db(db)
        if user:
            return (user, db, tenant)
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
            return (user, db, tenant)
        db.close()
    except OperationalError as e:
        err_str = str(e)
        if "tenant or user not found" in err_str.lower() or "fatal:" in err_str.lower():
            db = SessionLocal()
            user = _lookup_in_db(db)
            if user:
                return (user, db, tenant)
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
) -> Optional[Tuple[User, Session, Optional[Tenant]]]:
    """Like _resolve_user_and_db_for_request but returns None instead of raising when user not found."""
    try:
        user, db, tenant = _resolve_user_and_db_for_request(request, master_db, payload, sub)
        return (user, db, tenant)
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
    payload = decode_internal_token(token)
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

    jti = payload.get(CLAIM_JTI)
    cache_key = (jti, str(sub))
    cached = None
    with _pool_lock:
        entry = _auth_resolution_cache.get(cache_key)
        if entry:
            user_id, company_id, tenant_url, expiry = entry
            if expiry > _time.monotonic():
                cached = (user_id, company_id, tenant_url)
            else:
                _auth_resolution_cache.pop(cache_key, None)

    db = None
    try:
        if cached:
            user_id, company_id, tenant_url = cached
            path = (request.url.path or "").strip().rstrip("/")
            is_items_search = path == "/api/items/search"
            # Fast path for item search: no SET LOCAL, no user fetch — one round-trip (search query only)
            if is_items_search:
                db = SessionLocal() if not tenant_url or not tenant_url.strip() else _session_factory_for_url(tenant_url)()
                stub_user = _stub_user_for_cache(user_id)
                yield (stub_user, db)
                return
            db = SessionLocal() if not tenant_url or not tenant_url.strip() else _session_factory_for_url(tenant_url)()
            try:
                db.execute(text(f"SET LOCAL {RLS_CLAIM_COMPANY_ID} = :cid"), {"cid": str(company_id)})
            except Exception:
                pass
            user = db.get(User, user_id)
            if user and getattr(user, "deleted_at", None) is None and getattr(user, "is_active", True):
                if getattr(user, "must_change_password", False):
                    allowed = {
                        "/api/users/change-password-first-time",
                        "/api/auth/change-password",
                        "/api/auth/logout",
                        "/api/auth/me",
                    }
                    if path not in allowed:
                        parts = path.split("/")
                        allow_read = (
                            path == "/api/companies"
                            or (path.startswith("/api/companies/") and len(parts) == 4 and "logo" not in path and "settings" not in path and "stamp" not in path)
                            or (path.startswith("/api/companies/") and len(parts) == 5 and path.rstrip("/").endswith("/settings"))
                            or (path.startswith("/api/branches/company/") and len(parts) == 5)
                            or (path.startswith("/api/branches/") and len(parts) == 4)
                        )
                        if not allow_read:
                            db.close()
                            db = None
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="You must change your password before accessing other resources.",
                            )
                setattr(request.state, "effective_company_id", company_id)
                yield (user, db)
                return
            with _pool_lock:
                _auth_resolution_cache.pop(cache_key, None)
            db.close()
            db = None

        user, db, tenant = _resolve_user_and_db_for_request(request, master_db, payload, sub)
        # Set RLS session GUC so all queries in this request are scoped to user's company
        company_id = get_effective_company_id_for_user(db, user)
        if company_id:
            try:
                db.execute(text(f"SET LOCAL {RLS_CLAIM_COMPANY_ID} = :cid"), {"cid": str(company_id)})
            except Exception as e:
                logger.debug("Could not set RLS GUC %s: %s", RLS_CLAIM_COMPANY_ID, e)
        # Populate auth cache for repeat requests (e.g. item search) — short TTL
        with _pool_lock:
            _auth_resolution_cache[cache_key] = (
                user.id,
                company_id,
                getattr(tenant, "database_url", None) if tenant else None,
                _time.monotonic() + _auth_resolution_cache_ttl_seconds,
            )
        # Enforce must_change_password: deny access except to change-password-first-time, logout, auth/me,
        # and read-only company/branch endpoints so branch-select and status bar can load
        if getattr(user, "must_change_password", False):
            path = (request.url.path or "").strip()
            allowed = {
                "/api/users/change-password-first-time",
                "/api/auth/change-password",  # regular change-password also clears the flag
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
        setattr(request.state, "effective_company_id", company_id)
        yield (user, db)
    finally:
        if db is not None:
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


# When no tenant row exists for the app DB, use this UUID for storage (single-DB / post-migration).
# All companies on the default DB share this storage prefix: tenant-assets/{this_uuid}/...
_SYNTHETIC_DEFAULT_TENANT_UUID = UUID("11111111-1111-1111-1111-111111111111")


def get_tenant_or_default(
    request: Request,
    master_db: Session = Depends(get_master_db),
):
    """
    Resolve tenant for storage/tenant-scoped ops: from header, default DB tenant row, or synthetic.

    When all clients use the default DB (no X-Tenant-* header), we first look up a tenant in the
    tenants table whose database_url equals DATABASE_URL. If none exists (e.g. after collapsing
    to single DB, identified by company id), we return a synthetic tenant so logo/stamp upload and
    PO PDF generation still work. Storage uses tenant-assets/{tenant_id}/...; synthetic tenant id
    comes from DEFAULT_STORAGE_TENANT_ID env or a fixed UUID.
    """
    tenant = get_tenant_from_header(request, master_db)
    if tenant is not None:
        return tenant
    default_tenant = _get_default_tenant(master_db)
    if default_tenant is not None:
        if (default_tenant.status or "").lower() in ("suspended", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended. Please contact support.",
            )
        return default_tenant
    # No tenant row for this DB: use synthetic default so storage works (single-DB, company-identified)
    sid = getattr(settings, "DEFAULT_STORAGE_TENANT_ID", None) or ""
    if isinstance(sid, str):
        sid = (sid or "").strip()
    try:
        uid = UUID(sid) if sid else _SYNTHETIC_DEFAULT_TENANT_UUID
    except (ValueError, TypeError):
        uid = _SYNTHETIC_DEFAULT_TENANT_UUID
    return SimpleNamespace(
        id=uid,
        status="active",
        supabase_storage_url=None,
        supabase_storage_service_role_key=None,
    )


def get_tenant_optional(
    request: Request,
    master_db: Session = Depends(get_master_db),
) -> Optional[Tenant]:
    """
    Resolve tenant for storage/tenant-scoped ops when available; never raises.
    Returns tenant from header, or default DB tenant, or None so endpoints can
    still work without tenant (e.g. skip tenant-assets logo URLs).
    """
    tenant = get_tenant_from_header(request, master_db)
    if tenant is not None:
        if (tenant.status or "").lower() in ("suspended", "cancelled"):
            return None
        return tenant
    default_tenant = _get_default_tenant(master_db)
    if default_tenant is None:
        return None
    if (default_tenant.status or "").lower() in ("suspended", "cancelled"):
        return None
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


def ensure_user_has_branch_access(db: Session, user_id: UUID, branch_id: UUID) -> None:
    """
    Require a user_branch_roles row for (user_id, branch_id).
    Raises 403 if the user is not assigned to that branch.
    """
    from app.models.user import UserBranchRole
    ok = (
        db.query(UserBranchRole.id)
        .filter(
            UserBranchRole.user_id == user_id,
            UserBranchRole.branch_id == branch_id,
        )
        .first()
        is not None
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this branch",
        )


def user_has_sell_below_min_margin(db: Session, user_id: UUID, branch_id: UUID) -> bool:
    """True if user has permission sales.sell_below_min_margin for this branch (via their role). Used at batch/convert to allow selling below min margin."""
    from app.models.user import UserBranchRole, UserRole
    from app.models.permission import Permission, RolePermission
    perm = db.query(Permission).filter(Permission.name == "sales.sell_below_min_margin").first()
    if not perm:
        return False
    ubr = (
        db.query(UserBranchRole)
        .join(UserRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user_id, UserBranchRole.branch_id == branch_id)
        .first()
    )
    if not ubr:
        return False
    rp = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == ubr.role_id,
            RolePermission.permission_id == perm.id,
            RolePermission.branch_id.is_(None),
        )
        .first()
    )
    return rp is not None


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


