"""
Supplier model
"""
from sqlalchemy import Column, String, Boolean, Integer, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class Supplier(Base):
    """Supplier model"""
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    pin = Column(String(50))
    contact_person = Column(String(255))
    phone = Column(String(50))
    email = Column(String(255))
    address = Column(Text)
    credit_terms = Column(Integer)  # days (legacy)
    default_payment_terms_days = Column(Integer)  # default days until payment due
    credit_limit = Column(Numeric(20, 4))  # NULL = no limit
    allow_over_credit = Column(Boolean, default=False)
    opening_balance = Column(Numeric(20, 4), default=0)  # positive = we owe supplier
    is_active = Column(Boolean, default=True)
    # When true, every supplier invoice for this supplier must capture the external supplier invoice number.
    # Frontend uses this to toggle required validation; backend enforces it in purchase invoice APIs.
    requires_supplier_invoice_number = Column(Boolean, nullable=False, server_default="false", default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="suppliers")

