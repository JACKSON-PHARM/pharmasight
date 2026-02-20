"""
Authentication API
Handles username-based login (looks up email from username).
Dual-auth: when user has password_hash we verify password and return internal JWT;
otherwise return email for Supabase sign-in.

Uses get_tenant_db: LEGACY when no X-Tenant-* header, TENANT DB when resolved.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.database_master import get_master_db
from app.dependencies import get_current_user, get_tenant_db, get_tenant_from_header, tenant_db_session
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
    verify_password,
)

router = APIRouter()


def _trial_expired(tenant: Tenant) -> bool:
    """True if tenant is on trial and trial_ends_at is in the past (UTC)."""
    if tenant.status != "trial" or not tenant.trial_ends_at:
        return False
    end = tenant.trial_ends_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end < datetime.now(timezone.utc)


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


class UsernameLoginResponse(BaseModel):
    """Username login response. When internal auth used: access_token/refresh_token set; else email for Supabase."""
    email: str
    user_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    tenant_subdomain: Optional[str] = None
    # Internal auth: when user has password_hash we verify and return these
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


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
    """If user has password_hash, verify password; else no-op (Supabase will verify). Raises 401 if wrong."""
    if not getattr(user, "password_hash", None):
        return
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")


def _build_login_response(
    user: User,
    tenant: Optional[Tenant],
    password: Optional[str] = None,
) -> UsernameLoginResponse:
    """Build login response; if user has password_hash and password matches, add tokens."""
    subdomain = tenant.subdomain if tenant else None
    out = UsernameLoginResponse(
        email=user.email,
        user_id=str(user.id),
        username=getattr(user, "username", None) or None,
        full_name=user.full_name,
        tenant_subdomain=subdomain,
    )
    if getattr(user, "password_hash", None) and password is not None:
        if verify_password(password, user.password_hash):
            out.access_token = create_access_token(str(user.id), user.email, subdomain)
            out.refresh_token = create_refresh_token(str(user.id), user.email, subdomain)
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
    found: List[Tuple[Optional[Tenant], User]] = []
    for tenant in tenants:
        try:
            with tenant_db_session(tenant) as db:
                user = _find_user_in_db(db, normalized_username, check_email)
                if user:
                    found.append((tenant, user))
        except Exception:
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
def username_login(
    request: UsernameLoginRequest,
    tenant: Optional[Tenant] = Depends(get_tenant_from_header),
    db: Session = Depends(get_tenant_db),
    master_db: Session = Depends(get_master_db),
):
    """
    Lookup user by username and return email for Supabase Auth.

    - With X-Tenant-Subdomain: lookup in that tenant's DB; return tenant_subdomain so frontend persists it.
    - Without header: lookup in legacy DB; if not found, discover tenant by searching provisioned tenant DBs,
      then return user and tenant_subdomain so the app knows where the user belongs.
    """
    normalized_username = request.username.lower().strip()
    check_email = "@" in request.username

    user = _find_user_in_db(db, normalized_username, check_email)

    if not user and tenant is None:
        # No tenant header and not in legacy DB: discover which tenant(s) this user belongs to
        found_list = _find_user_in_all_tenants(master_db, normalized_username, check_email)
        if len(found_list) == 0:
            pass  # fall through to 404 below
        elif len(found_list) == 1:
            tenant, user = found_list[0]
            if _tenant_access_blocked(tenant):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account suspended. Please contact support.",
                )
            if _trial_expired(tenant):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Trial expired. Please contact support to upgrade.",
                )
            _require_password_if_internal(user, request.password)
            return _build_login_response(user, tenant, request.password)
        else:
            # Same username exists in more than one tenant: require tenant context (invite link or picker)
            tenants_info = [
                {"subdomain": t.subdomain, "name": t.name}
                for t, _ in found_list
            ]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "multiple_tenants",
                    "message": (
                        "This username exists in more than one organization. "
                        "Please sign in using the link from your invite email, or add ?tenant=SUBDOMAIN to the URL "
                        "(e.g. ...#login?tenant=your-org-subdomain)."
                    ),
                    "tenants": tenants_info,
                },
            )
    elif not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    else:
        if tenant and _tenant_access_blocked(tenant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended. Please contact support.",
            )
        if tenant and _trial_expired(tenant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trial expired. Please contact support to upgrade.",
            )
        _require_password_if_internal(user, request.password)
        return _build_login_response(user, tenant, request.password)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="User not found"
    )


# -----------------------------------------------------------------------------
# Internal auth: refresh, set-password (invite), request-reset, reset-password
# -----------------------------------------------------------------------------

class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None


@router.post("/auth/refresh", response_model=RefreshResponse)
def auth_refresh(body: RefreshRequest):
    """Exchange a valid refresh token for a new access token (and optional new refresh token)."""
    payload = decode_internal_token(body.refresh_token)
    if not payload or payload.get("type") != TYPE_REFRESH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    sub = payload.get(CLAIM_SUB)
    email = payload.get("email") or ""
    tenant_subdomain = payload.get(CLAIM_TENANT_SUBDOMAIN)
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    access_token = create_access_token(sub, email, tenant_subdomain)
    new_refresh = create_refresh_token(sub, email, tenant_subdomain)
    return RefreshResponse(access_token=access_token, refresh_token=new_refresh)


class SetPasswordRequest(BaseModel):
    """Set password via invitation_token (in-app invite flow). Requires X-Tenant-Subdomain."""
    invitation_token: str
    new_password: str = Field(..., min_length=6)


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
def auth_request_reset(
    request: Request,
    body: RequestResetRequest,
    background_tasks: BackgroundTasks,
    master_db: Session = Depends(get_master_db),
):
    """
    Send password reset email if user exists. Always returns 200 to avoid leaking existence.
    Email is sent in the background so the API returns quickly (avoids long waits and repeated clicks).
    Requires SMTP configured. Reset link uses internal JWT (no Supabase).
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
            sent = EmailService.send_password_reset(to_email, reset_url, expire_minutes)
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
    new_password: str = Field(..., min_length=6)


class ChangePasswordRequest(BaseModel):
    """Change password while logged in: current password + new password."""
    current_password: str
    new_password: str = Field(..., min_length=6)


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
    user.password_hash = hash_password(body.new_password)
    user.password_updated_at = datetime.now(timezone.utc)
    user.password_set = True
    db.commit()
    return {"message": "Password updated successfully."}


@router.post("/auth/reset-password", status_code=status.HTTP_200_OK)
def auth_reset_password(
    body: ResetPasswordRequest,
    master_db: Session = Depends(get_master_db),
):
    """Reset password using one-time token from email link. Sets password_hash (internal auth)."""
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
        user.password_hash = hash_password(body.new_password)
        user.password_updated_at = datetime.now(timezone.utc)
        user.password_set = True
        db.commit()
    return {"message": "Password reset. Sign in with your username and password."}
