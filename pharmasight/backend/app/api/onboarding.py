"""
Onboarding API - Client signup and setup.

Authority: database-per-tenant. Users live in TENANT DB only.
- Master: validate token, mark invite used.
- Tenant DB: username derivation, user create. Resolved from token → tenant.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database_master import get_master_db
from app.dependencies import tenant_db_session
from app.schemas.tenant import OnboardingSignupRequest, OnboardingSignupResponse
from app.services.onboarding_service import OnboardingService
from app.services.invite_service import InviteService
from app.utils.username_generator import generate_username_from_name
from app.models.user import User

router = APIRouter()


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
def signup(request: OnboardingSignupRequest, db: Session = Depends(get_master_db)):
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
        
        invite_url = f"https://{result['subdomain']}.pharmasight.com/setup?token={result['invite_token']}"
        
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
    with tenant_db_session(tenant) as tenant_db:
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

    with tenant_db_session(tenant) as tenant_db:
        username = _username_for_tenant(tenant, tenant_db)
        existing_by_id = tenant_db.query(User).filter(User.id == uid).first()
        if existing_by_id:
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
        )
        tenant_db.add(user)
        tenant_db.commit()

    OnboardingService.mark_invite_used(body.token, uid, master_db)
    return {
        "success": True,
        "message": "Password set. Sign in with your username and password.",
        "username": username,
    }
