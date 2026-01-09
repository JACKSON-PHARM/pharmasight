"""
Sales models (KRA Compliant)
"""
from sqlalchemy import Column, String, Numeric, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class SalesInvoice(Base):
    """Sales Invoice (KRA Document)"""
    __tablename__ = "sales_invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    invoice_no = Column(String(100), nullable=False)  # Sequential, KRA compliant
    invoice_date = Column(Date, nullable=False)
    customer_name = Column(String(255))
    customer_pin = Column(String(50))
    payment_mode = Column(String(50), nullable=False)  # cash, mpesa, credit, bank
    payment_status = Column(String(50), default="PAID")  # PAID, PARTIAL, CREDIT
    total_exclusive = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    discount_amount = Column(Numeric(20, 4), default=0)
    total_inclusive = Column(Numeric(20, 4), default=0)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    items = relationship("SalesInvoiceItem", back_populates="sales_invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="sales_invoice", cascade="all, delete-orphan")
    credit_notes = relationship("CreditNote", back_populates="original_invoice")

    __table_args__ = (
        {"comment": "KRA-compliant sales document. Immutable after creation."},
    )


class SalesInvoiceItem(Base):
    """Sales Invoice line items"""
    __tablename__ = "sales_invoice_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sales_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_ledger.id"))  # Reference to ledger entry
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)  # In sale unit
    unit_price_exclusive = Column(Numeric(20, 4), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    discount_amount = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    line_total_exclusive = Column(Numeric(20, 4), nullable=False)
    line_total_inclusive = Column(Numeric(20, 4), nullable=False)
    unit_cost_used = Column(Numeric(20, 4))  # For margin calculation
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    sales_invoice = relationship("SalesInvoice", back_populates="items")
    item = relationship("Item")
    batch_ledger_entry = relationship("InventoryLedger", foreign_keys=[batch_id])


class Payment(Base):
    """Payment (Settlement of Invoices)"""
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    sales_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False)
    payment_no = Column(String(100), nullable=False)
    payment_date = Column(Date, nullable=False)
    amount = Column(Numeric(20, 4), nullable=False)
    payment_mode = Column(String(50), nullable=False)  # cash, mpesa, bank, cheque
    reference_number = Column(String(100))
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    sales_invoice = relationship("SalesInvoice", back_populates="payments")


class CreditNote(Base):
    """Credit Note (KRA Document for Returns)"""
    __tablename__ = "credit_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    credit_note_no = Column(String(100), nullable=False)
    original_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id"), nullable=False)
    credit_note_date = Column(Date, nullable=False)
    reason = Column(Text)
    total_exclusive = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    total_inclusive = Column(Numeric(20, 4), default=0)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    original_invoice = relationship("SalesInvoice", back_populates="credit_notes")
    items = relationship("CreditNoteItem", back_populates="credit_note", cascade="all, delete-orphan")

    __table_args__ = (
        {"comment": "KRA-compliant return document. Must reference original invoice."},
    )


class CreditNoteItem(Base):
    """Credit Note line items"""
    __tablename__ = "credit_note_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_note_id = Column(UUID(as_uuid=True), ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    original_sale_item_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoice_items.id"))
    batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_ledger.id"))
    unit_name = Column(String(50), nullable=False)
    quantity_returned = Column(Numeric(20, 4), nullable=False)
    unit_price_exclusive = Column(Numeric(20, 4), nullable=False)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    line_total_exclusive = Column(Numeric(20, 4), nullable=False)
    line_total_inclusive = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    credit_note = relationship("CreditNote", back_populates="items")
    item = relationship("Item")
    batch_ledger_entry = relationship("InventoryLedger", foreign_keys=[batch_id])

