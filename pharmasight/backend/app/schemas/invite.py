"""
Schemas for user invitation
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID


class InviteAdminRequest(BaseModel):
    """Request to invite an admin user"""
    email: EmailStr = Field(..., description="Admin user email address")
    full_name: Optional[str] = Field(None, description="Full name of admin user")
    redirect_to: Optional[str] = Field("/setup", description="Redirect URL after password setup")


class InviteAdminResponse(BaseModel):
    """Response from admin user invitation"""
    success: bool
    user_id: Optional[UUID] = None
    email: str
    message: str
    error: Optional[str] = None


class UpdateUserMetadataRequest(BaseModel):
    """Request to update user metadata"""
    user_id: UUID = Field(..., description="Supabase Auth user ID")
    metadata: dict = Field(..., description="Metadata to update")


class SetupStatusResponse(BaseModel):
    """Response for setup status check"""
    needs_setup: bool = Field(..., description="Whether user needs to complete setup")
    company_exists: bool = Field(..., description="Whether company exists in database")
    user_id: Optional[UUID] = None
    must_setup_company: Optional[bool] = None


class AcceptInviteRequest(BaseModel):
    """Accept an invitation and set an initial password (internal auth only)."""
    invitation_token: str = Field(..., min_length=8, description="Invitation token from invite link")
    new_password: str = Field(..., min_length=8, description="New password to set")


class AcceptInviteResponse(BaseModel):
    """Response from invite acceptance."""
    message: str
