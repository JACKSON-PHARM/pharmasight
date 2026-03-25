"""
Cashbook engine models (money movement tracking).

Cashbook is a tracking layer:
- It is sourced from other modules (expenses, supplier payments, etc.)
- It does NOT replace those modules as the source of truth.
"""

from sqlalchemy import Column, String, Text, ForeignKey, Numeric, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid

from app.database import Base


class CashbookEntry(Base):
    """Unified money movement entry (inflow/outflow), sourced from other modules."""

    __tablename__ = "cashbook_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)

    # Named to match the cashbook_entries schema for simpler API serialization.
    date = Column(Date, nullable=False)
    type = Column(String(20), nullable=False)  # inflow | outflow
    amount = Column(Numeric(20, 4), nullable=False)
    payment_mode = Column(String(20), nullable=False)  # cash | mpesa | bank

    # Source linking (dedupe on (source_type, source_id))
    source_type = Column(String(50), nullable=False)  # expense | supplier_payment | sale
    source_id = Column(UUID(as_uuid=True), nullable=False)

    reference_number = Column(String(100))
    description = Column(Text)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Optional relationships (not required by cashbook APIs)
    company = relationship("Company")
    branch = relationship("Branch")

