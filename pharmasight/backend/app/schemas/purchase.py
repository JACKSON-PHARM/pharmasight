"""
Purchase schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal


class BatchDistribution(BaseModel):
    """Batch distribution for a single item"""
    batch_number: str = Field(..., description="Batch number (required)")
    expiry_date: Optional[date] = Field(None, description="Expiry date (required if item requires expiry tracking)")
    quantity: Decimal = Field(..., gt=0, description="Quantity in purchase unit for this batch")
    unit_cost: Decimal = Field(..., ge=0, description="Cost per purchase unit for this batch")


class GRNItemBase(BaseModel):
    """GRN item base schema"""
    item_id: UUID
    unit_name: str = Field(..., description="Purchase unit (box, carton, etc.)")
    quantity: Decimal = Field(..., gt=0, description="Quantity in purchase unit")
    unit_cost: Decimal = Field(..., ge=0, description="Cost per purchase unit")
    batch_number: Optional[str] = None  # Legacy: single batch (deprecated, use batches instead)
    expiry_date: Optional[date] = None  # Legacy: single expiry (deprecated, use batches instead)
    batches: Optional[List[BatchDistribution]] = Field(None, description="Batch distribution (multiple batches per item)")


class GRNItemCreate(GRNItemBase):
    """Create GRN item"""
    pass


class GRNItemResponse(GRNItemBase):
    """GRN item response"""
    id: UUID
    grn_id: UUID
    total_cost: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class GRNBase(BaseModel):
    """GRN base schema"""
    branch_id: UUID
    supplier_id: UUID
    date_received: date
    notes: Optional[str] = None


class GRNCreate(GRNBase):
    """Create GRN request"""
    company_id: UUID
    items: List[GRNItemCreate] = Field(..., min_items=1)
    created_by: UUID


class GRNResponse(GRNBase):
    """GRN response"""
    id: UUID
    company_id: UUID
    grn_no: str
    total_cost: Decimal
    created_by: UUID
    created_at: datetime
    items: List[GRNItemResponse] = []

    class Config:
        from_attributes = True


class SupplierInvoiceItemBase(BaseModel):
    """Supplier invoice item base schema"""
    item_id: UUID
    unit_name: str
    quantity: Decimal = Field(..., gt=0)
    unit_cost_exclusive: Decimal = Field(..., ge=0)
    vat_rate: Decimal = Field(default=16.00, ge=0, le=100)
    # Batch distribution support (same as GRN)
    batches: Optional[List[BatchDistribution]] = Field(None, description="Batch distribution (multiple batches per item)")


class SupplierInvoiceItemCreate(SupplierInvoiceItemBase):
    """Create supplier invoice item"""
    pass


class SupplierInvoiceItemUpdate(BaseModel):
    """Update one supplier invoice line (qty, unit, cost, batch_data)."""
    quantity: Optional[Decimal] = Field(None, gt=0)
    unit_name: Optional[str] = None
    unit_cost_exclusive: Optional[Decimal] = Field(None, ge=0)
    vat_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    batches: Optional[List[BatchDistribution]] = None
    batch_data: Optional[str] = Field(None, description="JSON string of batch distribution (alternative to batches)")


class SupplierInvoiceItemResponse(SupplierInvoiceItemBase):
    """Supplier invoice item response"""
    id: UUID
    purchase_invoice_id: UUID  # Keep column name for backward compatibility
    vat_amount: Decimal
    line_total_exclusive: Decimal
    line_total_inclusive: Decimal
    created_at: datetime
    # Enhanced item details (from Item relationship)
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    item_category: Optional[str] = None
    base_unit: Optional[str] = None
    # Batch data (stored as JSON string in database, parsed for response)
    batch_data: Optional[str] = None

    class Config:
        from_attributes = True


class SupplierInvoiceBase(BaseModel):
    """Supplier invoice base schema"""
    branch_id: UUID
    supplier_id: UUID
    supplier_invoice_number: Optional[str] = Field(None, description="Supplier's invoice number (from supplier - external document)")
    reference: Optional[str] = Field(None, description="Optional reference or comments")
    invoice_date: date
    linked_grn_id: Optional[UUID] = None
    vat_rate: Decimal = Field(default=16.00, ge=0, le=100)
    status: Optional[str] = Field(default="DRAFT", description="DRAFT (saved), BATCHED (stock added)")
    payment_status: Optional[str] = Field(default="UNPAID", description="UNPAID, PARTIAL, PAID")
    amount_paid: Optional[Decimal] = Field(default=0, ge=0, description="Amount paid to supplier")


class SupplierInvoiceCreate(SupplierInvoiceBase):
    """Create supplier invoice request"""
    company_id: UUID
    items: List[SupplierInvoiceItemCreate] = Field(..., min_items=1)
    created_by: UUID


class SupplierInvoiceResponse(SupplierInvoiceBase):
    """Supplier invoice response"""
    id: UUID
    company_id: UUID
    invoice_number: str  # System-generated document number (SPV{BRANCH}-{NUMBER})
    total_exclusive: Decimal
    vat_amount: Decimal
    total_inclusive: Decimal
    balance: Optional[Decimal] = None  # Calculated: total_inclusive - amount_paid
    created_by: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: List[SupplierInvoiceItemResponse] = []
    supplier_name: Optional[str] = None  # From relationship
    branch_name: Optional[str] = None  # From relationship
    created_by_name: Optional[str] = None  # From User relationship

    class Config:
        from_attributes = True

# Backward compatibility aliases
PurchaseInvoiceItemBase = SupplierInvoiceItemBase
PurchaseInvoiceItemCreate = SupplierInvoiceItemCreate
PurchaseInvoiceItemResponse = SupplierInvoiceItemResponse
PurchaseInvoiceBase = SupplierInvoiceBase
PurchaseInvoiceCreate = SupplierInvoiceCreate
PurchaseInvoiceResponse = SupplierInvoiceResponse


class PurchaseOrderItemBase(BaseModel):
    """Purchase order item base schema"""
    item_id: UUID
    unit_name: str = Field(..., description="Purchase unit (box, carton, etc.)")
    quantity: Decimal = Field(..., gt=0, description="Quantity in purchase unit")
    unit_price: Decimal = Field(..., ge=0, description="Expected price per purchase unit")


class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    """Create purchase order item"""
    pass


class PurchaseOrderItemResponse(PurchaseOrderItemBase):
    """Purchase order item response"""
    id: UUID
    purchase_order_id: UUID
    total_price: Decimal
    created_at: datetime
    # Enhanced item details (from Item relationship)
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    item_category: Optional[str] = None
    base_unit: Optional[str] = None
    default_cost: Optional[float] = None
    is_controlled: Optional[bool] = None  # From Item, for document branding rules

    class Config:
        from_attributes = True


class PurchaseOrderBase(BaseModel):
    """Purchase order base schema"""
    branch_id: UUID
    supplier_id: UUID
    order_date: date
    reference: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = Field(default="PENDING", description="PENDING, APPROVED, RECEIVED, CANCELLED")
    is_official: Optional[bool] = Field(default=True, description="If true, apply stamp/signature on official PO")


class PurchaseOrderCreate(PurchaseOrderBase):
    """Create purchase order request"""
    company_id: UUID
    items: List[PurchaseOrderItemCreate] = Field(..., min_items=1)
    created_by: UUID


class PurchaseOrderResponse(PurchaseOrderBase):
    """Purchase order response"""
    id: UUID
    company_id: UUID
    order_number: str
    total_amount: Decimal
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    items: List[PurchaseOrderItemResponse] = []
    supplier_name: Optional[str] = None  # From relationship
    branch_name: Optional[str] = None  # From relationship
    created_by_name: Optional[str] = None  # From User relationship
    approved_by_user_id: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    pdf_path: Optional[str] = None
    approved_by_name: Optional[str] = None
    logo_url: Optional[str] = None  # Short-lived signed URL for print header

    class Config:
        from_attributes = True
