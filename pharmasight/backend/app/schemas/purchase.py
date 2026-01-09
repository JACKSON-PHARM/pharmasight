"""
Purchase schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal


class GRNItemBase(BaseModel):
    """GRN item base schema"""
    item_id: UUID
    unit_name: str = Field(..., description="Purchase unit (box, carton, etc.)")
    quantity: Decimal = Field(..., gt=0, description="Quantity in purchase unit")
    unit_cost: Decimal = Field(..., ge=0, description="Cost per purchase unit")
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None


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


class PurchaseInvoiceItemBase(BaseModel):
    """Purchase invoice item base schema"""
    item_id: UUID
    unit_name: str
    quantity: Decimal = Field(..., gt=0)
    unit_cost_exclusive: Decimal = Field(..., ge=0)
    vat_rate: Decimal = Field(default=16.00, ge=0, le=100)


class PurchaseInvoiceItemCreate(PurchaseInvoiceItemBase):
    """Create purchase invoice item"""
    pass


class PurchaseInvoiceItemResponse(PurchaseInvoiceItemBase):
    """Purchase invoice item response"""
    id: UUID
    purchase_invoice_id: UUID
    vat_amount: Decimal
    line_total_exclusive: Decimal
    line_total_inclusive: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class PurchaseInvoiceBase(BaseModel):
    """Purchase invoice base schema"""
    branch_id: UUID
    supplier_id: UUID
    invoice_number: str = Field(..., description="Supplier's invoice number")
    pin_number: Optional[str] = None
    invoice_date: date
    linked_grn_id: Optional[UUID] = None
    vat_rate: Decimal = Field(default=16.00, ge=0, le=100)


class PurchaseInvoiceCreate(PurchaseInvoiceBase):
    """Create purchase invoice request"""
    company_id: UUID
    items: List[PurchaseInvoiceItemCreate] = Field(..., min_items=1)
    created_by: UUID


class PurchaseInvoiceResponse(PurchaseInvoiceBase):
    """Purchase invoice response"""
    id: UUID
    company_id: UUID
    total_exclusive: Decimal
    vat_amount: Decimal
    total_inclusive: Decimal
    created_by: UUID
    created_at: datetime
    items: List[PurchaseInvoiceItemResponse] = []

    class Config:
        from_attributes = True

