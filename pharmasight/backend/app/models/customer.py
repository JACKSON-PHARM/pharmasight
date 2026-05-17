"""
B2B wholesale customer model
"""
from sqlalchemy import Column, String, Boolean, Integer, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class Customer(Base):
    """Wholesale buyer (pharmacy, hospital, institution)."""
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    pin = Column(String(50))
    contact_person = Column(String(255))
    phone = Column(String(50))
    email = Column(String(255))
    address = Column(Text)
    city = Column(String(100))
    county = Column(String(100))
    customer_type = Column(String(50), nullable=False, default="PHARMACY")
    default_payment_terms_days = Column(Integer)
    credit_limit = Column(Numeric(20, 4))
    allow_over_credit = Column(Boolean, default=False)
    credit_enabled = Column(Boolean, default=True)
    default_sales_type = Column(String(20), nullable=False, default="WHOLESALE")
    opening_balance = Column(Numeric(20, 4), default=0)
    notes = Column(Text)
    portal_enabled = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company", back_populates="customers")
