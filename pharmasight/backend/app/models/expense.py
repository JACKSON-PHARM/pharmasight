"""
Expense engine models (OPEX only).

DB tables originate from 001_initial.sql:
- expense_categories
- expenses

This module adds ORM models and (in a later migration) optional columns used by
approval workflow (status, approved_at/by) and category activation (is_active).
"""
import uuid
from sqlalchemy import Column, String, Text, ForeignKey, Numeric, Date, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    # Added by migration: defaults true. If column absent, DB will error; keep migration in repo.
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("expense_categories.id"), nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(20, 4), nullable=False)
    expense_date = Column(Date, nullable=False)
    payment_mode = Column(String(50), nullable=False)  # cash, mpesa, bank
    reference_number = Column(String(100))
    attachment_url = Column(Text)
    status = Column(String(50), nullable=False, default="approved", server_default="approved")  # pending, approved
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    category = relationship("ExpenseCategory")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])

