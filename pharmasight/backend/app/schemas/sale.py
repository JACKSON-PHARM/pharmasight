"""
Sales schemas (KRA Compliant)
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal


class SalesInvoiceItemBase(BaseModel):
    """Sales invoice item base schema"""
    item_id: UUID
    unit_name: str = Field(..., description="Sale unit (tablet, box, etc.)")
    quantity: Decimal = Field(..., gt=0, description="Quantity in sale unit")
    unit_price_exclusive: Optional[Decimal] = Field(None, ge=0, description="Price per unit (exclusive of VAT)")
    discount_percent: Decimal = Field(default=0, ge=0, le=100)
    discount_amount: Decimal = Field(default=0, ge=0)


class SalesInvoiceItemCreate(SalesInvoiceItemBase):
    """Create sales invoice item"""
    pass


class SalesInvoiceItemResponse(SalesInvoiceItemBase):
    """Sales invoice item response"""
    id: UUID
    sales_invoice_id: UUID
    batch_id: Optional[UUID]
    vat_rate: Decimal
    vat_amount: Decimal
    line_total_exclusive: Decimal
    line_total_inclusive: Decimal
    unit_cost_used: Optional[Decimal]
    created_at: datetime

    class Config:
        from_attributes = True


class SalesInvoiceBase(BaseModel):
    """Sales invoice base schema"""
    branch_id: UUID
    invoice_date: date
    customer_name: Optional[str] = None
    customer_pin: Optional[str] = None
    payment_mode: str = Field(..., description="cash, mpesa, credit, bank")
    payment_status: str = Field(default="PAID", description="PAID, PARTIAL, CREDIT")
    discount_amount: Decimal = Field(default=0, ge=0)


class SalesInvoiceCreate(SalesInvoiceBase):
    """Create sales invoice request"""
    company_id: UUID
    items: List[SalesInvoiceItemCreate] = Field(..., min_items=1)
    created_by: UUID


class SalesInvoiceUpdate(BaseModel):
    """Update sales invoice (limited - KRA compliance)"""
    payment_status: Optional[str] = None
    customer_name: Optional[str] = None
    customer_pin: Optional[str] = None


class SalesInvoiceResponse(SalesInvoiceBase):
    """Sales invoice response"""
    id: UUID
    company_id: UUID
    invoice_no: str
    total_exclusive: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total_inclusive: Decimal
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    items: List[SalesInvoiceItemResponse] = []

    class Config:
        from_attributes = True


class PaymentBase(BaseModel):
    """Payment base schema"""
    sales_invoice_id: UUID
    payment_date: date
    amount: Decimal = Field(..., gt=0)
    payment_mode: str = Field(..., description="cash, mpesa, bank, cheque")
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class PaymentCreate(PaymentBase):
    """Create payment request"""
    company_id: UUID
    branch_id: UUID
    created_by: UUID


class PaymentResponse(PaymentBase):
    """Payment response"""
    id: UUID
    company_id: UUID
    branch_id: UUID
    payment_no: str
    created_by: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class CreditNoteItemBase(BaseModel):
    """Credit note item base schema"""
    item_id: UUID
    original_sale_item_id: Optional[UUID] = None
    unit_name: str
    quantity_returned: Decimal = Field(..., gt=0)
    unit_price_exclusive: Decimal = Field(..., ge=0)


class CreditNoteItemCreate(CreditNoteItemBase):
    """Create credit note item"""
    pass


class CreditNoteItemResponse(CreditNoteItemBase):
    """Credit note item response"""
    id: UUID
    credit_note_id: UUID
    batch_id: Optional[UUID]
    vat_rate: Decimal
    vat_amount: Decimal
    line_total_exclusive: Decimal
    line_total_inclusive: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class CreditNoteBase(BaseModel):
    """Credit note base schema"""
    original_invoice_id: UUID
    credit_note_date: date
    reason: Optional[str] = None


class CreditNoteCreate(CreditNoteBase):
    """Create credit note request"""
    company_id: UUID
    branch_id: UUID
    items: List[CreditNoteItemCreate] = Field(..., min_items=1)
    created_by: UUID


class CreditNoteResponse(CreditNoteBase):
    """Credit note response"""
    id: UUID
    company_id: UUID
    branch_id: UUID
    credit_note_no: str
    total_exclusive: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total_inclusive: Decimal
    created_by: UUID
    created_at: datetime
    items: List[CreditNoteItemResponse] = []

    class Config:
        from_attributes = True

