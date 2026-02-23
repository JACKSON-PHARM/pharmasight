"""
Tenant management models for multi-tenant SaaS
"""
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Integer, Numeric, ARRAY, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database_master import MasterBase as Base


class Tenant(Base):
    """Tenant (client) model"""
    __tablename__ = "tenants"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    subdomain = Column(String(100), unique=True, nullable=False)
    custom_domain = Column(String(255), nullable=True)
    
    # Database connection info
    database_name = Column(String(255), nullable=True)
    database_url = Column(Text, nullable=True)  # Should be encrypted
    supabase_project_id = Column(String(255), nullable=True)
    supabase_project_ref = Column(String(255), nullable=True)
    # Per-tenant Supabase Storage (optional). When set, storage/signed URLs use this project instead of env.
    supabase_storage_url = Column(Text, nullable=True)
    supabase_storage_service_role_key = Column(Text, nullable=True)
    is_provisioned = Column(Boolean, default=False, nullable=False)
    provisioned_at = Column(DateTime(timezone=True), nullable=True)

    # Status
    status = Column(String(20), default='trial', nullable=False)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    
    # Admin user info
    admin_email = Column(String(255), nullable=False)
    admin_full_name = Column(String(255), nullable=True)  # For username generation
    admin_user_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Contact info
    phone = Column(String(50), nullable=True)
    
    # Relationships
    invites = relationship("TenantInvite", back_populates="tenant", cascade="all, delete-orphan")
    subscriptions = relationship("TenantSubscription", back_populates="tenant", cascade="all, delete-orphan")
    modules = relationship("TenantModule", back_populates="tenant", cascade="all, delete-orphan")
    
    __table_args__ = (
        CheckConstraint("status IN ('trial', 'active', 'suspended', 'cancelled', 'past_due')", name="valid_status"),
    )


class TenantInvite(Base):
    """Invite tokens for tenant setup"""
    __tablename__ = "tenant_invites"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # Admin user ID in tenant's database
    
    token = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    tenant = relationship("Tenant", back_populates="invites")


class SubscriptionPlan(Base):
    """Subscription plan definitions"""
    __tablename__ = "subscription_plans"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    
    # Pricing
    price_monthly = Column(Numeric(10, 2), nullable=True)
    price_yearly = Column(Numeric(10, 2), nullable=True)
    
    # Limits
    max_users = Column(Integer, nullable=True)
    max_branches = Column(Integer, nullable=True)
    max_items = Column(Integer, nullable=True)
    
    # Features
    included_modules = Column(ARRAY(String), nullable=True)
    
    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    subscriptions = relationship("TenantSubscription", back_populates="plan")


class TenantSubscription(Base):
    """Active subscriptions for tenants"""
    __tablename__ = "tenant_subscriptions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=False)
    
    status = Column(String(20), default='trial', nullable=False)
    
    # Billing period
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    
    # Cancellation
    cancel_at_period_end = Column(Boolean, default=False)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Stripe integration
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    tenant = relationship("Tenant", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    
    __table_args__ = (
        CheckConstraint("status IN ('trial', 'active', 'cancelled', 'past_due', 'suspended')", name="valid_subscription_status"),
    )


class TenantModule(Base):
    """Feature flags per tenant"""
    __tablename__ = "tenant_modules"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    module_name = Column(String(100), nullable=False)
    
    is_enabled = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # NULL = perpetual
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    tenant = relationship("Tenant", back_populates="modules")
    
    __table_args__ = (
        {"extend_existing": True},
    )
