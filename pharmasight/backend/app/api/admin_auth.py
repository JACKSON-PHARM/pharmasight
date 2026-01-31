"""
Admin Authentication API
Handles admin login separately from regular user authentication
"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from app.services.admin_auth_service import AdminAuthService
import os

router = APIRouter()


class AdminLoginRequest(BaseModel):
    """Admin login request"""
    username: str  # Changed from email to username
    password: str


class AdminLoginResponse(BaseModel):
    """Admin login response"""
    success: bool
    is_admin: bool
    message: str
    token: str = None  # Simple token for frontend to identify admin session


@router.post("/admin/auth/login", response_model=AdminLoginResponse)
def admin_login(request: AdminLoginRequest):
    """
    Admin login endpoint
    Validates admin credentials and returns admin token
    """
    # Check if credentials match admin
    is_admin = AdminAuthService.authenticate_admin(request.username, request.password)
    
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials"
        )
    
    # Generate simple admin token (in production, use JWT)
    import secrets
    admin_token = secrets.token_urlsafe(32)
    
    return AdminLoginResponse(
        success=True,
        is_admin=True,
        message="Admin authentication successful",
        token=admin_token
    )


@router.get("/admin/auth/verify")
def verify_admin(token: str):
    """Verify admin token (placeholder - in production use JWT)"""
    # For now, just check if token exists
    # In production, verify JWT token
    return {"is_admin": True, "valid": bool(token)}
