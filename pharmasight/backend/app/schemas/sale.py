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


class BatchSalesInvoiceRequest(BaseModel):
    """Optional body for batch endpoint: sync invoice lines from frontend before batching."""
    items: Optional[List[SalesInvoiceItemCreate]] = Field(
        default=None,
        description="Current line items from UI (quantity, unit_name, unit_price_exclusive, etc.). If provided, draft lines are updated to match before stock deduction."
    )


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
    unit_cost_base: Optional[Decimal] = None  # Cost per base (wholesale) unit for accurate unit-aware calculations
    item_name: Optional[str] = None
    item_code: Optional[str] = None
    unit_display_short: Optional[str] = None  # P/W/S for display/print only
    batch_number: Optional[str] = None  # From ledger when batched, for receipt print
    expiry_date: Optional[str] = None  # ISO date from ledger when batched, for receipt print
    created_at: datetime

    class Config:
        from_attributes = True


class SalesInvoiceBase(BaseModel):
    """Sales invoice base schema"""
    branch_id: UUID
    invoice_date: date
    customer_name: Optional[str] = None
    customer_pin: Optional[str] = None
    customer_phone: Optional[str] = None  # Required if payment_mode is 'credit'
    payment_mode: str = Field(default="cash", description="cash, mpesa, credit, bank (legacy - use invoice_payments for split payments)")
    payment_status: str = Field(default="UNPAID", description="UNPAID, PARTIAL, PAID")
    sales_type: str = Field(default="RETAIL", description="RETAIL (customers) or WHOLESALE (pharmacies)")
    status: Optional[str] = Field(default="DRAFT", description="DRAFT, BATCHED, PAID, CANCELLED")
    discount_amount: Decimal = Field(default=0, ge=0)


class SalesInvoiceCreate(SalesInvoiceBase):
    """Create sales invoice request. Use for first item: creates DRAFT with that line. No duplicate item_id allowed."""
    company_id: UUID
    items: List[SalesInvoiceItemCreate] = Field(..., min_length=1)
    created_by: UUID


class SalesInvoiceUpdate(BaseModel):
    """Update sales invoice (limited - KRA compliance)"""
    payment_status: Optional[str] = None
    customer_name: Optional[str] = None
    customer_pin: Optional[str] = None
    customer_phone: Optional[str] = None
    payment_mode: Optional[str] = None


class SalesInvoiceResponse(SalesInvoiceBase):
    """Sales invoice response (includes company/branch/user for print letterhead)"""
    id: UUID
    company_id: UUID
    invoice_no: str
    total_exclusive: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total_inclusive: Decimal
    sales_type: Optional[str] = "RETAIL"
    status: Optional[str] = "DRAFT"  # Optional for backward compatibility
    batched: Optional[bool] = False
    batched_by: Optional[UUID] = None
    batched_at: Optional[datetime] = None
    cashier_approved: Optional[bool] = False
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    items: List[SalesInvoiceItemResponse] = []
    # Print letterhead (populated by API when fetching single invoice)
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    branch_name: Optional[str] = None
    branch_address: Optional[str] = None
    branch_phone: Optional[str] = None
    created_by_username: Optional[str] = None
    # Short-lived signed URL for company logo (for print/HTML); only when logo in tenant-assets
    logo_url: Optional[str] = None

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


# =====================================================
# QUOTATION SCHEMAS
# =====================================================

class QuotationItemBase(BaseModel):
    """Quotation item base schema"""
    item_id: UUID
    unit_name: str = Field(..., description="Sale unit (tablet, box, etc.)")
    quantity: Decimal = Field(..., gt=0, description="Quantity in sale unit")
    unit_price_exclusive: Optional[Decimal] = Field(None, ge=0, description="Price per unit (exclusive of VAT)")
    discount_percent: Decimal = Field(default=0, ge=0, le=100)


class QuotationItemCreate(QuotationItemBase):
    """Create quotation item"""
    pass


class QuotationItemResponse(QuotationItemBase):
    """Quotation item response (includes item_name, item_code, margin like sales invoice)"""
    id: UUID
    quotation_id: UUID
    vat_rate: Decimal
    vat_amount: Decimal
    discount_amount: Decimal
    line_total_exclusive: Decimal
    line_total_inclusive: Decimal
    item_name: Optional[str] = None
    item_code: Optional[str] = None
    unit_cost_used: Optional[Decimal] = None
    unit_cost_base: Optional[Decimal] = None  # Cost per base (wholesale) unit for accurate unit-aware calculations
    margin_percent: Optional[Decimal] = None
    unit_display_short: Optional[str] = None  # P/W/S for display/print only
    created_at: datetime

    class Config:
        from_attributes = True


class QuotationBase(BaseModel):
    """Quotation base schema"""
    branch_id: UUID
    quotation_date: date
    customer_name: Optional[str] = None
    customer_pin: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    status: str = Field(default="draft", description="draft, sent, accepted, converted, cancelled")
    discount_amount: Decimal = Field(default=0, ge=0)
    valid_until: Optional[date] = None


class QuotationCreate(QuotationBase):
    """Create quotation request"""
    company_id: UUID
    items: List[QuotationItemCreate] = Field(..., min_items=1)
    created_by: UUID


class QuotationUpdate(BaseModel):
    """Update quotation (before conversion)"""
    customer_name: Optional[str] = None
    customer_pin: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    discount_amount: Optional[Decimal] = None
    valid_until: Optional[date] = None
    items: Optional[List[QuotationItemCreate]] = None


class QuotationResponse(QuotationBase):
    """Quotation response (includes company/branch/user for print header)"""
    id: UUID
    company_id: UUID
    quotation_no: str
    total_exclusive: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    total_inclusive: Decimal
    converted_to_invoice_id: Optional[UUID] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    items: List[QuotationItemResponse] = []
    # Print header (populated by API when fetching single quotation)
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    branch_name: Optional[str] = None
    branch_address: Optional[str] = None
    branch_phone: Optional[str] = None
    created_by_username: Optional[str] = None
    logo_url: Optional[str] = None  # Short-lived signed URL for print

    class Config:
        from_attributes = True


class QuotationConvertRequest(BaseModel):
    """Convert quotation to invoice request"""
    invoice_date: Optional[date] = None  # If not provided, use current date
    payment_mode: str = Field(default="cash", description="cash, mpesa, credit, bank")
    payment_status: str = Field(default="UNPAID", description="UNPAID, PARTIAL, PAID")
    customer_name: Optional[str] = None  # Override if needed
    customer_pin: Optional[str] = None  # Override if needed
    reference: Optional[str] = None  # Override if needed
    notes: Optional[str] = None  # Override if needed


# =====================================================
# INVOICE PAYMENT SCHEMAS (SPLIT PAYMENTS)
# =====================================================

class InvoicePaymentBase(BaseModel):
    """Invoice payment base schema"""
    payment_mode: str = Field(..., description="cash, mpesa, card, credit, insurance")
    amount: Decimal = Field(..., gt=0)
    payment_reference: Optional[str] = None


class InvoicePaymentCreate(InvoicePaymentBase):
    """Create invoice payment request"""
    invoice_id: UUID
    paid_by: UUID


class InvoicePaymentResponse(InvoicePaymentBase):
    """Invoice payment response"""
    id: UUID
    invoice_id: UUID
    paid_by: Optional[UUID] = None
    paid_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True
