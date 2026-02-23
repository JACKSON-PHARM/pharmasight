"""
Tenant Management API - Admin endpoints for managing clients
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import secrets
import string
import logging

logger = logging.getLogger(__name__)

from app.database_master import get_master_db
from app.dependencies import tenant_db_session
from app.models.tenant import Tenant, TenantInvite, SubscriptionPlan, TenantSubscription, TenantModule
from app.schemas.tenant import (
    TenantCreate, TenantResponse, TenantUpdate, TenantListResponse,
    TenantInviteCreate, TenantInviteResponse, TenantProvisionRequest,
    TenantInitializeRequest,
    SubscriptionPlanResponse, TenantSubscriptionResponse, TenantModuleResponse,
)
from app.utils.username_generator import generate_username_from_name
from app.utils.public_url import get_public_base_url
from app.services.email_service import EmailService
from app.services.tenant_provisioning import initialize_tenant_database
from app.services.migration_service import get_public_table_count
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
    db: Session = Depends(get_master_db)
):
    """List all tenants with pagination and filtering. By default excludes deleted (cancelled) tenants."""
    try:
        query = db.query(Tenant)
        # By default exclude soft-deleted (cancelled) tenants so they disappear from the list
        if status_filter:
            query = query.filter(Tenant.status == status_filter)
        else:
            query = query.filter(Tenant.status != 'cancelled')
        
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
def get_tenant(tenant_id: UUID, db: Session = Depends(get_master_db)):
    """Get tenant by ID"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    return _tenant_to_response(tenant)


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(tenant_data: TenantCreate, db: Session = Depends(get_master_db)):
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

    # Create tenant
    tenant = Tenant(
        name=tenant_data.name,
        subdomain=subdomain,
        admin_email=tenant_data.admin_email,
        admin_full_name=tenant_data.admin_full_name,
        phone=tenant_data.phone,
        status='trial',
        trial_ends_at=datetime.utcnow() + timedelta(days=14)
    )
    
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    return _tenant_to_response(tenant)


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    db: Session = Depends(get_master_db)
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
def get_initialize_status(tenant_id: UUID, db: Session = Depends(get_master_db)):
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
def delete_tenant(tenant_id: UUID, db: Session = Depends(get_master_db)):
    """Delete a tenant (soft delete by setting status to cancelled)"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    
    # Soft delete
    tenant.status = 'cancelled'
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
    db: Session = Depends(get_master_db)
):
    """Create an invite token for tenant setup. Enabled only when tenant is provisioned."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    if not tenant.is_provisioned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant database not provisioned. Initialize the database first, then create an invite."
        )

    # Generate username for admin user (tenant DB for per-tenant uniqueness)
    generated_username = None
    with tenant_db_session(tenant) as tenant_db:
        if tenant.admin_full_name:
            try:
                generated_username = generate_username_from_name(
                    tenant.admin_full_name,
                    db_session=tenant_db
                )
            except Exception as e:
                print(f"Warning: Could not generate username from admin_full_name: {e}")
        if not generated_username:
            email_local = tenant.admin_email.split('@')[0]
            name_parts = email_local.replace('.', ' ').replace('_', ' ').replace('-', ' ').split()
            if len(name_parts) >= 2:
                try:
                    generated_username = generate_username_from_name(
                        ' '.join(name_parts),
                        db_session=tenant_db
                    )
                except Exception:
                    generated_username = f"{email_local[0].upper()}-{email_local.upper()[:10]}"
            else:
                generated_username = f"{email_local[0].upper()}-{email_local.upper()[:10]}"
    
    # Generate secure token
    token = _generate_secure_token()
    
    # Create invite
    invite = TenantInvite(
        tenant_id=tenant_id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(days=invite_data.expires_in_days)
    )
    
    db.add(invite)
    db.commit()
    db.refresh(invite)
    
    # Build setup URL so email and UI use a reachable link (APP_PUBLIC_URL or inferred from request on Render)
    base_url = get_public_base_url(request)
    setup_url = f"{base_url.rstrip('/')}/setup?token={invite.token}"
    
    # Return response immediately; send email in background to avoid timeout on Render (cold start / slow SMTP)
    invite_response = TenantInviteResponse.model_validate(invite)
    invite_response.username = generated_username
    invite_response.setup_url = setup_url

    if invite_data.send_email:
        # Check SMTP config before adding background task
        smtp_configured = EmailService.is_configured()
        invite_response.email_sent = smtp_configured  # True if SMTP is configured (email will be sent in background)
        
        if not smtp_configured:
            missing = []
            if not settings.SMTP_HOST:
                missing.append("SMTP_HOST")
            if not settings.SMTP_USER:
                missing.append("SMTP_USER")
            if not settings.SMTP_PASSWORD:
                missing.append("SMTP_PASSWORD")
            logger.warning(
                f"SMTP not configured (missing: {', '.join(missing)}). "
                f"Invite created for {tenant.admin_email} but email will not be sent. "
                f"Share the link manually: {setup_url}"
            )
        else:
            # Wrapper to log background task execution
            def send_email_with_logging():
                try:
                    logger.info(f"Background task: Sending invite email to {tenant.admin_email} for tenant {tenant.name}")
                    result = EmailService.send_tenant_invite(
                        to_email=tenant.admin_email,
                        tenant_name=tenant.name,
                        setup_url=setup_url,
                        username=generated_username,
                    )
                    if result:
                        logger.info(f"Background task: Successfully sent invite email to {tenant.admin_email}")
                    else:
                        logger.warning(f"Background task: Failed to send invite email to {tenant.admin_email} (check SMTP config and Render logs)")
                except Exception as e:
                    logger.exception(f"Background task: Exception sending invite email to {tenant.admin_email}: {e}")
            
            background_tasks.add_task(send_email_with_logging)
            logger.info(f"Invite created for {tenant.admin_email}. Email sending queued in background task (SMTP configured).")
    else:
        invite_response.email_sent = False

    return invite_response


@router.get("/tenants/{tenant_id}/invites", response_model=List[TenantInviteResponse])
def list_invites(tenant_id: UUID, db: Session = Depends(get_master_db)):
    """List all invites for a tenant"""
    invites = db.query(TenantInvite).filter(
        TenantInvite.tenant_id == tenant_id
    ).order_by(TenantInvite.created_at.desc()).all()
    
    return [TenantInviteResponse.model_validate(inv) for inv in invites]


@router.get("/smtp-status")
def get_smtp_status():
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
def list_plans(db: Session = Depends(get_master_db)):
    """List all subscription plans"""
    plans = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True
    ).order_by(SubscriptionPlan.price_monthly.asc()).all()
    
    return [SubscriptionPlanResponse.model_validate(p) for p in plans]


# =====================================================
# TENANT SUBSCRIPTIONS
# =====================================================

@router.get("/tenants/{tenant_id}/subscription", response_model=TenantSubscriptionResponse)
def get_subscription(tenant_id: UUID, db: Session = Depends(get_master_db)):
    """Get tenant's current subscription"""
    subscription = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.created_at.desc()).first()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found for this tenant"
        )
    
    return TenantSubscriptionResponse.model_validate(subscription)


# =====================================================
# TENANT MODULES
# =====================================================

@router.get("/tenants/{tenant_id}/modules", response_model=List[TenantModuleResponse])
def list_modules(tenant_id: UUID, db: Session = Depends(get_master_db)):
    """List all modules for a tenant"""
    modules = db.query(TenantModule).filter(
        TenantModule.tenant_id == tenant_id
    ).all()
    
    return [TenantModuleResponse.model_validate(m) for m in modules]


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


def _generate_secure_token(length: int = 32) -> str:
    """Generate a secure random token"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))
