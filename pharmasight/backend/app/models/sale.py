"""
Sales models (KRA Compliant)
"""
from sqlalchemy import Column, String, Numeric, Date, ForeignKey, Text, Boolean, UniqueConstraint
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
    invoice_no = Column(String(100), nullable=False)  # SD-{BRANCH_CODE}-{NUMBER}, e.g. SD-MAIN-000001
    invoice_date = Column(Date, nullable=False)
    customer_name = Column(String(255))
    customer_pin = Column(String(50))
    customer_phone = Column(String(50), nullable=True)  # Required for credit payment mode (nullable for backward compatibility)
    payment_mode = Column(String(50), nullable=False)  # cash, mpesa, credit, bank (legacy - kept for backward compatibility)
    payment_status = Column(String(50), default="PAID")  # PAID, PARTIAL, CREDIT
    sales_type = Column(String(20), default="RETAIL")  # RETAIL (customers) or WHOLESALE (pharmacies)
    total_exclusive = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    discount_amount = Column(Numeric(20, 4), default=0)
    total_inclusive = Column(Numeric(20, 4), default=0)
    # Document status: DRAFT (editable), BATCHED (committed, ready for payment), PAID (payment collected), CANCELLED
    status = Column(String(20), default="DRAFT", nullable=True)  # DRAFT, BATCHED, PAID, CANCELLED (nullable for backward compatibility)
    batched = Column(Boolean, default=False, nullable=True)
    batched_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    batched_at = Column(TIMESTAMP(timezone=True), nullable=True)
    cashier_approved = Column(Boolean, default=False, nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    creator = relationship("User", primaryjoin="SalesInvoice.created_by==User.id", foreign_keys="[SalesInvoice.created_by]")
    items = relationship("SalesInvoiceItem", back_populates="sales_invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="sales_invoice", cascade="all, delete-orphan")
    invoice_payments = relationship("InvoicePayment", back_populates="sales_invoice", cascade="all, delete-orphan")
    credit_notes = relationship("CreditNote", back_populates="original_invoice")

    __table_args__ = (
        {"comment": "KRA-compliant sales document. Immutable after creation."},
    )


class SalesInvoiceItem(Base):
    """Sales Invoice line items. One line per item per invoice (unique invoice_id + item_id)."""
    __tablename__ = "sales_invoice_items"
    __table_args__ = (
        UniqueConstraint("sales_invoice_id", "item_id", name="uq_sales_invoice_items_invoice_item"),
    )

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
    # Cached item details for display (snapshot at time of sale)
    item_name = Column(String(255), nullable=True)
    item_code = Column(String(100), nullable=True)
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


class Quotation(Base):
    """Sales Quotation (Non-stock-affecting document)"""
    __tablename__ = "quotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    quotation_no = Column(String(100), nullable=False)  # Sequential
    quotation_date = Column(Date, nullable=False)
    customer_name = Column(String(255))
    customer_pin = Column(String(50))
    reference = Column(String(255))  # Optional reference number
    notes = Column(Text)  # Additional notes
    status = Column(String(50), default="draft")  # draft, sent, accepted, converted, cancelled
    total_exclusive = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    discount_amount = Column(Numeric(20, 4), default=0)
    total_inclusive = Column(Numeric(20, 4), default=0)
    converted_to_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id"), nullable=True)  # If converted
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    valid_until = Column(Date, nullable=True)  # Quotation expiry date

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    creator = relationship("User", primaryjoin="Quotation.created_by==User.id", foreign_keys="[Quotation.created_by]")
    items = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan")
    converted_invoice = relationship("SalesInvoice", foreign_keys=[converted_to_invoice_id])

    __table_args__ = (
        {"comment": "Sales quotation - does not affect inventory. Can be converted to invoice."},
    )


class QuotationItem(Base):
    """Quotation line items"""
    __tablename__ = "quotation_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quotation_id = Column(UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)  # In sale unit
    unit_price_exclusive = Column(Numeric(20, 4), nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0)
    discount_amount = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    line_total_exclusive = Column(Numeric(20, 4), nullable=False)
    line_total_inclusive = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    quotation = relationship("Quotation", back_populates="items")
    item = relationship("Item")


class InvoicePayment(Base):
    """Split Payment Tracking for Sales Invoices"""
    __tablename__ = "invoice_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False)
    payment_mode = Column(String(20), nullable=False)  # 'cash', 'mpesa', 'card', 'credit', 'insurance'
    amount = Column(Numeric(15, 4), nullable=False, default=0)
    payment_reference = Column(String(100))  # M-Pesa code, transaction ID, etc.
    paid_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    paid_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    sales_invoice = relationship("SalesInvoice", back_populates="invoice_payments")
    user = relationship("User", foreign_keys=[paid_by])

    __table_args__ = (
        {"comment": "Split payment tracking for sales invoices. Supports multiple payment modes per invoice."},
    )
