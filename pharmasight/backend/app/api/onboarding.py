"""
Onboarding API - Client signup and setup.

Authority: database-per-tenant. Users live in TENANT DB only.
- Master: validate token, mark invite used.
- Tenant DB: username derivation, user create. Resolved from token → tenant.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database_master import get_master_db
from app.dependencies import tenant_or_app_db_session
from app.schemas.tenant import OnboardingSignupRequest, OnboardingSignupResponse
from datetime import datetime, timezone

from app.services.onboarding_service import OnboardingService
from app.services.invite_service import InviteService
from app.utils.public_url import get_public_base_url
from app.utils.username_generator import generate_username_from_name
from app.utils.auth_internal import hash_password
from app.models.user import User, UserRole, UserBranchRole
from app.models.company import Company, Branch

router = APIRouter()


def _ensure_company_and_branch_for_tenant(tenant_db: Session, tenant) -> None:
    """
    Single-DB: ensure a Company and Branch exist for this tenant (name = tenant.name). Create if missing.
    """
    company = tenant_db.query(Company).filter(Company.name == tenant.name).first()
    if not company:
        company = Company(
            name=tenant.name,
            currency="KES",
            timezone="Africa/Nairobi",
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
def signup(http_request: Request, request: OnboardingSignupRequest, db: Session = Depends(get_master_db)):
    """
    Client signup endpoint
    Only requires email and company name
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
    Uses MASTER for token/tenant; TENANT DB for username derivation (per-tenant uniqueness).
    """
    tenant = OnboardingService.validate_invite_token(token, master_db)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invite token",
        )
    with tenant_or_app_db_session(tenant) as tenant_db:
        username = _username_for_tenant(tenant, tenant_db)
    return {
        "valid": True,
        "tenant_id": str(tenant.id),
        "subdomain": tenant.subdomain,
        "company_name": tenant.name,
        "username": username,
        "admin_email": tenant.admin_email,
    }


@router.post("/onboarding/complete-tenant-invite")
def complete_tenant_invite(
    body: CompleteTenantInviteRequest,
    master_db: Session = Depends(get_master_db),
):
    """
    Complete tenant invite: validate token, create user in TENANT DB, mark invite used.

    Uses MASTER for token/tenant and mark_invite_used only.
    User create/lookup is in TENANT DB only. No global user linking or email pre-check.
    """
    import uuid as _uuid

    tenant = OnboardingService.validate_invite_token(body.token, master_db)
    if not tenant:
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

    with tenant_or_app_db_session(tenant) as tenant_db:
        username = _username_for_tenant(tenant, tenant_db)
        existing_by_id = tenant_db.query(User).filter(User.id == uid).first()
        if existing_by_id:
            _ensure_user_branch_role_for_tenant(tenant_db, uid, tenant)
            tenant_db.commit()
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

    OnboardingService.mark_invite_used(body.token, uid, master_db)
    return {
        "success": True,
        "message": "Password set. Sign in with your username and password.",
        "username": username,
    }
