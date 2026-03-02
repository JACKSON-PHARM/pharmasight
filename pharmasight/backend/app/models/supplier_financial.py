"""
Supplier financial models: payments, allocations, returns, ledger.
Single source of truth for supplier balances: supplier_ledger_entries.
"""
from sqlalchemy import Column, String, Numeric, Date, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class SupplierPayment(Base):
    """Payment made to a supplier. Allocations link to specific invoices."""
    __tablename__ = "supplier_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    payment_date = Column(Date, nullable=False)
    method = Column(String(50), nullable=False)  # cash, bank, mpesa, cheque
    reference = Column(String(255))
    amount = Column(Numeric(20, 4), nullable=False)
    is_allocated = Column(Boolean, default=False)  # True when allocations exist
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    supplier = relationship("Supplier")
    creator = relationship("User", foreign_keys=[created_by])
    allocations = relationship(
        "SupplierPaymentAllocation",
        back_populates="supplier_payment",
        cascade="all, delete-orphan",
    )


class SupplierPaymentAllocation(Base):
    """Allocation of a supplier payment to a specific invoice."""
    __tablename__ = "supplier_payment_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_payment_id = Column(UUID(as_uuid=True), ForeignKey("supplier_payments.id", ondelete="CASCADE"), nullable=False)
    supplier_invoice_id = Column(UUID(as_uuid=True), ForeignKey("purchase_invoices.id", ondelete="CASCADE"), nullable=False)
    allocated_amount = Column(Numeric(20, 4), nullable=False)

    supplier_payment = relationship("SupplierPayment", back_populates="allocations")
    supplier_invoice = relationship("SupplierInvoice", foreign_keys=[supplier_invoice_id])


class SupplierReturn(Base):
    """Goods returned to supplier. When approved, reduces stock and creates ledger credit."""
    __tablename__ = "supplier_returns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    linked_invoice_id = Column(UUID(as_uuid=True), ForeignKey("purchase_invoices.id", ondelete="SET NULL"))
    return_date = Column(Date, nullable=False)
    reason = Column(Text)
    total_value = Column(Numeric(20, 4), nullable=False, default=0)
    status = Column(String(50), nullable=False, default="pending")  # pending, approved, rejected, credited
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    supplier = relationship("Supplier")
    linked_invoice = relationship("SupplierInvoice", foreign_keys=[linked_invoice_id])
    creator = relationship("User", foreign_keys=[created_by])
    lines = relationship(
        "SupplierReturnLine",
        back_populates="supplier_return",
        cascade="all, delete-orphan",
    )


class SupplierReturnLine(Base):
    """Line item for a supplier return; used for stock reduction."""
    __tablename__ = "supplier_return_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_return_id = Column(UUID(as_uuid=True), ForeignKey("supplier_returns.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(String(200))
    expiry_date = Column(Date)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_cost = Column(Numeric(20, 4), nullable=False)
    line_total = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    supplier_return = relationship("SupplierReturn", back_populates="lines")
    item = relationship("Item")


class SupplierLedgerEntry(Base):
    """Single source of truth for supplier financial tracking. Debit = we owe, Credit = we paid/credited."""
    __tablename__ = "supplier_ledger_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    entry_type = Column(String(50), nullable=False)  # invoice, payment, return, adjustment, opening_balance
    reference_id = Column(UUID(as_uuid=True))
    debit = Column(Numeric(20, 4), nullable=False, default=0)
    credit = Column(Numeric(20, 4), nullable=False, default=0)
    running_balance = Column(Numeric(20, 4))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    supplier = relationship("Supplier")
