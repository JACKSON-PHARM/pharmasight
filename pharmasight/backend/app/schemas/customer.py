"""
Customer (wholesale B2B) schemas
"""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class CustomerBase(BaseModel):
    name: str = Field(..., description="Customer / institution name")
    pin: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    customer_type: str = Field(default="PHARMACY", description="PHARMACY, HOSPITAL, CLINIC, INSTITUTION, OTHER")
    default_payment_terms_days: Optional[int] = None
    credit_limit: Optional[float] = None
    allow_over_credit: Optional[bool] = None
    credit_enabled: Optional[bool] = True
    default_sales_type: str = Field(default="WHOLESALE")
    opening_balance: Optional[float] = None
    notes: Optional[str] = None
    portal_enabled: Optional[bool] = False


class CustomerCreate(CustomerBase):
    company_id: UUID


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    pin: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    customer_type: Optional[str] = None
    default_payment_terms_days: Optional[int] = None
    credit_limit: Optional[float] = None
    allow_over_credit: Optional[bool] = None
    credit_enabled: Optional[bool] = None
    default_sales_type: Optional[str] = None
    opening_balance: Optional[float] = None
    notes: Optional[str] = None
    portal_enabled: Optional[bool] = None
    is_active: Optional[bool] = None


class CustomerMergeRequest(BaseModel):
    from_customer_id: UUID
    to_customer_id: UUID


class CustomerResponse(CustomerBase):
    id: UUID
    company_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
