"""
Settings and Configuration models
"""
from sqlalchemy import Column, String, Text, Integer, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class CompanySetting(Base):
    """Company settings"""
    __tablename__ = "company_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    setting_key = Column(String(100), nullable=False)
    setting_value = Column(Text)
    setting_type = Column(String(50), default="string")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {"comment": "Company-level settings"},
    )


class DocumentSequence(Base):
    """
    Document numbering sequences
    
    BRANCH-SPECIFIC sequences for generating invoice numbers.
    Invoice numbers MUST include branch code.
    """
    __tablename__ = "document_sequences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String(50), nullable=False)  # SALES_INVOICE, GRN, CREDIT_NOTE, PAYMENT
    prefix = Column(String(20))  # Will include branch code
    current_number = Column(Integer, default=0)
    year = Column(Integer)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {"comment": "BRANCH-SPECIFIC document numbering. Invoice numbers MUST include branch code."},
    )


class PublicSiteSettings(Base):
    """
    Platform-level public marketing settings (singleton row: id=1).

    Used by /marketing/* pages to avoid hardcoding public contact details.
    """

    __tablename__ = "public_site_settings"

    id = Column(Integer, primary_key=True, default=1)
    support_email = Column(Text, nullable=True)
    sales_email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    whatsapp = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    logo_url = Column(Text, nullable=True)
    marketing_images = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

