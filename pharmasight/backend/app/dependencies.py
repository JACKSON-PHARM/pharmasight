"""
Tenant resolution and DB dependencies for database-per-tenant architecture.

Authority: DATABASE_PER_TENANT_IMPLEMENTATION_PLAN.md and architecture context.
- Master DB: tenant management only. Never users, companies, branches, items.
- Tenant DB: one per tenant; full app schema. Data isolated per tenant.
- Legacy/default DB: current DATABASE_URL. No tenant header → use this.

Auth: get_current_user_optional / get_current_user accept internal JWT or (when
SUPABASE_JWT_SECRET set) Supabase JWT. Tenant from token or X-Tenant-* header.
"""
import threading
from contextlib import contextmanager
from typing import Generator, Optional, Tuple
from uuid import UUID

from fastapi import Request, Depends, HTTPException, status
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.database_master import get_master_db
from app.models.tenant import Tenant
from app.models.user import User
from app.utils.auth_internal import (
    decode_token_dual,
)

# -----------------------------------------------------------------------------
# Tenant engine pool (Step 2)
# One engine + session factory per tenant database_url. Legacy uses existing
# app DB (SessionLocal); never store legacy URL in pool.
# -----------------------------------------------------------------------------
_tenant_engines: dict[str, object] = {}
_tenant_sessions: dict[str, sessionmaker] = {}
_pool_lock = threading.Lock()


def _session_factory_for_url(database_url: str) -> sessionmaker:
    """Get or create session factory for a tenant database_url. Thread-safe."""
    with _pool_lock:
        if database_url not in _tenant_sessions:
            engine = create_engine(
                database_url,
                poolclass=pool.QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=120000",
                },
                echo=settings.DEBUG,
            )
            _tenant_engines[database_url] = engine
            _tenant_sessions[database_url] = sessionmaker(
                autocommit=False, autoflush=False, bind=engine
            )
        return _tenant_sessions[database_url]


def get_tenant_from_header(
    request: Request,
    db: Session = Depends(get_master_db),
) -> Optional[Tenant]:
    """
    Resolve tenant from X-Tenant-Subdomain or X-Tenant-ID header.

    Uses MASTER DB only (tenants table). No app/tenant data read here.

    - No header → None (default/legacy DB).
    - Header present, tenant not found → 404.
    - Header present, tenant found but no database_url → 503 (not provisioned).
    - Header present, tenant found with database_url → Tenant.
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
    if not tenant.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant database not provisioned",
        )
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
    if tenant is None:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
        return

    factory = _session_factory_for_url(tenant.database_url)
    db = factory()
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


def get_current_user_optional(
    request: Request,
    master_db: Session = Depends(get_master_db),
) -> Generator[Optional[Tuple[User, Session]], None, None]:
    """
    If Authorization: Bearer <token> present and valid (internal or Supabase JWT),
    yield (user, tenant_db_session). Otherwise yield None.
    Tenant comes from token (internal) or X-Tenant-Subdomain header (Supabase).
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
    tenant = _tenant_from_token_or_header(request, master_db, payload)
    if not tenant or not tenant.database_url:
        yield None
        return
    if (tenant.status or "").lower() in ("suspended", "cancelled"):
        yield None
        return
    factory = _session_factory_for_url(tenant.database_url)
    db = factory()
    try:
        user = db.query(User).filter(User.id == sub, User.deleted_at.is_(None)).first()
        if not user or not user.is_active:
            yield None
            return
        yield (user, db)
    finally:
        db.close()


def get_current_user(
    request: Request,
    master_db: Session = Depends(get_master_db),
) -> Generator[Tuple[User, Session], None, None]:
    """
    Require valid JWT; yield (user, tenant_db_session). Raises 401 if no/invalid token.
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
    tenant = _tenant_from_token_or_header(request, master_db, payload)
    if not tenant or not tenant.database_url:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant not found or not provisioned",
        )
    if (tenant.status or "").lower() in ("suspended", "cancelled"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    factory = _session_factory_for_url(tenant.database_url)
    db = factory()
    try:
        user = db.query(User).filter(User.id == sub, User.deleted_at.is_(None)).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
        yield (user, db)
    finally:
        db.close()


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


