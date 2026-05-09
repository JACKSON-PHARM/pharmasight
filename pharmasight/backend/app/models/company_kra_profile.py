"""Company-level KRA capability profile (control-plane foundation)."""
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class CompanyKraProfile(Base):
    __tablename__ = "company_kra_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)

    module_enabled = Column(Boolean, nullable=False, default=False)
    default_environment = Column(String(20), nullable=False, default="sandbox")
    kra_trader_invoicing_system_name = Column(String(255), nullable=True)
    integrator_pin = Column(Text, nullable=True)

    onboarding_status = Column(String(30), nullable=False, default="draft")
    activation_status = Column(String(30), nullable=False, default="inactive")

    last_health_check_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_successful_sync_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_validation_status = Column(String(30), nullable=True)
    last_validation_error = Column(Text, nullable=True)
    credential_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company")
