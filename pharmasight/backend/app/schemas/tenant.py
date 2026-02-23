"""
Pydantic schemas for tenant management
"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class TenantBase(BaseModel):
    """Base tenant schema"""
    name: str = Field(..., min_length=1, max_length=255)
    admin_email: EmailStr
    admin_full_name: Optional[str] = Field(None, max_length=255, description="Admin full name for username generation (e.g., 'Dr. Jackson' -> 'D-JACKSON')")
    phone: Optional[str] = Field(None, max_length=50)


class TenantCreate(TenantBase):
    """Schema for creating a new tenant"""
    pass


class TenantUpdate(BaseModel):
    """Schema for updating a tenant"""
    name: Optional[str] = None
    admin_email: Optional[EmailStr] = None
    admin_full_name: Optional[str] = Field(None, max_length=255, description="Admin full name for username generation")
    phone: Optional[str] = Field(None, max_length=50)
    custom_domain: Optional[str] = None
    status: Optional[str] = None
    trial_ends_at: Optional[datetime] = Field(None, description="When the trial period ends (UTC). Controls trial usage days.")
    supabase_storage_url: Optional[str] = Field(None, description="Optional: Supabase project URL for this tenant's storage. When set with service role key, PDF/logo signed URLs use this project.")
    supabase_storage_service_role_key: Optional[str] = Field(None, description="Optional: Service role key for tenant's Supabase storage. Only set when using per-tenant Supabase project.")


class TenantProvisionRequest(BaseModel):
    """Schema for provisioning a tenant database (paste Supabase Postgres URL)"""
    database_url: str = Field(..., min_length=1, description="Direct Postgres URI from Supabase project (Settings → Database → URI)")


class TenantInitializeRequest(BaseModel):
    """Schema for initializing a tenant database (empty DB only)."""
    database_url: str = Field(..., min_length=1, description="Direct Postgres URI from Supabase (Settings → Database → URI)")


class TenantResponse(TenantBase):
    """Schema for tenant response. admin_email is str so DB values like dev@localhost are accepted."""
    admin_email: str  # Override EmailStr to allow dev/localhost emails from DB
    id: UUID
    subdomain: str
    custom_domain: Optional[str] = None
    status: str
    database_name: Optional[str] = None
    phone: Optional[str] = None
    admin_full_name: Optional[str] = None
    is_provisioned: bool = False
    provisioned_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    trial_ends_at: Optional[datetime] = None
    # Per-tenant Supabase storage (master DB only). Key is masked in responses for security.
    supabase_storage_url: Optional[str] = None
    supabase_storage_configured: bool = False  # True when service role key is set (key value never returned)

    class Config:
        from_attributes = True


class TenantListResponse(BaseModel):
    """Schema for listing tenants"""
    tenants: List[TenantResponse]
    total: int


class TenantInviteCreate(BaseModel):
    """Schema for creating an invite"""
    # tenant_id is in the path, not in the body
    expires_in_days: int = Field(default=7, ge=1, le=30)
    send_email: bool = Field(default=True, description="Send invite link to tenant admin email")


class TenantInviteResponse(BaseModel):
    """Schema for invite response"""
    id: UUID
    tenant_id: UUID
    token: str
    username: Optional[str] = None  # Generated username for the admin user
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime
    email_sent: Optional[bool] = None  # True if invite was emailed to admin_email
    setup_url: Optional[str] = None  # Full URL for setup (uses APP_PUBLIC_URL so email and copy link match on Render)
    
    class Config:
        from_attributes = True


class SubscriptionPlanResponse(BaseModel):
    """Schema for subscription plan"""
    id: UUID
    name: str
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    max_users: Optional[int] = None
    max_branches: Optional[int] = None
    max_items: Optional[int] = None
    included_modules: Optional[List[str]] = None
    is_active: bool
    
    class Config:
        from_attributes = True


class TenantSubscriptionResponse(BaseModel):
    """Schema for tenant subscription"""
    id: UUID
    tenant_id: UUID
    plan_id: UUID
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class TenantModuleResponse(BaseModel):
    """Schema for tenant module"""
    id: UUID
    tenant_id: UUID
    module_name: str
    is_enabled: bool
    expires_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class OnboardingSignupRequest(BaseModel):
    """Schema for client signup"""
    email: EmailStr
    company_name: str = Field(..., min_length=1, max_length=255)


class OnboardingSignupResponse(BaseModel):
    """Schema for signup response"""
    success: bool
    message: str
    tenant_id: Optional[UUID] = None
