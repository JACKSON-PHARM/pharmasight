"""
Authentication API
Handles username-based login (looks up email from username).
Internal auth only: verifies password and returns internal JWT.

Login resolves users within an organization when ``org`` / ``tenant`` context is provided (see company_context).
Logout revokes the access token server-side so the session is fully terminated.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, text
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
)
from app.utils.auth_internal import (
    CLAIM_COMPANY_ID,
    CLAIM_EMAIL,
    CLAIM_EXP,
    CLAIM_JTI,
    CLAIM_SUB,
    CLAIM_TENANT_SUBDOMAIN,
    create_signup_handoff_token,
    decode_internal_token,
    decode_internal_token_or_reason,
    decode_signup_handoff_token,
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
    CLAIM_TENANT_SUBDOMAIN,
    TYPE_REFRESH,
    TYPE_RESET,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    hash_password,
    validate_new_password,
    verify_password,
)
from app.services.demo_signup_service import create_demo_tenant
from app.services.company_context import (
    build_org_login_url,
    company_ids_for_user,
    find_user_for_company_login,
    normalize_org_slug,
    org_slug_from_request,
    preferred_company_id_from_request,
    tenant_for_org_slug,
)
from app.services.branch_provisioning_service import ensure_user_assigned_to_company_hq
from app.services.tenant_registry_service import ensure_tenant_row_for_company
from app.utils.company_access import get_company_access, get_subscription_access
from app.services.company_governance_service import (
    derive_commercial_access,
    governance_access_display,
)
from app.utils.whatsapp_e164 import normalize_whatsapp_e164

router = APIRouter()


def _raise_http_for_db_unreachable(exc: OperationalError) -> None:
    """
    Map infrastructure-style DB errors to 503 so login does not surface as opaque 500.
    Re-raises other OperationalError (e.g. auth failures) unchanged.
    """
    orig = getattr(exc, "orig", None)
    msg = (str(orig) if orig is not None else str(exc)).lower()
    unreachable_markers = (
        "could not translate host name",
        "name or service not known",
        "could not connect to server",
        "connection timed out",
        "connection refused",
        "network is unreachable",
        "temporary failure in name resolution",
        "no route to host",
    )
    if any(m in msg for m in unreachable_markers):
        logger.warning("Database unreachable during auth request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cannot connect to the database from this server. Check internet access, DNS, and "
                "DATABASE_URL. If the direct host (db.*.supabase.co) does not resolve or IPv6 is blocked, "
                "use the Supabase Session pooler URL (IPv4, port 5432) from the Supabase dashboard."
            ),
        ) from None
    raise exc


PORTAL_BILLING_ROLES = frozenset({"admin", "owner", "super admin"})


class AuthMeResponse(BaseModel):
    user_id: str
    roles: List[str]
    username: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    portal_billing_visible: bool = Field(
        default=False,
        description="True when the user may see plan/subscription details on the marketing portal.",
    )
    portal_whatsapp_e164: Optional[str] = Field(
        default=None,
        description="Digits-only international WhatsApp for wa.me (company override or platform default).",
    )
    subscription_access: Optional[str] = None
    # Backward-compatible fields (used by existing SPA). Values are derived from `companies` only.
    tenant_status: Optional[str] = None
    subscription_plan: Optional[str] = None
    trial_ends_at: Optional[datetime] = None
    subscription_period_ends_at: Optional[datetime] = Field(
        None,
        description="Effective period end for UI (demo: inferred from created_at when trial_expires_at is unset).",
    )
    trial_days_remaining: Optional[int] = None
    subscription_tenant_subdomain: Optional[str] = None
    subscription_used_default_tenant_fallback: Optional[bool] = None
    company_id: Optional[str] = None
    company_access: Optional[str] = None
    org_slug: Optional[str] = Field(
        None,
        description="Organization subdomain for shareable login URL (tenants.subdomain).",
    )
    org_login_url: Optional[str] = Field(
        None,
        description="Full ERP login URL including ?org= for this organization.",
    )


# When user is found only in default/legacy DB (no tenant DB), reset token uses this subdomain.
LEGACY_TENANT_SUBDOMAIN = "__default__"


def _enforce_login_company_access(
    db: Session,
    user: User,
    company_id: Optional[Any] = None,
) -> None:
    """
    Access control for password login uses companies only (see get_company_access).
    Blocks inactive companies; blocks expired self-service demos (subscription_plan == demo).
    """
    from app.models.company import Company

    if company_id is None:
        company_id = get_effective_company_id_for_user(db, user)
    company = db.query(Company).filter(Company.id == company_id).first() if company_id else None
    access = get_company_access(company)
    if access == "blocked":
        sub = (getattr(company, "subscription_status", None) or "").strip().lower()
        if sub in ("suspended", "canceled", "cancelled", "past_due"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This organization's subscription is suspended. Contact your administrator or SightOps support."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This organization is no longer active. Please contact your administrator or support "
                "if you need access."
            ),
        )
    if access == "expired":
        plan = (getattr(company, "subscription_plan", None) or "").strip().lower()
        if plan == "demo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your SightOps demo has expired. Please upgrade to continue using the system.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Your trial or subscription period has ended. Contact your administrator to activate commercial access."
            ),
        )


def _company_blocked_for_user(db: Session, user: User) -> bool:
    """True if the user's effective company is inactive (operators should not receive reset email / reset password)."""
    from app.models.company import Company

    company_id = get_effective_company_id_for_user(db, user)
    company = db.query(Company).filter(Company.id == company_id).first() if company_id else None
    return get_company_access(company) == "blocked"


class UsernameLoginRequest(BaseModel):
    """Username-based login request"""
    username: str
    password: str
    tenant: Optional[str] = None  # Organization slug (tenants.subdomain); alias: org query param on SPA
    org: Optional[str] = None


class UsernameLoginResponse(BaseModel):
    """Username login response (internal auth tokens)."""
    email: str
    user_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    # Legacy field: null when the account is company-scoped (single shared DB). JWT may still carry the claim as null.
    tenant_subdomain: Optional[str] = Field(
        default=None,
        description="Deprecated for routing; always null for new company-scoped users. Not used for DB selection.",
    )
    # Internal auth: when user has password_hash we verify and return these
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    # When True, client should force user to change password (e.g. after admin-create)
    must_change_password: Optional[bool] = None
    company_id: Optional[str] = None
    org_slug: Optional[str] = Field(None, description="Organization subdomain (tenants.subdomain).")
    org_login_url: Optional[str] = None


class StartDemoRequest(BaseModel):
    """Self-service account creation from the login page (shared demo DB)."""
    organization_name: str = Field(..., min_length=1, max_length=255, description="Used to create the organization/company")
    full_name: str = Field(..., min_length=1, max_length=255, description="Used for display and to generate the username")
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=50, description="Required; used for duplicate detection")
    password: str = Field(..., min_length=8)


class StartDemoResponse(BaseModel):
    """Response for self-service demo signup."""
    access_token: str
    refresh_token: str
    tenant_id: str
    tenant_subdomain: Optional[str] = None
    username: Optional[str] = None
    user_id: Optional[str] = None
    email: Optional[str] = None
    signup_handoff_token: Optional[str] = None
    invite_email_sent: Optional[bool] = Field(
        default=None,
        description="True if the setup invite email was delivered via SMTP.",
    )


class ExchangeSignupHandoffRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=16000)


def start_demo_api_response(result: dict, request_email: str) -> StartDemoResponse:
    """Build API response including a short-lived handoff JWT for marketing → ERP on a different origin."""
    pl = decode_internal_token(result["access_token"], verify_exp=True) or {}
    user_id = str(result.get("user_id") or pl.get(CLAIM_SUB) or "")
    email = (result.get("email") or pl.get(CLAIM_EMAIL) or request_email or "").strip()
    handoff = create_signup_handoff_token(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        user_id=user_id,
        email=email,
        username=result.get("username"),
        tenant_subdomain=result.get("tenant_subdomain"),
    )
    return StartDemoResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        tenant_id=result["tenant_id"],
        tenant_subdomain=result.get("tenant_subdomain"),
        username=result.get("username"),
        user_id=user_id or None,
        email=email or None,
        signup_handoff_token=handoff,
        invite_email_sent=result.get("invite_email_sent"),
    )


def _portal_redacted_me(payload: dict) -> dict:
    """Strip billing/subscription fields for marketing portal when caller is not an owner/admin."""
    if payload.get("portal_billing_visible"):
        return payload
    redacted = dict(payload)
    for key in (
        "subscription_access",
        "tenant_status",
        "subscription_plan",
        "trial_ends_at",
        "subscription_period_ends_at",
        "trial_days_remaining",
        "subscription_tenant_subdomain",
        "subscription_used_default_tenant_fallback",
        "company_id",
        "company_access",
    ):
        redacted[key] = None
    return redacted


@router.get("/auth/me", response_model=AuthMeResponse)
def auth_me(
    request: Request,
    user_db: Tuple[User, Session] = Depends(get_current_user),
    master_db: Session = Depends(get_master_db),
):
    """
    Return current authenticated user_id, RBAC role names, and subscription/trial context
    derived from the authenticated user's effective `company_id` (single source of truth).

    When the client sends ``X-PharmaSight-Portal: 1`` (marketing customer portal), subscription/plan
    fields are omitted unless ``portal_billing_visible`` (company admin / owner roles).
    """
    user, db = user_db
    auth_hdr = request.headers.get("Authorization")
    token = (auth_hdr[7:].strip() if auth_hdr and auth_hdr.startswith("Bearer ") else None) or None
    if token:
        pl, dec_err = decode_internal_token_or_reason(token)
        if pl:
            logger.debug(
                "auth/me bearer claims sub=%s jti=%s exp=%s company_id=%s type=%s",
                pl.get(CLAIM_SUB),
                pl.get(CLAIM_JTI),
                pl.get(CLAIM_EXP),
                pl.get(CLAIM_COMPANY_ID),
                pl.get("type"),
            )
        elif dec_err:
            logger.warning("auth/me token re-decode failed (unexpected after auth): %s", dec_err)

    from app.models.user import UserBranchRole, UserRole

    rows = (
        db.query(UserRole.role_name)
        .join(UserBranchRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user.id)
        .distinct()
        .all()
    )
    roles = sorted({(r[0] or "").strip().lower() for r in (rows or []) if r and r[0]})

    # Company access (single source of truth)
    company_id = None
    company = None
    preferred = preferred_company_id_from_request(request, master_db)
    jwt_cid = None
    if token:
        pl_jwt, _ = decode_internal_token_or_reason(token)
        if pl_jwt:
            try:
                raw_c = (pl_jwt.get(CLAIM_COMPANY_ID) or "").strip()
                if raw_c:
                    from uuid import UUID as _UUID

                    jwt_cid = _UUID(raw_c)
            except (ValueError, TypeError):
                jwt_cid = None
    if preferred is None and jwt_cid is not None:
        preferred = jwt_cid

    org_slug = None
    org_login_url = None
    try:
        company_id = get_effective_company_id_for_user(db, user, preferred_company_id=preferred)
        if company_id:
            from app.models.company import Company

            company = db.query(Company).filter(Company.id == company_id).first()
            tenant_row = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
            if tenant_row and tenant_row.subdomain:
                org_slug = normalize_org_slug(tenant_row.subdomain) or tenant_row.subdomain
                org_login_url = build_org_login_url(org_slug)
    except Exception:
        company_id = None
        company = None

    company_access = get_company_access(company)
    commercial_state = derive_commercial_access(company) if company else "active"
    commercial_access_meta = governance_access_display(commercial_state)
    subscription_access = get_subscription_access(company)

    governance_summary: Optional[Dict[str, Any]] = None
    if company_id and company:
        try:
            from app.services.company_governance_service import compile_governance_profile

            gov = compile_governance_profile(db, company_id, company=company)
            governance_summary = {
                "commercial_access": gov.get("commercial_access"),
                "uses_legacy_governance": gov.get("uses_legacy_governance"),
                "organization_operating_model": gov.get("organization_operating_model"),
                "governance_problem_count": len(gov.get("governance_problems") or []),
            }
        except Exception:
            governance_summary = None
    trial_expires_at = getattr(company, "trial_expires_at", None) if company else None
    from app.utils.company_plan_limits import company_trial_expires_effective

    # Period end drives trial countdown banners only — not paid ``active`` access.
    period_end: Optional[datetime] = None
    if commercial_state in ("trial", "demo", "expired"):
        period_end = company_trial_expires_effective(company) if company else None
        if period_end is None:
            period_end = trial_expires_at

    trial_days_remaining: Optional[int] = None
    n = datetime.now(timezone.utc)
    end_for_days = period_end
    if end_for_days is not None and commercial_state in ("trial", "demo", "expired"):
        end = end_for_days
        if getattr(end, "tzinfo", None) is None:
            end = end.replace(tzinfo=timezone.utc)
        delta_days = (end - n).days
        if commercial_state in ("trial", "demo"):
            trial_days_remaining = max(0, delta_days)
        elif commercial_state == "expired":
            trial_days_remaining = 0

    portal_billing_visible = bool(PORTAL_BILLING_ROLES.intersection(set(roles)))
    portal_wa_raw = (
        getattr(company, "portal_upgrade_whatsapp", None) if company else None
    )
    portal_whatsapp_e164 = normalize_whatsapp_e164(
        str(portal_wa_raw).strip() if portal_wa_raw else None,
        default_e164=settings.PORTAL_DEFAULT_WHATSAPP or "0708476318",
    )

    row = {
        "user_id": str(user.id),
        "roles": roles,
        "username": getattr(user, "username", None),
        "full_name": getattr(user, "full_name", None),
        "company_name": getattr(company, "name", None) if company else None,
        "portal_billing_visible": portal_billing_visible,
        "portal_whatsapp_e164": portal_whatsapp_e164,
        "subscription_access": subscription_access,
        "commercial_access_state": commercial_state,
        "commercial_access_label": commercial_access_meta.get("label"),
        "tenant_status": getattr(company, "subscription_status", None) if company else None,
        "subscription_plan": getattr(company, "subscription_plan", None) if company else None,
        "trial_ends_at": trial_expires_at if commercial_state in ("trial", "demo", "expired") else None,
        "subscription_period_ends_at": period_end,
        "trial_days_remaining": trial_days_remaining,
        "subscription_tenant_subdomain": None,
        "subscription_used_default_tenant_fallback": False,
        "company_id": str(company_id) if company_id else None,
        "company_access": company_access,
        "org_slug": org_slug,
        "org_login_url": org_login_url,
        "governance": governance_summary,
    }

    hdr = (request.headers.get("x-pharmasight-portal") or "").strip().lower()
    if hdr in ("1", "true", "yes"):
        return _portal_redacted_me(row)

    return row


def _find_user_in_shared_db(normalized_username: str, check_email: bool) -> Optional[User]:
    """Single-DB user lookup (shared SessionLocal)."""
    db = SessionLocal()
    try:
        return _find_user_in_db(db, normalized_username, check_email)
    finally:
        db.close()


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
    *,
    company_id: Optional[Any] = None,
) -> UsernameLoginResponse:
    """Build login response; if user has password_hash and password matches, add tokens."""
    from uuid import UUID as _UUID

    subdomain = normalize_org_slug(tenant.subdomain if tenant else None)
    company_id_str = None
    if company_id is not None:
        company_id_str = str(company_id)
    elif db:
        resolved = get_effective_company_id_for_user(db, user)
        company_id_str = str(resolved) if resolved else None
    org_login_url = build_org_login_url(subdomain) if subdomain else None
    out = UsernameLoginResponse(
        email=user.email,
        user_id=str(user.id),
        username=getattr(user, "username", None) or None,
        full_name=user.full_name,
        tenant_subdomain=subdomain,
        company_id=company_id_str,
        org_slug=subdomain,
        org_login_url=org_login_url,
        must_change_password=getattr(user, "must_change_password", None),
    )
    if getattr(user, "password_hash", None) and password is not None:
        if verify_password(password, user.password_hash):
            pref = None
            if company_id_str:
                try:
                    pref = _UUID(company_id_str)
                except (ValueError, TypeError):
                    pref = None
            out.access_token = create_access_token(
                str(user.id), user.email, subdomain, company_id=company_id_str
            )
            out.refresh_token = create_refresh_token(
                str(user.id), user.email, subdomain, company_id=company_id_str
            )
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
    tenants = master_db.query(Tenant).filter(Tenant.database_url.isnot(None)).limit(MAX_TENANTS_TO_SEARCH).all()
    subdomains = [t.subdomain for t in tenants]
    logger.info("Tenant discovery: %d tenant(s) with database_url (subdomains: %s)", len(tenants), subdomains)
    if not tenants:
        logger.warning("No tenants with database_url set. Check public.tenants.database_url for multi-DB setups.")
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


def _login_blocked_company_message() -> str:
    return (
        "This organization is no longer active. Your account was part of an organization that has been deactivated. "
        "Please contact your administrator or support if you need access."
    )


def _resolve_user_for_org_login(
    db: Session,
    normalized_username: str,
    check_email: bool,
    company_id,
) -> Optional[User]:
    """
    Find user for org-scoped login. Prefer branch-assigned users; for legacy accounts with
    no roles anywhere, auto-assign HQ in this company once (same as branch list lazy grant).
    """
    user = find_user_for_company_login(db, normalized_username, check_email, company_id)
    if user:
        return user
    user = _find_user_in_db(db, normalized_username, check_email)
    if not user:
        return None
    assigned = company_ids_for_user(db, user.id)
    if assigned and company_id not in assigned:
        return None
    if not assigned:
        ensure_user_assigned_to_company_hq(db, user.id, company_id, commit=True)
    return user


@router.post("/auth/username-login", response_model=UsernameLoginResponse)
@limiter.limit("5/minute")
def username_login(
    request: Request,
    body: UsernameLoginRequest,
    master_db: Session = Depends(get_master_db),
):
    """
    Password login scoped to an organization when ``org`` / ``tenant`` context is present.

    Without org context, login succeeds only when the user belongs to a single company
    (branch assignment) or the database has a single company (dev / legacy).
    """
    try:
        from app.models.company import Company
        from uuid import UUID as _UUID

        normalized_username = body.username.lower().strip()
        check_email = "@" in body.username
        org_slug = (
            normalize_org_slug(body.org)
            or normalize_org_slug(body.tenant)
            or org_slug_from_request(request)
        )
        logger.info(
            "username-login attempt user=%s org=%s",
            normalized_username[:50],
            org_slug or "(none)",
        )

        db = SessionLocal()
        try:
            if org_slug:
                tenant = tenant_for_org_slug(master_db, org_slug)
                if not tenant or not tenant.company_id:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Unknown organization. Check your login link or ask your administrator for the correct URL.",
                    )
                company = db.query(Company).filter(Company.id == tenant.company_id).first()
                if company and get_company_access(company) == "blocked":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=_login_blocked_company_message(),
                    )
                user = _resolve_user_for_org_login(
                    db, normalized_username, check_email, tenant.company_id
                )
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid username or password for this organization.",
                    )
                _require_password_if_internal(user, body.password)
                ensure_user_assigned_to_company_hq(db, user.id, tenant.company_id, commit=True)
                _enforce_login_company_access(db, user, tenant.company_id)
                resp = _build_login_response(
                    user,
                    tenant,
                    body.password,
                    db=db,
                    company_id=tenant.company_id,
                )
                if resp.refresh_token:
                    _persist_refresh_token_on_login(tenant, str(user.id), resp.refresh_token)
                return resp

            user = _find_user_in_db(db, normalized_username, check_email)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password",
                )

            assigned = company_ids_for_user(db, user.id)
            if len(assigned) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Your account belongs to more than one organization. "
                        "Sign in using your organization's link (it includes ?org= in the URL). "
                        "Ask your administrator if you do not have it."
                    ),
                )

            company_id = assigned[0] if len(assigned) == 1 else get_effective_company_id_for_user(db, user)
            if not company_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        "No branch is assigned to your account yet. "
                        "Ask your administrator to assign you to a branch, or use your organization's login link."
                    ),
                )

            tenant = master_db.query(Tenant).filter(Tenant.company_id == company_id).first()
            if not tenant:
                tenant = ensure_tenant_row_for_company(master_db, _UUID(str(company_id)))

            _require_password_if_internal(user, body.password)
            ensure_user_assigned_to_company_hq(db, user.id, company_id, commit=True)
            _enforce_login_company_access(db, user, company_id)
            resp = _build_login_response(
                user,
                tenant,
                body.password,
                db=db,
                company_id=company_id,
            )
            if resp.refresh_token:
                _persist_refresh_token_on_login(tenant, str(user.id), resp.refresh_token)
            return resp
        finally:
            db.close()
    except OperationalError as e:
        _raise_http_for_db_unreachable(e)


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
                    or "already registered with this phone number" in msg_lc
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

    return start_demo_api_response(result, str(body.email))


@router.post("/auth/exchange-signup-handoff", response_model=UsernameLoginResponse)
@limiter.limit("30/minute")
def auth_exchange_signup_handoff(
    request: Request,
    body: ExchangeSignupHandoffRequest,
    master_db: Session = Depends(get_master_db),
):
    """
    Exchange a short-lived signup handoff JWT (from public marketing signup) for the same payload
    as username-login: access + refresh tokens. Persists refresh token like a normal login.
    """
    parsed = decode_signup_handoff_token((body.token or "").strip())
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired handoff token.",
        )
    subd = parsed.get("tenant_subdomain")
    tenant = None
    if subd:
        tenant = master_db.query(Tenant).filter(Tenant.subdomain == subd).first()
    if parsed.get("refresh_token"):
        _persist_refresh_token_on_login(tenant, parsed["user_id"], parsed["refresh_token"])
    return UsernameLoginResponse(
        email=parsed["email"],
        user_id=parsed["user_id"],
        username=parsed.get("username"),
        tenant_subdomain=subd,
        access_token=parsed["access_token"],
        refresh_token=parsed["refresh_token"],
        must_change_password=False,
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
    if tenant and (tenant.database_url or "").strip():
        if _normalize_db_url(tenant.database_url) == _normalize_db_url(settings.database_connection_string):
            tenant = None
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
    # Single shared app DB: login persists refresh_tokens via SessionLocal when tenant is None or when
    # tenant DB is unreachable. If public.tenants.database_url still points at the same physical DB,
    # using tenant_db_session can split refresh state (row visible in one pool, not the other) and
    # cause 401 on refresh + immediate client logout loops after login.
    if tenant and (tenant.database_url or "").strip():
        if _normalize_db_url(tenant.database_url) == _normalize_db_url(settings.database_connection_string):
            tenant = None
    if not tenant or not tenant.database_url:
        session = SessionLocal()
        try:
            # One refresh per user at a time across uvicorn workers (Render); avoids double-rotate 401s.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(CAST(:uid AS text)))"),
                {"uid": str(sub)},
            )
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
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(CAST(:uid AS text)))"),
            {"uid": str(sub)},
        )
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
        use_isolated_tenant_db = bool(
            tenant
            and (tenant.database_url or "").strip()
            and _normalize_db_url(tenant.database_url)
            != _normalize_db_url(settings.database_connection_string)
        )
        if use_isolated_tenant_db:
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
    if hasattr(user, "must_change_password"):
        user.must_change_password = False
    db.commit()
    invalidate_auth_cache_for_user(user.id)
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
    user = _find_user_in_shared_db(email_or_username, check_email)
    found_list = [(None, user)] if user else []
    if not found_list:
        logger.info("[request-reset] No user found for %s; not sending email (same response for security)", email_or_username[:3] + "***")
        print("[request-reset] No user found for this email; no email sent. (Use an email that exists in your tenant DB.)")
        return {"message": "If an account exists, you will receive a reset link.", "email_sent": False}
    tenant, user = found_list[0]
    try:
        if tenant is None:
            db_chk = SessionLocal()
            try:
                if _company_blocked_for_user(db_chk, user):
                    return {"message": "If an account exists, you will receive a reset link.", "email_sent": False}
            finally:
                db_chk.close()
        else:
            with tenant_db_session(tenant) as db_chk:
                if _company_blocked_for_user(db_chk, user):
                    return {"message": "If an account exists, you will receive a reset link.", "email_sent": False}
    except Exception:
        logger.debug("[request-reset] company access check skipped due to DB error", exc_info=True)
    subdomain_for_token = tenant.subdomain if tenant else LEGACY_TENANT_SUBDOMAIN
    logger.info("[request-reset] User found, queuing reset email to %s (tenant=%s)", user.email, subdomain_for_token)
    reset_token = create_reset_token(str(user.id), subdomain_for_token)
    base = get_public_base_url(request)
    reset_url = f"{base.rstrip('/')}/app#password-reset?token={reset_token}"
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
                sign_in_url = build_org_login_url(
                    subdomain_for_token,
                    base_url=base.rstrip("/"),
                )
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
            if _company_blocked_for_user(db, user):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This organization is no longer active.")
            pw_error = validate_new_password(body.new_password)
            if pw_error:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
            user.password_hash = hash_password(body.new_password)
            user.password_updated_at = datetime.now(timezone.utc)
            user.password_set = True
            if hasattr(user, "must_change_password"):
                user.must_change_password = False
            db.commit()
            invalidate_auth_cache_for_user(user.id)
        finally:
            db.close()
        return {"message": "Password reset. Sign in with your username and password."}
    tenant = master_db.query(Tenant).filter(Tenant.subdomain == tenant_subdomain).first()
    if not tenant or not tenant.database_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    with tenant_db_session(tenant) as db:
        user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if _company_blocked_for_user(db, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This organization is no longer active.")
        pw_error = validate_new_password(body.new_password)
        if pw_error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
        user.password_hash = hash_password(body.new_password)
        user.password_updated_at = datetime.now(timezone.utc)
        user.password_set = True
        if hasattr(user, "must_change_password"):
            user.must_change_password = False
        db.commit()
        invalidate_auth_cache_for_user(user.id)
    return {"message": "Password reset. Sign in with your username and password."}
