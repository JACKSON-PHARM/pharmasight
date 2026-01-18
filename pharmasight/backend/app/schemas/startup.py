"""
Startup/Initialization schemas
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import date
from uuid import UUID


class CompanySetupData(BaseModel):
    """Company data for initialization"""
    name: str = Field(..., min_length=1, max_length=255)
    registration_number: Optional[str] = None
    pin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    currency: str = Field(default="KES", max_length=10)
    timezone: str = Field(default="Africa/Nairobi", max_length=50)
    fiscal_start_date: Optional[date] = None


class AdminUserSetupData(BaseModel):
    """Admin user data for initialization"""
    id: UUID = Field(..., description="Must match Supabase Auth user_id")
    email: EmailStr
    full_name: Optional[str] = None
    phone: Optional[str] = None


class BranchSetupData(BaseModel):
    """Branch data for initialization"""
    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=50, description="Optional: Auto-generated as BR001 if first branch and not provided")
    address: Optional[str] = None
    phone: Optional[str] = None


class StartupRequest(BaseModel):
    """Complete startup request"""
    company: CompanySetupData
    admin_user: AdminUserSetupData
    branch: BranchSetupData


class StartupResponse(BaseModel):
    """Startup response"""
    company_id: UUID
    user_id: UUID
    branch_id: UUID
    message: str

    class Config:
        from_attributes = True

