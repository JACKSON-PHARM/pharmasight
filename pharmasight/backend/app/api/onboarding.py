"""
Onboarding API - Client signup and setup.

Authority: database-per-tenant. Users live in TENANT DB only.
- Master: validate token, mark invite used.
- Tenant DB: username derivation, user create. Resolved from token → tenant.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from app.database_master import get_master_db
from app.database import SessionLocal
from app.dependencies import tenant_or_app_db_session
from app.schemas.tenant import OnboardingSignupRequest, OnboardingSignupResponse
from datetime import datetime, timedelta, timezone

from app.config import settings

from app.services.onboarding_service import OnboardingService
from app.rate_limit import limiter
from app.services.invite_service import InviteService
from app.utils.public_url import get_public_base_url
from app.utils.username_generator import generate_username_from_name
from app.utils.auth_internal import hash_password
from app.models.user import User, UserRole, UserBranchRole
from app.models.company import Company, Branch
from app.services.branch_settings_service import ensure_default_branch_settings

router = APIRouter()

# 409 for consumed setup links (master TenantInvite.used_at) and duplicate DB rows on retry.
# Same message when invite is no longer valid for completion (avoids frontend retry loops surfacing as 5xx).
_INVITE_ALREADY_COMPLETED_MSG = "Invite already completed. Please log in."


def _ensure_company_and_branch_for_tenant(tenant_db: Session, tenant) -> None:
    """
    Single-DB: ensure a Company and Branch exist for this tenant (name = tenant.name). Create if missing.
    """
    company = tenant_db.query(Company).filter(Company.name == tenant.name).first()
    if not company:
        trial_days = getattr(settings, "DEFAULT_COMPANY_TRIAL_DAYS", None) or getattr(
            settings, "DEMO_DURATION_DAYS", None
        )
        try:
            trial_days = int(trial_days) if trial_days is not None else 14
        except (TypeError, ValueError):
            trial_days = 14
        if trial_days < 1:
            trial_days = 14
        trial_end = datetime.now(timezone.utc) + timedelta(days=trial_days)
        company = Company(
            name=tenant.name,
            currency="KES",
            timezone="Africa/Nairobi",
            subscription_status=None,
            trial_expires_at=trial_end,
            is_active=True,
        )
        tenant_db.add(company)
        tenant_db.flush()
    branch = tenant_db.query(Branch).filter(Branch.company_id == company.id).first()
    if not branch:
        branch = Branch(
            company_id=company.id,
            name="Head Office",
            code="HQ",
            is_active=True,
            is_hq=True,
        )
        tenant_db.add(branch)
        tenant_db.flush()
        ensure_default_branch_settings(tenant_db, branch.id)


def _sync_master_tenant_company_id(master_db: Session, tenant, tenant_db: Session, user_id) -> None:
    """Persist tenants.company_id from the user's branch assignment (Option B)."""
    link = (
        tenant_db.query(Branch.company_id)
        .join(UserBranchRole, UserBranchRole.branch_id == Branch.id)
        .filter(UserBranchRole.user_id == user_id)
        .first()
    )
    if link and link[0] is not None:
        tenant.company_id = link[0]
        master_db.flush()


def _ensure_user_branch_role_for_tenant(tenant_db: Session, user_id, tenant) -> None:
    """
    Single-DB multi-company: ensure user has a branch role so they get the correct company_id.
    Ensures Company+Branch exist, then finds or creates UserBranchRole.
    """
    _ensure_company_and_branch_for_tenant(tenant_db, tenant)
    company = tenant_db.query(Company).filter(Company.name == tenant.name).first()
    if not company:
        return
    branch = tenant_db.query(Branch).filter(Branch.company_id == company.id).first()
    if not branch:
        return
    admin_role = tenant_db.query(UserRole).filter(UserRole.role_name == "admin").first()
    if not admin_role:
        admin_role = UserRole(role_name="admin", description="Company admin")
        tenant_db.add(admin_role)
        tenant_db.flush()
    existing = tenant_db.query(UserBranchRole).filter(
        UserBranchRole.user_id == user_id,
        UserBranchRole.branch_id == branch.id,
    ).first()
    if existing:
        return
    tenant_db.add(
        UserBranchRole(user_id=user_id, branch_id=branch.id, role_id=admin_role.id)
    )
    tenant_db.flush()


def _username_for_tenant(tenant, tenant_db: Session) -> str:
    """Derive username from tenant. Uses TENANT DB for uniqueness (per-tenant)."""
    generated = None
    if tenant.admin_full_name:
        try:
            generated = generate_username_from_name(tenant.admin_full_name, db_session=tenant_db)
        except Exception:
            pass
    if not generated:
        email_local = tenant.admin_email.split("@")[0]
        name_parts = email_local.replace(".", " ").replace("_", " ").replace("-", " ").split()
        if len(name_parts) >= 2:
            try:
                generated = generate_username_from_name(" ".join(name_parts), db_session=tenant_db)
            except Exception:
                generated = f"{email_local[0].upper()}-{email_local.upper()[:10]}"
        else:
            generated = f"{email_local[0].upper()}-{email_local.upper()[:10]}"
    return generated


class CompleteTenantInviteRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=8)


@router.post("/onboarding/signup", response_model=OnboardingSignupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
def signup(http_request: Request, request: OnboardingSignupRequest, db: Session = Depends(get_master_db)):
    """
    Client signup endpoint. Rate limited: 10 attempts per hour per IP.
    Only requires email and company name.
    """
    try:
        result = OnboardingService.create_tenant_from_signup(
            email=request.email,
            company_name=request.company_name,
            db=db
        )
        
        # TODO: Send welcome email with invite link
        # For now, return the token (in production, send via email)
        base_url = get_public_base_url(http_request)
        invite_url = f"{base_url.rstrip('/')}/setup?token={result['invite_token']}"
        
        return OnboardingSignupResponse(
            success=True,
            message=f"Account created! Check your email for setup instructions. Your URL: {invite_url}",
            tenant_id=result['tenant'].id
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tenant: {str(e)}"
        )


@router.get("/onboarding/validate-token/{token}")
def validate_token(
    token: str,
    master_db: Session = Depends(get_master_db),
):
    """Validate invite token; returns tenant info and username for set-password flow.
    Uses MASTER for token/tenant; TENANT DB (or app DB if tenant DB unreachable) for username.
    """
    tenant = OnboardingService.validate_invite_token(token, master_db)
    if not tenant:
        if OnboardingService.invite_token_already_used(token, master_db):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_INVITE_ALREADY_COMPLETED_MSG,
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invite token",
        )
    try:
        with tenant_or_app_db_session(tenant) as tenant_db:
            username = _username_for_tenant(tenant, tenant_db)
    except OperationalError as e:
        err_msg = str(e).strip()
        if "Tenant or user not found" not in err_msg and "FATAL:" not in err_msg.upper():
            raise
        # Tenant's DB deleted/unreachable (legacy re-invite); use app DB for username derivation.
        db = SessionLocal()
        try:
            username = _username_for_tenant(tenant, db)
        finally:
            db.close()
    return {
        "valid": True,
        "tenant_id": str(tenant.id),
        "subdomain": tenant.subdomain,
        "company_name": tenant.name,
        "username": username,
        "admin_email": tenant.admin_email,
    }


def _complete_invite_with_session(
    tenant_db: Session,
    tenant,
    uid,
    body: CompleteTenantInviteRequest,
    master_db: Session,
) -> dict:
    """Run invite-completion logic against the given tenant/app DB session. Returns response dict."""
    username = _username_for_tenant(tenant, tenant_db)
    existing_by_id = tenant_db.query(User).filter(User.id == uid).first()
    if existing_by_id:
        _ensure_user_branch_role_for_tenant(tenant_db, uid, tenant)
        tenant_db.commit()
        _sync_master_tenant_company_id(master_db, tenant, tenant_db, uid)
        OnboardingService.mark_invite_used(body.token, uid, master_db)
        return {
            "success": True,
            "message": "Account already exists. Sign in with your username and password.",
            "username": username,
        }
    # Init flow may have created User with temp UUID. Remove it before adding Supabase-backed user.
    init_user = tenant_db.query(User).filter(User.email == tenant.admin_email).first()
    if init_user:
        tenant_db.delete(init_user)
        tenant_db.flush()
    user = User(
        id=uid,
        email=tenant.admin_email,
        username=username,
        full_name=tenant.admin_full_name,
        phone=tenant.phone,
        is_active=True,
        is_pending=False,
        password_set=True,
        password_hash=hash_password(body.password),
        password_updated_at=datetime.now(timezone.utc),
    )
    tenant_db.add(user)
    tenant_db.flush()
    _ensure_user_branch_role_for_tenant(tenant_db, uid, tenant)
    tenant_db.commit()
    _sync_master_tenant_company_id(master_db, tenant, tenant_db, uid)
    OnboardingService.mark_invite_used(body.token, uid, master_db)
    return {
        "success": True,
        "message": "Password set. Sign in with your username and password.",
        "username": username,
    }


@router.post("/onboarding/complete-tenant-invite")
def complete_tenant_invite(
    body: CompleteTenantInviteRequest,
    master_db: Session = Depends(get_master_db),
):
    """
    Complete tenant invite: validate token, create user in TENANT DB (or app DB), mark invite used.

    Uses MASTER for token/tenant and mark_invite_used only.
    If the tenant's database_url points to a deleted project (e.g. re-invited legacy tenant),
    falls back to the app DB so setup can complete.
    """
    import uuid as _uuid

    try:
        tenant = OnboardingService.validate_invite_token(body.token, master_db)
    except ProgrammingError as e:
        err = str(getattr(e, "orig", e))
        if "plan_type" in err:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Master database is missing required columns (e.g. plan_type). "
                    "Apply database/master_add_tenant_demo_fields.sql to the master database, then retry."
                ),
            ) from e
        raise
    if not tenant:
        if OnboardingService.invite_token_already_used(body.token, master_db):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_INVITE_ALREADY_COMPLETED_MSG,
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invite token",
        )

    result = InviteService.create_user_with_password(
        email=tenant.admin_email,
        password=body.password,
        full_name=tenant.admin_full_name or "",
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message") or result.get("error", "Failed to create user"),
        )
    user_id = result["user_id"]
    uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    def _run_tenant_invite_completion():
        try:
            with tenant_or_app_db_session(tenant) as tenant_db:
                return _complete_invite_with_session(tenant_db, tenant, uid, body, master_db)
        except OperationalError as e:
            err_msg = str(e).strip()
            if "Tenant or user not found" not in err_msg and "FATAL:" not in err_msg.upper():
                raise
            # Tenant's database_url points to a deleted/unreachable Supabase project (legacy re-invite).
            # Use app DB so the user can complete setup in the single-DB multi-company instance.
            db = SessionLocal()
            try:
                return _complete_invite_with_session(db, tenant, uid, body, master_db)
            finally:
                db.close()

    try:
        return _run_tenant_invite_completion()
    except IntegrityError as e:
        orig = getattr(e, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        err_s = str(e).lower()
        if pgcode == "23505" or "duplicate key" in err_s or "unique constraint" in err_s:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_INVITE_ALREADY_COMPLETED_MSG,
            ) from e
        raise
