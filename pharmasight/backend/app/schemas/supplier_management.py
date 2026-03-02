"""
Schemas for supplier management: payments, allocations, returns, ledger, aging, metrics.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator


# Payment methods that require a reference (M-Pesa code, transaction ID, cheque number, etc.)
CASHLESS_METHODS = frozenset({"mpesa", "bank", "card", "cheque"})


class SupplierPaymentAllocationCreate(BaseModel):
    """Allocate part of a payment to an invoice."""
    supplier_invoice_id: UUID
    allocated_amount: Decimal = Field(..., gt=0)


class SupplierPaymentCreate(BaseModel):
    """Create a supplier payment, optionally with allocations."""
    branch_id: UUID
    supplier_id: UUID
    payment_date: date
    method: str = Field(..., description="cash, bank, mpesa, card, cheque")
    reference: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    allocations: Optional[List[SupplierPaymentAllocationCreate]] = None

    @model_validator(mode="after")
    def require_reference_for_cashless(self):
        """Reference required for MPesa, Bank, Card, Cheque (cashless transactions)."""
        if self.method and self.method.lower() in CASHLESS_METHODS:
            ref = (self.reference or "").strip()
            if not ref:
                raise ValueError(
                    "Reference is required for MPesa, Bank, Card, and Cheque payments "
                    "(e.g. M-Pesa code, transaction ID, cheque number)"
                )
        return self


class SupplierPaymentAllocationResponse(BaseModel):
    id: UUID
    supplier_payment_id: UUID
    supplier_invoice_id: UUID
    allocated_amount: Decimal
    invoice_number: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SupplierPaymentResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    supplier_id: UUID
    payment_date: date
    method: str
    reference: Optional[str] = None
    amount: Decimal
    is_allocated: bool
    created_by: UUID
    created_at: datetime
    allocations: List[SupplierPaymentAllocationResponse] = []
    supplier_name: Optional[str] = None
    branch_name: Optional[str] = None

    class Config:
        from_attributes = True


# --- Supplier returns ---
class SupplierReturnLineCreate(BaseModel):
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0)
    line_total: Decimal = Field(..., ge=0)


class SupplierReturnCreate(BaseModel):
    branch_id: UUID
    supplier_id: UUID
    linked_invoice_id: Optional[UUID] = None
    return_date: date
    reason: Optional[str] = None
    lines: List[SupplierReturnLineCreate] = Field(..., min_length=1)


class SupplierReturnLineResponse(BaseModel):
    id: UUID
    supplier_return_id: UUID
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class SupplierReturnResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    supplier_id: UUID
    linked_invoice_id: Optional[UUID] = None
    return_date: date
    reason: Optional[str] = None
    total_value: Decimal
    status: str
    created_by: UUID
    created_at: datetime
    lines: List[SupplierReturnLineResponse] = []
    supplier_name: Optional[str] = None
    branch_name: Optional[str] = None

    class Config:
        from_attributes = True


# --- Ledger ---
class SupplierLedgerEntryResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    supplier_id: UUID
    date: date
    entry_type: str
    reference_id: Optional[UUID] = None
    debit: Decimal
    credit: Decimal
    running_balance: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --- Aging ---
class AgingBucket(BaseModel):
    bucket: str  # 0-30, 31-60, 61-90, 90+
    amount: Decimal
    count: int


class SupplierAgingRow(BaseModel):
    supplier_id: UUID
    supplier_name: str
    total_outstanding: Decimal
    bucket_0_30: Decimal
    bucket_31_60: Decimal
    bucket_61_90: Decimal
    bucket_90_plus: Decimal
    overdue_amount: Decimal


class AgingReportResponse(BaseModel):
    as_of_date: date
    branch_id: Optional[UUID] = None
    suppliers: List[SupplierAgingRow]
    totals: AgingBucket


# --- Monthly metrics ---
class SupplierMonthlyMetricsResponse(BaseModel):
    month: str  # YYYY-MM
    company_id: UUID
    branch_id: Optional[UUID] = None
    total_purchases: Decimal
    total_payments: Decimal
    total_returns: Decimal
    net_outstanding: Decimal
    overdue_amount: Decimal
    top_suppliers_by_purchase: List[dict]  # [{ supplier_id, name, total }]
    average_payment_days: Optional[float] = None


# --- Statement ---
class SupplierStatementLine(BaseModel):
    date: date
    description: str
    reference: Optional[str] = None
    debit: Decimal
    credit: Decimal
    balance: Decimal


class SupplierStatementResponse(BaseModel):
    supplier_id: UUID
    supplier_name: str
    branch_id: Optional[UUID] = None
    branch_name: Optional[str] = None
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: List[SupplierStatementLine]
