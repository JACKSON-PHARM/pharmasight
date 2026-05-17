"""
Company and Branch models
"""
from sqlalchemy import Column, String, Boolean, Text, Date, ForeignKey, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class Company(Base):
    """Company model"""
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    registration_number = Column(String(100))
    pin = Column(String(50))
    logo_url = Column(Text)
    phone = Column(String(50))
    email = Column(String(255))
    address = Column(Text)
    currency = Column(String(10), default="KES")
    timezone = Column(String(50), default="Africa/Nairobi")
    fiscal_start_date = Column(Date)
    # Platform subscription fields (managed by platform admin)
    subscription_plan = Column(Text, nullable=True)
    subscription_status = Column(Text, nullable=True)
    trial_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Optional SaaS caps (enforced from companies only; never read from Tenant)
    product_limit = Column(Integer, nullable=True)
    branch_limit = Column(Integer, nullable=True)
    user_limit = Column(Integer, nullable=True)
    # Stripe (Phase 2 — company-scoped; never mirrored on tenants)
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    # Marketing customer portal: optional WhatsApp override for upgrade CTAs (wa.me)
    portal_upgrade_whatsapp = Column(String(32), nullable=True)
    # KRA / eTIMS tenant activation (execution plane); infra toggles live in ENV only.
    kra_enabled = Column(Boolean, nullable=False, default=False)
    kra_mode = Column(String(32), nullable=False, default="sandbox")
    kra_onboarded_at = Column(TIMESTAMP(timezone=True), nullable=True)
    # Platform governance: organizational intent (parent of branch fiscal doctrine).
    organization_operating_model = Column(String(40), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    branches = relationship("Branch", back_populates="company", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="company", cascade="all, delete-orphan")
    suppliers = relationship("Supplier", back_populates="company", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="company", cascade="all, delete-orphan")
    modules = relationship(
        "CompanyModule",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    kra_profile = relationship(
        "CompanyKraProfile",
        uselist=False,
        back_populates="company",
        cascade="all, delete-orphan",
    )


class Branch(Base):
    """
    Branch model
    
    Branch code is REQUIRED and used in invoice numbering.
    Format: {BRANCH_CODE}-INV-YYYY-000001
    """
    __tablename__ = "branches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False)  # REQUIRED for invoice numbering
    address = Column(Text)
    phone = Column(String(50))
    till_number = Column(String(50), nullable=True)  # Till number for sales invoice footer (branch characteristic)
    paybill = Column(String(50), nullable=True)  # Paybill for sales invoice footer
    is_active = Column(Boolean, default=True)
    is_hq = Column(Boolean, default=False)  # HQ branch: exclusive create items, suppliers, users, roles, branches
    # Fiscal doctrine for this branch only (not patient entry pathway). See invoice_workflow_policy service.
    invoice_workflow_type = Column(
        String(40),
        nullable=False,
        default="RETAIL_COUNTER",
        server_default="RETAIL_COUNTER",
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="branches")
    settings = relationship("BranchSetting", back_populates="branch", uselist=False, cascade="all, delete-orphan")
    etims_credentials = relationship(
        "BranchEtimsCredentials",
        back_populates="branch",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BranchSetting(Base):
    """Per-branch settings (e.g. branch inventory: allow manual transfer/receipt)."""
    __tablename__ = "branch_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    allow_manual_transfer = Column(Boolean, nullable=False, default=True)
    allow_manual_receipt = Column(Boolean, nullable=False, default=True)
    allow_adjust_cost = Column(Boolean, nullable=False, default=True)
    cost_outlier_threshold_pct = Column(Numeric(10, 2), nullable=True)
    min_margin_retail_pct_override = Column(Numeric(10, 2), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    branch = relationship("Branch", back_populates="settings")


class BranchEtimsCredentials(Base):
    """Per-branch eTIMS OSCU credentials (sandbox/production)."""

    __tablename__ = "branch_etims_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, unique=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    kra_bhf_id = Column(String(50), nullable=True)
    device_serial = Column(String(100), nullable=True)
    etims_solution = Column(String(50), nullable=False, default="OSCU")
    cmc_key_encrypted = Column(Text, nullable=True)
    environment = Column(String(20), nullable=False, default="sandbox")
    enabled = Column(Boolean, nullable=False, default=False)
    kra_oauth_username = Column(String(255), nullable=True)
    kra_oauth_password = Column(Text, nullable=True)
    connection_status = Column(String(30), nullable=False, default="not_configured")
    last_tested_at = Column(TIMESTAMP(timezone=True), nullable=True)
    activation_status = Column(String(30), nullable=False, default="draft")
    validation_status = Column(String(30), nullable=False, default="unknown")
    last_validation_error = Column(Text, nullable=True)
    last_validation_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_successful_sync_at = Column(TIMESTAMP(timezone=True), nullable=True)
    apigee_app_id = Column(String(255), nullable=True)
    client_tax_pin = Column(String(50), nullable=True)
    integrator_pin = Column(Text, nullable=True)
    consumer_key = Column(String(255), nullable=True)
    consumer_secret_encrypted = Column(Text, nullable=True)
    credential_version = Column(Integer, nullable=False, default=1)
    credential_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    token_last_checked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    token_status = Column(String(30), nullable=False, default="unknown")
    token_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    failed_validation_count = Column(Integer, nullable=False, default=0)
    activation_blockers = Column(Text, nullable=True)
    # insertStockIO SAR sequence (last successful sarNo for this OSCU branch).
    kra_last_stock_io_sar_no = Column(Integer, nullable=False, default=0)
    # saveTrnsSalesOsdc invcNo sequence (next value to send; KRA monotonic per branch, not POS invoice_no).
    kra_osdc_next_invc_no = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    branch = relationship("Branch", back_populates="etims_credentials")
    company = relationship("Company")

