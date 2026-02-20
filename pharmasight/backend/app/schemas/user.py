"""
User management schemas
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


# =====================================================
# User Role Schemas
# =====================================================

class UserRoleResponse(BaseModel):
    """User role response schema"""
    id: UUID
    role_name: str
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# User Branch Role Schemas
# =====================================================

class UserBranchRoleResponse(BaseModel):
    """User branch role response (with role and branch details)"""
    id: UUID
    user_id: UUID
    branch_id: UUID
    role_id: UUID
    role_name: Optional[str] = None  # Populated from join
    branch_name: Optional[str] = None  # Populated from join
    created_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# User Schemas
# =====================================================

class UserCreate(BaseModel):
    """Schema for creating a new user (Admin-only)"""
    email: EmailStr
    username: Optional[str] = Field(None, description="Username for login. If not provided, auto-generated from full_name (e.g., 'D-JACKSON')")
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role_name: str = Field(..., description="Role name (e.g., 'admin', 'pharmacist', 'cashier')")
    branch_id: Optional[UUID] = Field(None, description="Optional branch ID to assign user to")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "D-JACKSON",  # Optional - auto-generated if not provided
                "full_name": "Dr. Jackson",
                "phone": "+254700000000",
                "role_name": "pharmacist",
                "branch_id": "123e4567-e89b-12d3-a456-426614174000"
            }
        }


class UserUpdate(BaseModel):
    """Schema for updating user details"""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    ppb_number: Optional[str] = None
    designation: Optional[str] = None


class UserResponse(BaseModel):
    """User response schema with role information"""
    id: UUID
    email: str
    username: Optional[str] = None  # Username for login
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    signature_path: Optional[str] = None  # Path in storage; no URL in company settings
    ppb_number: Optional[str] = None
    designation: Optional[str] = None
    is_pending: bool
    password_set: bool
    invitation_code: Optional[str] = None  # Show invitation code if pending
    deleted_at: Optional[datetime] = None  # Soft delete timestamp
    branch_roles: List[UserBranchRoleResponse] = []  # List of branch-role assignments
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """List of users with basic info"""
    users: List[UserResponse]
    total: int


# =====================================================
# User Management Action Schemas
# =====================================================

class UserActivateRequest(BaseModel):
    """Schema for activating/deactivating a user"""
    is_active: bool


class UserRoleUpdate(BaseModel):
    """Schema for updating user role assignment"""
    role_name: str
    branch_id: Optional[UUID] = None  # If None, update all roles, else specific branch


class InvitationResponse(BaseModel):
    """Response when user is created with invitation"""
    user_id: UUID
    email: str
    username: str  # Generated username for login
    invitation_token: str
    invitation_code: str
    invitation_link: Optional[str] = None  # Full invitation URL if available
    message: str = "User created successfully. Invitation code generated."
