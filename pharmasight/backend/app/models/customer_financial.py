"""
Customer financial models: payments, allocations, ledger (AR).
Debit = customer owes us. Credit = customer paid or credited.
"""
from sqlalchemy import Column, String, Numeric, Date, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class CustomerPayment(Base):
    __tablename__ = "customer_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    payment_date = Column(Date, nullable=False)
    method = Column(String(50), nullable=False)
    reference = Column(String(255))
    amount = Column(Numeric(20, 4), nullable=False)
    is_allocated = Column(Boolean, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    customer = relationship("Customer")
    creator = relationship("User", foreign_keys=[created_by])
    allocations = relationship(
        "CustomerPaymentAllocation",
        back_populates="customer_payment",
        cascade="all, delete-orphan",
    )


class CustomerPaymentAllocation(Base):
    __tablename__ = "customer_payment_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_payment_id = Column(
        UUID(as_uuid=True), ForeignKey("customer_payments.id", ondelete="CASCADE"), nullable=False
    )
    sales_invoice_id = Column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False
    )
    allocated_amount = Column(Numeric(20, 4), nullable=False)

    customer_payment = relationship("CustomerPayment", back_populates="allocations")
    sales_invoice = relationship("SalesInvoice", foreign_keys=[sales_invoice_id])


class CustomerLedgerEntry(Base):
    __tablename__ = "customer_ledger_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    entry_type = Column(String(50), nullable=False)
    reference_id = Column(UUID(as_uuid=True))
    debit = Column(Numeric(20, 4), nullable=False, default=0)
    credit = Column(Numeric(20, 4), nullable=False, default=0)
    running_balance = Column(Numeric(20, 4))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    customer = relationship("Customer")


class CustomerActivity(Base):
    __tablename__ = "customer_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    activity_type = Column(String(50), nullable=False)
    subject = Column(String(255), nullable=False)
    notes = Column(Text)
    due_date = Column(Date)
    status = Column(String(50), nullable=False, default="open")
    assigned_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    completed_at = Column(TIMESTAMP(timezone=True))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    customer = relationship("Customer")
    assignee = relationship("User", foreign_keys=[assigned_user_id])
    creator = relationship("User", foreign_keys=[created_by])


class CustomerUser(Base):
    """Future B2B portal identity (Phase 5 foundation)."""
    __tablename__ = "customer_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    auth_user_id = Column(UUID(as_uuid=True))
    is_active = Column(Boolean, default=True)
    invited_at = Column(TIMESTAMP(timezone=True))
    last_login_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    customer = relationship("Customer")
