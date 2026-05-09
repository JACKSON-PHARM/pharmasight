from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class InsuranceProviderBase(BaseModel):
    name: str
    code: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    terms_days: Decimal = Field(default=30, ge=0)
    is_active: bool = True


class InsuranceProviderCreate(InsuranceProviderBase):
    pass


class InsuranceProviderUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    terms_days: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class InsuranceProviderResponse(InsuranceProviderBase):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InsuranceClaimStatusUpdate(BaseModel):
    status: str
    approved_amount: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class InsuranceClaimResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    insurance_provider_id: UUID
    sales_invoice_id: UUID
    claim_number: str
    status: str
    billed_amount: Decimal
    approved_amount: Decimal
    settled_amount: Decimal
    outstanding_amount: Decimal
    submitted_at: Optional[datetime] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InsuranceSettlementAllocationCreate(BaseModel):
    insurance_claim_id: UUID
    allocated_amount: Decimal = Field(..., gt=0)


class InsuranceSettlementCreate(BaseModel):
    branch_id: UUID
    insurance_provider_id: UUID
    settlement_date: date
    method: str = "bank"
    reference: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    notes: Optional[str] = None
    allocations: List[InsuranceSettlementAllocationCreate] = []


class InsuranceSettlementAllocationResponse(BaseModel):
    id: UUID
    insurance_settlement_id: UUID
    insurance_claim_id: UUID
    allocated_amount: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class InsuranceSettlementResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    insurance_provider_id: UUID
    settlement_number: str
    settlement_date: date
    method: str
    reference: Optional[str] = None
    amount: Decimal
    notes: Optional[str] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    allocations: List[InsuranceSettlementAllocationResponse] = []

    class Config:
        from_attributes = True


class InsuranceAgingRow(BaseModel):
    provider_id: UUID
    provider_name: str
    current: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    days_91_plus: Decimal
    total: Decimal
