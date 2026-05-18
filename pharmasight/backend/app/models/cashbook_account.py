"""
Treasury routing dimension — NOT accounting accounts.

cashbook_accounts route operational money movement to tills, M-Pesa, bank, etc.
No balances, debit/credit, or GL semantics are stored here.
"""
from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid

from app.database import Base


class CashbookAccount(Base):
    __tablename__ = "cashbook_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True)
    account_code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    routing_type = Column(String(30), nullable=False)
    payment_mode = Column(String(20), nullable=True)
    classification = Column(String(30), nullable=False, default="branch_finance")
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
