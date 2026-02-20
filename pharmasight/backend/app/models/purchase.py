"""
Purchase models (GRN and Purchase Invoices)
"""
from sqlalchemy import Column, String, Numeric, Date, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class GRN(Base):
    """Goods Received Note"""
    __tablename__ = "grns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    grn_no = Column(String(100), nullable=False)
    date_received = Column(Date, nullable=False)
    total_cost = Column(Numeric(20, 4), default=0)
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    supplier = relationship("Supplier")
    items = relationship("GRNItem", back_populates="grn", cascade="all, delete-orphan")

    __table_args__ = (
        {"comment": "GRN updates stock and cost. VAT is handled separately in Supplier Invoice."},
    )


class GRNItem(Base):
    """GRN line items"""
    __tablename__ = "grn_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grn_id = Column(UUID(as_uuid=True), ForeignKey("grns.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    unit_name = Column(String(50), nullable=False)  # Purchase unit (box, carton, etc.)
    quantity = Column(Numeric(20, 4), nullable=False)  # In purchase unit
    unit_cost = Column(Numeric(20, 4), nullable=False)  # Cost per purchase unit
    batch_number = Column(String(200))
    expiry_date = Column(Date)
    total_cost = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    grn = relationship("GRN", back_populates="items")
    item = relationship("Item")


class SupplierInvoice(Base):
    """Supplier Invoice (Receiving Document - Adds Stock)"""
    __tablename__ = "purchase_invoices"  # Keep table name for backward compatibility

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    invoice_number = Column(String(100), nullable=False)  # Supplier's invoice number
    pin_number = Column(String(100))  # Deprecated - kept for backward compatibility
    reference = Column(String(255))  # Optional reference or comments
    invoice_date = Column(Date, nullable=False)
    linked_grn_id = Column(UUID(as_uuid=True), ForeignKey("grns.id"))
    total_exclusive = Column(Numeric(20, 4), default=0)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    total_inclusive = Column(Numeric(20, 4), default=0)
    # Document status: DRAFT (saved but not batched), BATCHED (stock added)
    status = Column(String(50), default="DRAFT")  # DRAFT, BATCHED
    # Payment tracking
    payment_status = Column(String(50), default="UNPAID")  # UNPAID, PARTIAL, PAID
    amount_paid = Column(Numeric(20, 4), default=0)
    balance = Column(Numeric(20, 4))  # Calculated: total_inclusive - amount_paid
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    supplier = relationship("Supplier")
    linked_grn = relationship("GRN")
    items = relationship("SupplierInvoiceItem", back_populates="supplier_invoice", cascade="all, delete-orphan")

    __table_args__ = (
        {"comment": "Supplier Invoice - Receiving document that ADDS STOCK. Can only be reversed by supplier credit note."},
    )


class SupplierInvoiceItem(Base):
    """Supplier Invoice line items"""
    __tablename__ = "purchase_invoice_items"  # Keep table name for backward compatibility

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_invoice_id = Column(UUID(as_uuid=True), ForeignKey("purchase_invoices.id", ondelete="CASCADE"), nullable=False)  # Keep column name for backward compatibility
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_cost_exclusive = Column(Numeric(20, 4), nullable=False)
    vat_rate = Column(Numeric(5, 2), default=16.00)
    vat_amount = Column(Numeric(20, 4), default=0)
    line_total_exclusive = Column(Numeric(20, 4), nullable=False)
    line_total_inclusive = Column(Numeric(20, 4), nullable=False)
    batch_data = Column(Text)  # JSON string storing batch distribution for this item
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    supplier_invoice = relationship("SupplierInvoice", back_populates="items", foreign_keys=[purchase_invoice_id])
    item = relationship("Item")


class PurchaseOrder(Base):
    """Purchase Order (Pre-order document before GRN)"""
    __tablename__ = "purchase_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    order_number = Column(String(100), nullable=False)  # PO{BRANCH_CODE}-000001
    order_date = Column(Date, nullable=False)
    reference = Column(String(255))  # User reference/notes
    notes = Column(Text)
    total_amount = Column(Numeric(20, 4), default=0)
    status = Column(String(50), default="PENDING")  # PENDING, APPROVED, RECEIVED, CANCELLED
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    # Approval workflow: set when status becomes APPROVED; PDF generated and stored
    approved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    is_official = Column(Boolean, default=True)  # Apply stamp/signature on official PO
    pdf_path = Column(Text, nullable=True)  # tenant-assets/{tenant_id}/documents/purchase_orders/{po_id}.pdf

    # Relationships
    company = relationship("Company")
    approved_by_user = relationship("User", foreign_keys=[approved_by_user_id])
    branch = relationship("Branch")
    supplier = relationship("Supplier")
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")

    __table_args__ = (
        {"comment": "Purchase Orders are created before receiving goods. Can be converted to GRN."},
    )


class PurchaseOrderItem(Base):
    """Purchase Order line items"""
    __tablename__ = "purchase_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id"), nullable=False)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_price = Column(Numeric(20, 4), nullable=False)  # Expected price
    total_price = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items")
    item = relationship("Item")
