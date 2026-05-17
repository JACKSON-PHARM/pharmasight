"""Schemas for customer AR and CRM."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

CASHLESS_METHODS = frozenset({"mpesa", "bank", "card", "cheque"})


class CustomerPaymentAllocationCreate(BaseModel):
    sales_invoice_id: UUID
    allocated_amount: Decimal = Field(..., gt=0)


class CustomerPaymentCreate(BaseModel):
    branch_id: UUID
    customer_id: UUID
    payment_date: date
    method: str = Field(..., description="cash, bank, mpesa, card, cheque")
    reference: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    allocations: Optional[List[CustomerPaymentAllocationCreate]] = None

    @model_validator(mode="after")
    def require_reference_for_cashless(self):
        if self.method and self.method.lower() in CASHLESS_METHODS:
            ref = (self.reference or "").strip()
            if not ref:
                raise ValueError(
                    "Reference is required for MPesa, Bank, Card, and Cheque payments"
                )
        return self


class CustomerPaymentAllocationResponse(BaseModel):
    id: UUID
    customer_payment_id: UUID
    sales_invoice_id: UUID
    allocated_amount: Decimal
    invoice_no: Optional[str] = None

    class Config:
        from_attributes = True


class CustomerPaymentResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    payment_date: date
    method: str
    reference: Optional[str] = None
    amount: Decimal
    is_allocated: bool
    created_by: UUID
    created_at: datetime
    allocations: List[CustomerPaymentAllocationResponse] = []
    customer_name: Optional[str] = None
    branch_name: Optional[str] = None

    class Config:
        from_attributes = True


class CustomerLedgerEntryResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    date: date
    entry_type: str
    reference_id: Optional[UUID] = None
    debit: Decimal
    credit: Decimal
    running_balance: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerAgingRow(BaseModel):
    customer_id: UUID
    customer_name: str
    current: Decimal = Decimal("0")
    days_1_30: Decimal = Decimal("0")
    days_31_60: Decimal = Decimal("0")
    days_61_90: Decimal = Decimal("0")
    days_over_90: Decimal = Decimal("0")
    total_outstanding: Decimal = Decimal("0")


class AgingBucket(BaseModel):
    label: str
    amount: Decimal


class CustomerAgingReportResponse(BaseModel):
    as_of_date: date
    branch_id: Optional[UUID] = None
    rows: List[CustomerAgingRow] = []
    buckets: List[AgingBucket] = []


class CustomerStatementLine(BaseModel):
    date: date
    entry_type: str
    reference: Optional[str] = None
    debit: Decimal
    credit: Decimal
    balance: Decimal


class CustomerStatementResponse(BaseModel):
    customer_id: UUID
    customer_name: str
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: List[CustomerStatementLine] = []


class CustomerActivityCreate(BaseModel):
    customer_id: UUID
    activity_type: str = Field(..., description="call, visit, email, follow_up, other")
    subject: str
    notes: Optional[str] = None
    due_date: Optional[date] = None
    assigned_user_id: Optional[UUID] = None


class CustomerActivityUpdate(BaseModel):
    activity_type: Optional[str] = None
    subject: Optional[str] = None
    notes: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    assigned_user_id: Optional[UUID] = None


class CustomerActivityResponse(BaseModel):
    id: UUID
    company_id: UUID
    customer_id: UUID
    activity_type: str
    subject: str
    notes: Optional[str] = None
    due_date: Optional[date] = None
    status: str
    assigned_user_id: Optional[UUID] = None
    completed_at: Optional[datetime] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    customer_name: Optional[str] = None

    class Config:
        from_attributes = True


class CustomerAnalyticsResponse(BaseModel):
    customer_id: UUID
    customer_name: str
    sales_30d: Decimal = Decimal("0")
    sales_90d: Decimal = Decimal("0")
    sales_365d: Decimal = Decimal("0")
    outstanding_balance: Decimal = Decimal("0")
    overdue_amount: Decimal = Decimal("0")
    open_follow_ups: int = 0
