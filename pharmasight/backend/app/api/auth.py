"""
Authentication API
Handles username-based login (looks up email from username).
Internal auth only: verifies password and returns internal JWT.

Login always uses legacy + tenant discovery (ignores X-Tenant-Subdomain for lookup).
Logout revokes the access token server-side so the session is fully terminated.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import SessionLocal
from app.rate_limit import limiter
from app.database_master import get_master_db
from app.dependencies import (
    get_current_user,
    get_tenant_db,
    get_tenant_from_header,
    tenant_db_session,
    get_effective_company_id_for_user,
    invalidate_auth_cache_for_user,
    _tenant_from_token_or_header,
    _get_default_tenant,
)
from app.utils.auth_internal import (
    CLAIM_EXP,
    CLAIM_JTI,
    CLAIM_SUB,
    CLAIM_TENANT_SUBDOMAIN,
    decode_internal_token,
    revoke_token_in_db,
    insert_refresh_token,
    get_active_refresh_token_by_jti,
    deactivate_refresh_token_by_jti,
    deactivate_all_refresh_tokens_for_user,
    revoke_oldest_refresh_tokens_over_limit,
    MAX_ACTIVE_REFRESH_TOKENS_PER_USER,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.email_service import EmailService
from app.utils.public_url import get_public_base_url
from app.utils.auth_internal import (
    CLAIM_SUB,
    CLAIM_TENANT_SUBDOMAIN,
    TYPE_REFRESH,
    TYPE_RESET,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_internal_token,
    hash_password,
    validate_new_password,
    verify_password,
)
from app.services.plan_context import get_tenant_plan_context
from app.services.demo_signup_service import create_demo_tenant
from app.utils.subscription_billing import compute_subscription_billing_state

router = APIRouter()


class AuthMeResponse(BaseModel):
    user_id: str
    roles: List[str]
    subscription_access: Optional[str] = None
    tenant_status: Optional[str] = None
    trial_ends_at: Optional[datetime] = None
    trial_days_remaining: Optional[int] = None
    # Which master `tenants` row was used (debug: compare local vs Render if behavior differs)
    subscription_tenant_subdomain: Optional[str] = None
    subscription_used_default_tenant_fallback: Optional[bool] = None
    # Debug (safe: no secrets). Helps compare Render vs local when subscription differs.
    debug_db_project_ref: Optional[str] = None
    debug_master_db_project_ref: Optional[str] = None
    debug_master_tenants_with_database_url: Optional[int] = None


# When user is found only in default/legacy DB (no tenant DB), reset token uses this subdomain.
LEGACY_TENANT_SUBDOMAIN = "__default__"


def _tenant_access_blocked(tenant: Optional[Tenant]) -> bool:
    """True if tenant is suspended or cancelled (no access to app). None = legacy DB, not blocked."""
    if tenant is None:
        return False
    return (tenant.status or "").lower() in ("suspended", "cancelled")


class UsernameLoginRequest(BaseModel):
    """Username-based login request"""
    username: str
    password: str
    tenant: Optional[str] = None  # Optional hint: when login fails, used to show "organization deactivated" vs "user not found"


class UsernameLoginResponse(BaseModel):
    """Username login response (internal auth tokens)."""
    email: str
    user_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    tenant_subdomain: Optional[str] = None
    # Internal auth: when user has password_hash we verify and return these
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    # When True, client should force user to change password (e.g. after admin-create)
    must_change_password: Optional[bool] = None


class StartDemoRequest(BaseModel):
    """Self-service account creation from the login page (shared demo DB)."""
    organization_name: str = Field(..., min_length=1, max_length=255, description="Used to create the organization/company")
    full_name: str = Field(..., min_length=1, max_length=255, description="Used for display and to generate the username")
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(..., min_length=8)


class StartDemoResponse(BaseModel):
    """Response for self-service demo signup."""
    access_token: str
    refresh_token: str
    tenant_id: str


@router.get("/auth/me", response_model=AuthMeResponse)
def auth_me(
    request: Request,
    user_db: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """
    Return current authenticated user_id, RBAC role names, and subscription/trial context
    from the master tenant row (for dashboard messaging and UI gating).
    """
    user, _ = user_db
    from app.models.user import UserBranchRole, UserRole

    rows = (
        db.query(UserRole.role_name)
        .join(UserBranchRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user.id)
        .distinct()
        .all()
    )
    roles = sorted({(r[0] or "").strip().lower() for r in (rows or []) if r and r[0]})

    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    payload = decode_internal_token(token) if token else None
    tenant = None
    used_default_fallback = False
    if payload:
        tenant = _tenant_from_token_or_header(request, master_db, payload)
    if tenant is None:
        tenant = _get_default_tenant(master_db)
        used_default_fallback = tenant is not None
    state = compute_subscription_billing_state(tenant)

    # Safe debug: only return Supabase project refs (no passwords/URLs).
    debug_db_ref = None
    debug_master_ref = None
    debug_tenants_with_db_url = None
    try:
        from app.dependencies import _supabase_project_ref_from_url
        from app.database_master import MASTER_DATABASE_URL

        debug_db_ref = _supabase_project_ref_from_url(getattr(settings, "database_connection_string", "") or "")
        debug_master_ref = _supabase_project_ref_from_url(MASTER_DATABASE_URL or "")
        try:
            debug_tenants_with_db_url = (
                master_db.query(Tenant)
                .filter(Tenant.database_url.isnot(None))
                .count()
            )
        except Exception:
            debug_tenants_with_db_url = None
    except Exception:
        pass
    return {
        "user_id": str(user.id),
        "roles": roles,
        "subscription_access": state.get("subscription_access"),
        "tenant_status": state.get("tenant_status"),
        "trial_ends_at": state.get("trial_ends_at"),
        "trial_days_remaining": state.get("trial_days_remaining"),
        "subscription_tenant_subdomain": getattr(tenant, "subdomain", None) if tenant else None,
        "subscription_used_default_tenant_fallback": used_default_fallback,
        "debug_db_project_ref": debug_db_ref,
        "debug_master_db_project_ref": debug_master_ref,
        "debug_master_tenants_with_database_url": debug_tenants_with_db_url,
    }


def _find_user_in_db(db: Session, normalized_username: str, check_email: bool) -> Optional[User]:
    """Look up user by username (and optionally email) in the given session."""
    user = db.query(User).filter(
        func.lower(func.trim(User.username)) == normalized_username,
        User.is_active == True,
        User.deleted_at.is_(None)
    ).first()
    if not user and check_email:
        user = db.query(User).filter(
            func.lower(func.trim(User.email)) == normalized_username,
            User.is_active == True,
            User.deleted_at.is_(None)
        ).first()
    return user


def _require_password_if_internal(user: User, password: str) -> None:
    """Verify password against internal password_hash. Raises 401 if wrong."""
    if not getattr(user, "password_hash", None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not enabled for password login")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")


def _build_login_response(
    user: User,
    tenant: Optional[Tenant],
    password: Optional[str] = None,
    db: Optional[Session] = None,
) -> UsernameLoginResponse:
    """Build login response; if user has password_hash and password matches, add tokens. company_id from user's DB for JWT."""
    subdomain = tenant.subdomain if tenant else None
    company_id_str = None
    if db:
        company_id = get_effective_company_id_for_user(db, user)
        company_id_str = str(company_id) if company_id else None
    out = UsernameLoginResponse(
        email=user.email,
        user_id=str(user.id),
        username=getattr(user, "username", None) or None,
        full_name=user.full_name,
        tenant_subdomain=subdomain,
        must_change_password=getattr(user, "must_change_password", None),
    )
    if getattr(user, "password_hash", None) and password is not None:
        if verify_password(password, user.password_hash):
            out.access_token = create_access_token(str(user.id), user.email, subdomain, company_id=company_id_str)
            out.refresh_token = create_refresh_token(str(user.id), user.email, subdomain, company_id=company_id_str)
    return out


def _normalize_db_url(url: Optional[str]) -> str:
    """Normalize DB URL for comparison (strip, lowercase)."""
    if not url:
        return ""
    return (url.strip() or "").lower()


# Cap tenant search so login/request-reset don't block for minutes when many tenants exist.
MAX_TENANTS_TO_SEARCH = 50


def _find_user_in_all_tenants(
    master_db: Session, normalized_username: str, check_email: bool
) -> List[Tuple[Optional[Tenant], User]]:
    """
    Find all tenants where this username/email exists.
    Also searches the default/legacy DB (DATABASE_URL); if user found there, we pair them
    with a tenant whose database_url matches the default, or the first tenant, so the reset link works.
    Search is limited to MAX_TENANTS_TO_SEARCH to keep response time bounded (e.g. on Render).
    Returns list of (tenant, user); tenant may be None for legacy-only (caller handles).
    """
    default_url = _normalize_db_url(settings.database_connection_string)
    tenants = master_db.query(Tenant).filter(
        Tenant.database_url.isnot(None),
        ~Tenant.status.in_(["cancelled", "suspended"]),
    ).limit(MAX_TENANTS_TO_SEARCH).all()
    subdomains = [t.subdomain for t in tenants]
    logger.info("Tenant discovery: %d tenant(s) with database_url and active status (subdomains: %s)", len(tenants), subdomains)
    if not tenants:
        logger.warning("No tenants with database_url set and status not cancelled/suspended. Check public.tenants: set database_url and status for Harte (and other tenant rows).")
    found: List[Tuple[Optional[Tenant], User]] = []
    for tenant in tenants:
        try:
            with tenant_db_session(tenant) as db:
                user = _find_user_in_db(db, normalized_username, check_email)
                if user:
                    found.append((tenant, user))
        except Exception as e:
            err_str = str(e)
            if "tenant or user not found" in err_str.lower() or "fatal:" in err_str.lower():
                # Tenant's DB points to deleted/unreachable project (e.g. re-invited legacy). Search app DB.
                try:
                    app_db = SessionLocal()
                    try:
                        user = _find_user_in_db(app_db, normalized_username, check_email)
                        if user:
                            found.append((tenant, user))
                            return found
                    finally:
                        app_db.close()
                except Exception:
                    pass
            if "unreachable" in err_str.lower() or "connection" in err_str.lower() or "503" in err_str:
                logger.warning("Tenant %s DB unreachable or connection failed: %s", tenant.subdomain, e)
            else:
                logger.debug("Tenant %s DB error: %s", tenant.subdomain, e)
            continue
    if found:
        return found
    # Fallback: search default/legacy DB (where public.users often lives in single-DB setups)
    # Always use (None, user) so the reset token gets LEGACY_TENANT_SUBDOMAIN and reset-password looks in the same DB.
    try:
        db = SessionLocal()
        try:
            user = _find_user_in_db(db, normalized_username, check_email)
            if user:
                found.append((None, user))
        finally:
            db.close()
    except Exception:
        pass
    return found


@router.post("/auth/username-login", response_model=UsernameLoginResponse)
@limiter.limit("5/minute")
def username_login(
    request: Request,
    body: UsernameLoginRequest,
    master_db: Session = Depends(get_master_db),
):
    """
    Lookup user by username and return email. Rate limited: 5 attempts per minute per IP.

    Always uses legacy + tenant discovery: first search legacy DB, then all tenant DBs
    (from master). Ignores X-Tenant-Subdomain for lookup so master and tenant users
    both resolve correctly regardless of frontend state.
    """
    normalized_username = body.username.lower().strip()
    check_email = "@" in body.username

    # 1) Legacy DB first
    legacy_db = SessionLocal()
    try:
        user = _find_user_in_db(legacy_db, normalized_username, check_email)
        if user:
            _require_password_if_internal(user, body.password)
            resp = _build_login_response(user, None, body.password, db=legacy_db)
            if resp.refresh_token:
                _persist_refresh_token_on_login(None, str(user.id), resp.refresh_token)
            return resp
    finally:
        legacy_db.close()

    # 2) Not in legacy: discover in all tenant DBs (from master)
    logger.info("Username not in legacy DB, searching all tenants for username=%s", normalized_username[:50])
    found_list = _find_user_in_all_tenants(master_db, normalized_username, check_email)
    if len(found_list) == 0:
        # If client sent a tenant hint (e.g. from ?tenant= in URL), check if that org is deleted/deactivated
        tenant_hint = (body.tenant or "").strip().lower() or None
        if tenant_hint:
            hinted = master_db.query(Tenant).filter(func.lower(Tenant.subdomain) == tenant_hint).first()
            if hinted and (hinted.status or "").lower() in ("cancelled", "suspended"):
                logger.info(
                    "User not found; hinted tenant %s is %s (deleted/deactivated org)",
                    tenant_hint,
                    hinted.status,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "This organization is no longer active. Your account was part of an organization that has been deactivated. "
                        "Please contact your administrator or support if you need access."
                    ),
                )
        logger.warning(
            "User not found in legacy DB or any tenant DB (username=%s). "
            "Ensure tenant DBs are reachable and public.tenants have database_url set.",
            normalized_username[:50],
        )
        # 401 (not 404): avoids confusion in browser DevTools where 404 looks like a missing API route.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if len(found_list) == 1:
        tenant, user = found_list[0]
        if _tenant_access_blocked(tenant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended. Please contact support.",
            )
        # Expired trials may still sign in; the app restricts features until they upgrade.
        # Demo expiry enforcement: block login for expired demo tenants before issuing tokens
        if tenant is not None:
            plan_ctx = get_tenant_plan_context(tenant)
            if plan_ctx.get("plan_type") == "demo":
                demo_expires_at = plan_ctx.get("demo_expires_at")
                if demo_expires_at is not None:
                    end = demo_expires_at
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=timezone.utc)
                    if end < datetime.now(timezone.utc):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your PharmaSight demo has expired. Please upgrade to continue using the system.",
                        )
        _require_password_if_internal(user, body.password)
        # User found in legacy/app DB (tenant is None) or in a tenant DB (use app DB if tenant DB unreachable)
        if tenant is None:
            db = SessionLocal()
            try:
                resp = _build_login_response(user, tenant, body.password, db=db)
            finally:
                db.close()
        else:
            try:
                with tenant_db_session(tenant) as tenant_db:
                    resp = _build_login_response(user, tenant, body.password, db=tenant_db)
            except OperationalError as e:
                if "Tenant or user not found" in str(e) or "FATAL:" in str(e).upper():
                    db = SessionLocal()
                    try:
                        resp = _build_login_response(user, tenant, body.password, db=db)
                    finally:
                        db.close()
                else:
                    raise
        if resp.refresh_token:
            _persist_refresh_token_on_login(tenant, str(user.id), resp.refresh_token)
        return resp
    # Same username in multiple tenants
    tenants_info = [{"subdomain": t.subdomain, "name": t.name} for t, _ in found_list]
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "multiple_tenants",
            "message": (
                "This username exists in more than one organization. "
                "Please sign in using the link from your invite email, or add ?tenant=SUBDOMAIN to the URL."
            ),
            "tenants": tenants_info,
        },
    )


@router.post("/auth/start-demo", response_model=StartDemoResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
def auth_start_demo(request: Request, body: StartDemoRequest):
    """
    Self-service demo signup from the login page.

    Creates a demo tenant, provisions the tenant DB (shared app DB in demo mode),
    creates a Company, HQ Branch, and initial admin User, and returns internal
    auth tokens so the caller can log the user in immediately.
    """
    try:
        result = create_demo_tenant(
            organization_name=body.organization_name.strip(),
            full_name=body.full_name.strip(),
            email=str(body.email).strip().lower(),
            phone=body.phone,
            password=body.password,
        )
    except ValueError as e:
        msg = str(e)
        msg_lc = msg.lower()
        code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "too many demo signups" in msg_lc
            else (
                status.HTTP_409_CONFLICT
                if (
                    "already registered with this email" in msg_lc
                    or "already registered for this organization" in msg_lc
                    or "organization with this name already exists" in msg_lc
                )
                else status.HTTP_400_BAD_REQUEST
            )
        )
        raise HTTPException(status_code=code, detail=msg)
    except Exception as e:
        logger.exception("Demo signup failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create your account right now. Please try again later.",
        )

    return StartDemoResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        tenant_id=result["tenant_id"],
        tenant_subdomain=result["tenant_subdomain"],
        username=result["username"],
    )


# -----------------------------------------------------------------------------
# Logout (server-side revoke) and refresh
# -----------------------------------------------------------------------------


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
def auth_logout(request: Request, master_db: Session = Depends(get_master_db)):
    """
    Terminate session server-side: revoke access token (jti in revoked_tokens) and
    invalidate all active refresh tokens for this user in this tenant. Call with Authorization: Bearer <access_token>.
    """
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    if not token:
        return {"detail": "Logged out"}
    payload = decode_internal_token(token, verify_exp=False)
    if not payload or not payload.get(CLAIM_JTI):
        return {"detail": "Logged out"}
    jti = payload.get(CLAIM_JTI)
    user_id = payload.get(CLAIM_SUB)
    tenant_subdomain = (payload.get(CLAIM_TENANT_SUBDOMAIN) or "").strip()
    exp = payload.get(CLAIM_EXP)
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    # Resolve tenant so we revoke in the same DB that owns this user (tenant or legacy)
    tenant = None
    if tenant_subdomain and tenant_subdomain != "__default__":
        tenant = master_db.query(Tenant).filter(Tenant.subdomain == tenant_subdomain).first()
    if tenant and tenant.database_url:
        with tenant_db_session(tenant) as session:
            revoke_token_in_db(session, jti, expires_at)
            if user_id:
                deactivate_all_refresh_tokens_for_user(session, str(user_id))
                session.commit()
    else:
        session = SessionLocal()
        try:
            revoke_token_in_db(session, jti, expires_at)
            if user_id:
                deactivate_all_refresh_tokens_for_user(session, str(user_id))
                session.commit()
        finally:
            session.close()
    return {"detail": "Logged out"}


# -----------------------------------------------------------------------------
# Internal auth: refresh, set-password (invite), request-reset, reset-password
# -----------------------------------------------------------------------------

class RefreshRequest(BaseModel):
    refresh_token: str
    device_info: Optional[str] = None  # optional client/browser info


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None


@router.post("/auth/refresh", response_model=RefreshResponse)
@limiter.limit("10/minute")
def auth_refresh(
    request: Request,
    body: RefreshRequest,
    master_db: Session = Depends(get_master_db),
):
    """
    Exchange a valid refresh token for a new access token and a new refresh token (rotation). Rate limited: 10/minute per IP.
    Incoming refresh token must exist in refresh_tokens, be active and not expired; then it is
    marked inactive and a new token is issued and stored.
    """
    payload = decode_internal_token(body.refresh_token)
    if not payload or payload.get("type") != TYPE_REFRESH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    jti = payload.get(CLAIM_JTI)
    sub = payload.get(CLAIM_SUB)
    email = payload.get("email") or ""
    tenant_subdomain = payload.get(CLAIM_TENANT_SUBDOMAIN)
    exp = payload.get(CLAIM_EXP)
    if not sub or not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    if not expires_at or expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    # Resolve tenant and open its DB
    tenant = None
    if tenant_subdomain and (tenant_subdomain or "").strip() and (tenant_subdomain or "").strip() != "__default__":
        tenant = master_db.query(Tenant).filter(Tenant.subdomain == (tenant_subdomain or "").strip()).first()
    if not tenant or not tenant.database_url:
        session = SessionLocal()
        try:
            _do_refresh_rotate(session, None, body.refresh_token, jti, sub, email, tenant_subdomain, expires_at, body.device_info)
            user = session.query(User).filter(User.id == sub, User.deleted_at.is_(None)).first()
            company_id_str = None
            if user:
                cid = get_effective_company_id_for_user(session, user)
                company_id_str = str(cid) if cid else None
            access_token = create_access_token(sub, email, tenant_subdomain, company_id=company_id_str)
            new_refresh = create_refresh_token(sub, email, tenant_subdomain, company_id=company_id_str)
            _persist_refresh_token(session, None, sub, new_refresh, body.device_info)
            revoke_oldest_refresh_tokens_over_limit(session, sub, MAX_ACTIVE_REFRESH_TOKENS_PER_USER)
            session.commit()
            return RefreshResponse(access_token=access_token, refresh_token=new_refresh)
        finally:
            session.close()

    with tenant_db_session(tenant) as session:
        _do_refresh_rotate(session, tenant, body.refresh_token, jti, sub, email, tenant_subdomain, expires_at, body.device_info)
        user = session.query(User).filter(User.id == sub, User.deleted_at.is_(None)).first()
        company_id_str = None
        if user:
            cid = get_effective_company_id_for_user(session, user)
            company_id_str = str(cid) if cid else None
        access_token = create_access_token(sub, email, tenant_subdomain, company_id=company_id_str)
        new_refresh = create_refresh_token(sub, email, tenant_subdomain, company_id=company_id_str)
        _persist_refresh_token(session, tenant, sub, new_refresh, body.device_info)
        revoke_oldest_refresh_tokens_over_limit(session, sub, MAX_ACTIVE_REFRESH_TOKENS_PER_USER)
        session.commit()
        return RefreshResponse(access_token=access_token, refresh_token=new_refresh)


def _do_refresh_rotate(session, tenant, refresh_token, jti, sub, email, tenant_subdomain, expires_at, device_info):
    """Validate incoming refresh token in DB and mark it inactive (rotate). Raises 401 if invalid."""
    row = get_active_refresh_token_by_jti(session, jti)
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    deactivate_refresh_token_by_jti(session, jti)


def _persist_refresh_token(session: Session, tenant: Optional[Tenant], user_id: str, refresh_token_jwt: str, device_info: Optional[str] = None) -> None:
    """Decode the refresh token JWT and insert a row into refresh_tokens. Does not commit."""
    payload = decode_internal_token(refresh_token_jwt)
    if not payload:
        return
    jti = payload.get(CLAIM_JTI)
    exp = payload.get(CLAIM_EXP)
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    if not jti or not expires_at:
        return
    tenant_id = str(tenant.id) if tenant else None
    insert_refresh_token(session, user_id, jti, expires_at, tenant_id=tenant_id, device_info=device_info)


def _persist_refresh_token_on_login(tenant: Optional[Tenant], user_id: str, refresh_token_jwt: str) -> None:
    """Persist a refresh token issued at login into the tenant/legacy DB. Enforces max active sessions."""
    if not refresh_token_jwt:
        return
    try:
        if tenant and tenant.database_url:
            with tenant_db_session(tenant) as session:
                _persist_refresh_token(session, tenant, user_id, refresh_token_jwt, device_info=None)
                revoke_oldest_refresh_tokens_over_limit(session, user_id, MAX_ACTIVE_REFRESH_TOKENS_PER_USER)
                session.commit()
        else:
            session = SessionLocal()
            try:
                _persist_refresh_token(session, None, user_id, refresh_token_jwt, device_info=None)
                revoke_oldest_refresh_tokens_over_limit(session, user_id, MAX_ACTIVE_REFRESH_TOKENS_PER_USER)
                session.commit()
            finally:
                session.close()
    except Exception as e:
        # If refresh_tokens table is missing (migration not applied), login still succeeds
        logger.warning("Could not persist refresh token on login (table may be missing): %s", e)


class SetPasswordRequest(BaseModel):
    """Set password via invitation_token (in-app invite flow). Requires X-Tenant-Subdomain."""
    invitation_token: str
    new_password: str = Field(..., min_length=8)


@router.post("/auth/set-password", status_code=status.HTTP_200_OK)
def auth_set_password(
    body: SetPasswordRequest,
    tenant: Optional[Tenant] = Depends(get_tenant_from_header),
    db: Session = Depends(get_tenant_db),
):
    """Set password for invited user (invitation_token). Clears invitation_token and sets password_set."""
    if not tenant:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant context required (X-Tenant-Subdomain)")
    user = db.query(User).filter(
        User.invitation_token == body.invitation_token,
        User.deleted_at.is_(None),
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired invitation")
    pw_error = validate_new_password(body.new_password)
    if pw_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
    user.password_hash = hash_password(body.new_password)
    user.password_updated_at = datetime.now(timezone.utc)
    user.password_set = True
    user.is_pending = False
    user.invitation_token = None
    user.is_active = True
    db.commit()
    return {"message": "Password set. Sign in with your username and password."}


class RequestResetRequest(BaseModel):
    """Request password reset email. Send email (or username) to look up user."""
    email: Optional[str] = None
    username: Optional[str] = None


@router.post("/auth/request-reset", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def auth_request_reset(
    request: Request,
    body: RequestResetRequest,
    background_tasks: BackgroundTasks,
    master_db: Session = Depends(get_master_db),
):
    """
    Send password reset email if user exists. Rate limited: 5/minute per IP. Always returns 200 to avoid leaking existence.
    Email is sent in the background so the API returns quickly (avoids long waits and repeated clicks).
    Requires SMTP configured. Reset link uses internal JWT.
    Reset link base URL: APP_PUBLIC_URL when set (non-localhost); else request Origin (so Render works).
    """
    email_or_username = (body.email or body.username or "").strip().lower()
    if not email_or_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email or username required")
    check_email = "@" in email_or_username
    found_list = _find_user_in_all_tenants(master_db, email_or_username, check_email)
    if not found_list:
        logger.info("[request-reset] No user found for %s; not sending email (same response for security)", email_or_username[:3] + "***")
        print("[request-reset] No user found for this email; no email sent. (Use an email that exists in your tenant DB.)")
        return {"message": "If an account exists, you will receive a reset link.", "email_sent": False}
    tenant, user = found_list[0]
    if _tenant_access_blocked(tenant):
        return {"message": "If an account exists, you will receive a reset link.", "email_sent": False}
    subdomain_for_token = tenant.subdomain if tenant else LEGACY_TENANT_SUBDOMAIN
    logger.info("[request-reset] User found, queuing reset email to %s (tenant=%s)", user.email, subdomain_for_token)
    reset_token = create_reset_token(str(user.id), subdomain_for_token)
    base = get_public_base_url(request)
    reset_url = f"{base}/#password-reset?token={reset_token}"
    expire_minutes = settings.RESET_TOKEN_EXPIRE_MINUTES
    to_email = user.email
    if not EmailService.is_configured():
        logger.warning(
            "SMTP not configured; password reset email will not be sent. To=%s",
            to_email,
        )
        return {"message": "If an account exists, you will receive a reset link.", "email_sent": False}

    def send_reset_email():
        try:
            uname = (getattr(user, "username", None) or "").strip() or None
            sign_in_url = None
            if subdomain_for_token and subdomain_for_token != LEGACY_TENANT_SUBDOMAIN:
                sign_in_url = f"{base.rstrip('/')}/?tenant={subdomain_for_token}#login"
            sent = EmailService.send_password_reset(
                to_email,
                reset_url,
                expire_minutes,
                username=uname,
                tenant_subdomain=subdomain_for_token if subdomain_for_token != LEGACY_TENANT_SUBDOMAIN else None,
                sign_in_url=sign_in_url,
            )
            if sent:
                logger.info("[request-reset] Password reset email sent to %s", to_email)
                print(f"  [request-reset] Email sent to {to_email}")
            else:
                logger.warning("[request-reset] Password reset email failed for %s (check SMTP)", to_email)
                print(f"  [request-reset] Email NOT sent to {to_email} (SMTP failed or not configured – check SMTP_* env and server logs)")
        except Exception as e:
            logger.exception("[request-reset] Background send failed for %s: %s", to_email, e)
            print(f"  [request-reset] Email send ERROR for {to_email}: {type(e).__name__}: {e}")

    background_tasks.add_task(send_reset_email)
    return {"message": "If an account exists, you will receive a reset link.", "email_sent": True}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    """Change password while logged in: current password + new password."""
    current_password: str
    new_password: str = Field(..., min_length=8)


@router.post("/auth/change-password", status_code=status.HTTP_200_OK)
def auth_change_password(
    body: ChangePasswordRequest,
    current_user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """Change password for the authenticated user. Requires current password."""
    user, db = current_user_and_db
    if not getattr(user, "password_hash", None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password change is not available for this account.",
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    pw_error = validate_new_password(body.new_password)
    if pw_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
    user.password_hash = hash_password(body.new_password)
    user.password_updated_at = datetime.now(timezone.utc)
    user.password_set = True
    user.must_change_password = False  # clear forced first-time change so other APIs work
    db.commit()
    invalidate_auth_cache_for_user(user.id)  # so next request sees updated flag (e.g. Users page)
    return {"message": "Password updated successfully."}


@router.post("/auth/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def auth_reset_password(
    request: Request,
    body: ResetPasswordRequest,
    master_db: Session = Depends(get_master_db),
):
    """Reset password using one-time token from email link. Rate limited: 5/minute per IP."""
    payload = decode_internal_token(body.token)
    if not payload or payload.get("type") != TYPE_RESET:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset link")
    sub = payload.get(CLAIM_SUB)
    tenant_subdomain = payload.get(CLAIM_TENANT_SUBDOMAIN)
    if not sub:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")
    from uuid import UUID
    user_id = UUID(sub)
    if tenant_subdomain == LEGACY_TENANT_SUBDOMAIN:
        # User lives in default/legacy DB (public.users)
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
            pw_error = validate_new_password(body.new_password)
            if pw_error:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
            user.password_hash = hash_password(body.new_password)
            user.password_updated_at = datetime.now(timezone.utc)
            user.password_set = True
            db.commit()
        finally:
            db.close()
        return {"message": "Password reset. Sign in with your username and password."}
    tenant = master_db.query(Tenant).filter(Tenant.subdomain == tenant_subdomain).first()
    if not tenant or not tenant.database_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if (tenant.status or "").lower() in ("suspended", "cancelled"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    with tenant_db_session(tenant) as db:
        user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        pw_error = validate_new_password(body.new_password)
        if pw_error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
        user.password_hash = hash_password(body.new_password)
        user.password_updated_at = datetime.now(timezone.utc)
        user.password_set = True
        if hasattr(user, "must_change_password"):
            user.must_change_password = False
        db.commit()
    return {"message": "Password reset. Sign in with your username and password."}
