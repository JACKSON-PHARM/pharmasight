"""
Company and Branch schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date
from uuid import UUID


class CompanyBase(BaseModel):
    """Company base schema"""
    name: str = Field(..., min_length=1, max_length=255)
    registration_number: Optional[str] = None
    pin: Optional[str] = None
    logo_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    currency: str = Field(default="KES", max_length=10)
    timezone: str = Field(default="Africa/Nairobi", max_length=50)
    fiscal_start_date: Optional[date] = None


class CompanyCreate(CompanyBase):
    """Create company request"""
    pass


class CompanyUpdate(BaseModel):
    """Update company request"""
    name: Optional[str] = None
    registration_number: Optional[str] = None
    pin: Optional[str] = None
    logo_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    fiscal_start_date: Optional[date] = None


class CompanyResponse(CompanyBase):
    """Company response"""
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BranchBase(BaseModel):
    """Branch base schema"""
    company_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=50, description="REQUIRED: Used in invoice numbering")
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = Field(default=True)


class BranchCreate(BranchBase):
    """Create branch request"""
    pass


class BranchUpdate(BaseModel):
    """Update branch request"""
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class BranchResponse(BranchBase):
    """Branch response"""
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SupplierBase(BaseModel):
    """Supplier base schema"""
    company_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    pin: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    credit_terms: Optional[int] = Field(None, ge=0, description="Credit terms in days")
    is_active: bool = Field(default=True)


class SupplierCreate(SupplierBase):
    """Create supplier request"""
    pass


class SupplierUpdate(BaseModel):
    """Update supplier request"""
    name: Optional[str] = None
    pin: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    credit_terms: Optional[int] = None
    is_active: Optional[bool] = None


class SupplierResponse(SupplierBase):
    """Supplier response"""
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

