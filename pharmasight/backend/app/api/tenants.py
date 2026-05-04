"""
Tenant Management API - Admin endpoints for managing clients
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

from app.database_master import get_master_db
from app.dependencies import get_current_admin
from app.database import SessionLocal
from app.models.company import Branch, Company
from app.models.tenant import Tenant, SubscriptionPlan
from app.services.company_provisioning_service import HQBranchSpec, create_company_with_hq_branch_and_registry
from app.schemas.tenant import (
    TenantCreate, TenantResponse, TenantUpdate, TenantListResponse,
    TenantInviteCreate, TenantInviteResponse, TenantProvisionRequest,
    TenantInitializeRequest,
    SubscriptionPlanResponse,
)
from app.services.email_service import EmailService
from app.services.tenant_provisioning import initialize_tenant_database
from app.services.migration_service import get_public_table_count
from app.services.tenant_invite_service import create_tenant_invite, list_tenant_invites
from app.config import settings, is_supabase_owner_email

router = APIRouter()


# =====================================================
# TENANT CRUD OPERATIONS
# =====================================================

@router.get("/tenants", response_model=TenantListResponse)
def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """List infra tenant registry rows (Option B: no subscription/status filtering on Tenant)."""
    try:
        query = db.query(Tenant)
        if status_filter:
            # Deprecated query param: ignored — use Licensing (companies) for lifecycle.
            _ = status_filter
        
        # Apply search
        
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (Tenant.name.ilike(search_term)) |
                (Tenant.subdomain.ilike(search_term)) |
                (Tenant.admin_email.ilike(search_term))
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        tenants = query.order_by(Tenant.created_at.desc()).offset(skip).limit(limit).all()
        
        return TenantListResponse(
            tenants=[_tenant_to_response(t) for t in tenants],
            total=total
        )
    except Exception as e:
        # Log the error for debugging
        import traceback
        error_msg = f"Error listing tenants: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        )


def _tenant_to_response(tenant: Tenant) -> TenantResponse:
    """Build TenantResponse; never expose supabase_storage_service_role_key, set supabase_storage_configured."""
    r = TenantResponse.model_validate(tenant)
    return r.model_copy(update={
        "supabase_storage_configured": bool((getattr(tenant, "supabase_storage_service_role_key", None) or "").strip()),
    })

@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """Get tenant by ID"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    return _tenant_to_response(tenant)


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant_data: TenantCreate,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """Create a new tenant (manual creation)"""
    # Generate subdomain from company name
    subdomain = _generate_subdomain(tenant_data.name, db)
    
    # Check if email already exists
    existing = db.query(Tenant).filter(Tenant.admin_email == tenant_data.admin_email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant with email {tenant_data.admin_email} already exists"
        )

    # Do not use Supabase project/account owner email as tenant admin (causes Auth "already registered").
    if is_supabase_owner_email(tenant_data.admin_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This email is the Supabase project/account owner. Use a different email for the tenant admin to avoid sign-in conflicts."
        )

    app_db = SessionLocal()
    try:
        _company, _branch, tenant = create_company_with_hq_branch_and_registry(
            app_db,
            db,
            company_kwargs={
                "name": tenant_data.name,
                "currency": "KES",
                "timezone": "Africa/Nairobi",
                "is_active": True,
            },
            admin_email=tenant_data.admin_email,
            hq=HQBranchSpec(name="Head Office", code="HQ"),
            admin_full_name=tenant_data.admin_full_name,
            tenant_phone=tenant_data.phone,
            tenant_subdomain=subdomain,
        )
    except Exception:
        app_db.rollback()
        raise
    finally:
        app_db.close()

    return _tenant_to_response(tenant)


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """Update tenant information"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    # Update fields
    update_data = tenant_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)
    
    db.commit()
    db.refresh(tenant)
    
    return _tenant_to_response(tenant)


@router.get("/tenants/{tenant_id}/initialize-status")
def get_initialize_status(
    tenant_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """
    For Admin UI: whether to show Initialize Tenant Database form.

    Show form when database_url is null OR database_url exists but DB has zero tables.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    database_url_set = bool(tenant.database_url and tenant.database_url.strip())
    table_count: Optional[int] = None
    if database_url_set:
        try:
            table_count = get_public_table_count(tenant.database_url)
        except Exception:
            table_count = None
    can_show_initialize_form = not tenant.is_provisioned and (
        not database_url_set or (table_count is not None and table_count == 0)
    )
    return {
        "database_url_set": database_url_set,
        "table_count": table_count,
        "can_show_initialize_form": can_show_initialize_form,
        "is_provisioned": tenant.is_provisioned,
    }


@router.post("/tenants/{tenant_id}/initialize")
def initialize_tenant(
    tenant_id: UUID,
    body: TenantInitializeRequest,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """
    Initialize tenant database (admin-only). Empty DB only.

    - Connect to database_url, check public table count.
    - If > 0: 400 "Database already initialized. Refusing to run migrations."
    - If 0: run migrations, verify tables, create initial tenant admin user,
      persist database_url, database_name, is_provisioned, provisioned_at.
    - On any failure, do not mark provisioned.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    if is_supabase_owner_email(tenant.admin_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This tenant's admin email is the Supabase project/account owner. Use a different email for the tenant admin to avoid sign-in conflicts."
        )
    try:
        out = initialize_tenant_database(tenant, db, body.database_url.strip())
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    return {
        "success": True,
        "message": "Tenant database initialized. Tables created, initial admin user created. You can now create an invite.",
        "database_name": out["database_name"],
        "provisioned_at": out["provisioned_at"].isoformat(),
    }


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """Soft-delete infra row (legacy column update without using it for product access — prefer Licensing)."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    setattr(tenant, "status", "cancelled")
    db.commit()
    
    return None


# =====================================================
# TENANT INVITES
# =====================================================

@router.post("/tenants/{tenant_id}/invites", response_model=TenantInviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    invite_data: TenantInviteCreate,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """Create an invite token for tenant setup. Works when tenant is provisioned or points to the app DB (single-DB)."""
    return create_tenant_invite(
        tenant_id=tenant_id,
        invite_data=invite_data,
        db=db,
        request=request,
        background_tasks=background_tasks,
    )


@router.get("/tenants/{tenant_id}/invites", response_model=List[TenantInviteResponse])
def list_invites(
    tenant_id: UUID,
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """List all invites for a tenant"""
    return list_tenant_invites(tenant_id=tenant_id, db=db)


@router.get("/smtp-status")
def get_smtp_status(_admin: None = Depends(get_current_admin)):
    """Check SMTP configuration status (for admin debugging)"""
    is_configured = EmailService.is_configured()
    status_info = {
        "smtp_configured": is_configured,
        "smtp_host_set": bool(settings.SMTP_HOST),
        "smtp_user_set": bool(settings.SMTP_USER),
        "smtp_password_set": bool(settings.SMTP_PASSWORD),
        "smtp_port": settings.SMTP_PORT,
        "email_from": settings.EMAIL_FROM,
    }
    if not is_configured:
        missing = []
        if not settings.SMTP_HOST:
            missing.append("SMTP_HOST")
        if not settings.SMTP_USER:
            missing.append("SMTP_USER")
        if not settings.SMTP_PASSWORD:
            missing.append("SMTP_PASSWORD")
        status_info["missing_variables"] = missing
        status_info["message"] = f"SMTP not configured. Missing: {', '.join(missing)}"
    else:
        status_info["message"] = "SMTP is configured (emails will be sent in background tasks)"
    return status_info


# =====================================================
# SUBSCRIPTION PLANS
# =====================================================

@router.get("/plans", response_model=List[SubscriptionPlanResponse])
def list_plans(
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """List all subscription plans"""
    plans = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True
    ).order_by(SubscriptionPlan.price_monthly.asc()).all()
    
    return [SubscriptionPlanResponse.model_validate(p) for p in plans]


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def _generate_subdomain(company_name: str, db: Session) -> str:
    """Generate a unique subdomain from company name"""
    # Convert to lowercase, remove special chars, replace spaces with hyphens
    base = company_name.lower()
    base = ''.join(c if c.isalnum() or c in ('-', '_') else '-' for c in base)
    base = '-'.join(base.split())  # Replace spaces with hyphens
    base = base.strip('-')  # Remove leading/trailing hyphens
    
    # Limit length
    if len(base) > 50:
        base = base[:50]
    
    # Check if available
    subdomain = base
    counter = 1
    while db.query(Tenant).filter(Tenant.subdomain == subdomain).first():
        subdomain = f"{base}{counter}"
        counter += 1
    
    return subdomain
