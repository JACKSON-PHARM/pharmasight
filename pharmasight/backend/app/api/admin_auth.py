"""
Platform admin authentication API.

Admin sign-in is password + email OTP. Password recovery is email-link based.
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import get_current_admin
from app.rate_limit import limiter
from app.services.admin_auth_service import AdminAuthService, DEFAULT_ADMIN_EMAIL
from app.services.admin_token_store import add_admin_token, get_admin_user_id, revoke_admin_token
from app.utils.public_url import get_public_base_url

router = APIRouter()


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=512)


class AdminLoginResponse(BaseModel):
    success: bool
    is_admin: bool = False
    otp_required: bool = False
    challenge_id: Optional[str] = None
    email_masked: Optional[str] = None
    email_sent: Optional[bool] = None
    message: str
    token: Optional[str] = None


class AdminOtpVerifyRequest(BaseModel):
    challenge_id: str = Field(..., min_length=10, max_length=80)
    otp: str = Field(..., min_length=4, max_length=20)


class AdminResetRequest(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None


class AdminResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=512)


class AdminEmailChangeRequest(BaseModel):
    new_email: EmailStr


class AdminEmailChangeVerifyRequest(BaseModel):
    request_id: str = Field(..., min_length=10, max_length=80)
    otp: str = Field(..., min_length=4, max_length=20)


def _current_admin_user_id(request: Request) -> str:
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    admin_user_id = get_admin_user_id(token or "")
    if not admin_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return admin_user_id


@router.post("/admin/auth/login", response_model=AdminLoginResponse)
@limiter.limit("5/minute")
def admin_login(request: Request, body: AdminLoginRequest):
    result = AdminAuthService.start_login(body.username, body.password)
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "password_not_set":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin password is not set yet. Use Forgot password to create a secure password.",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")
    if not result.get("email_sent"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin OTP could not be sent. Check SMTP_HOST, SMTP_USER, and SMTP_PASSWORD on the backend.",
        )
    return AdminLoginResponse(
        success=True,
        otp_required=True,
        challenge_id=result.get("challenge_id"),
        email_masked=result.get("email_masked"),
        email_sent=True,
        message="Verification code sent to the admin email.",
    )


@router.post("/admin/auth/verify-otp", response_model=AdminLoginResponse)
@limiter.limit("10/minute")
def admin_verify_otp(request: Request, body: AdminOtpVerifyRequest):
    result = AdminAuthService.verify_otp(body.challenge_id, body.otp)
    if not result.get("ok"):
        reason = result.get("reason")
        msg = "Invalid verification code"
        if reason == "expired":
            msg = "Verification code expired. Sign in again."
        elif reason == "locked":
            msg = "Too many verification attempts. Sign in again."
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)
    token = secrets.token_urlsafe(32)
    add_admin_token(token, admin_user_id=result.get("admin_user_id"))
    return AdminLoginResponse(
        success=True,
        is_admin=True,
        otp_required=False,
        message="Admin authentication successful",
        token=token,
    )


@router.post("/admin/auth/request-reset")
@limiter.limit("3/hour")
def admin_request_reset(request: Request, body: AdminResetRequest):
    email_or_username = (str(body.email or "") or body.username or DEFAULT_ADMIN_EMAIL or "admin").strip()
    base_url = get_public_base_url(request)
    result = AdminAuthService.request_password_reset(email_or_username, base_url=base_url)
    return {
        "message": "If that admin account exists, a secure reset link has been sent.",
        "email_sent": bool(result.get("email_sent")),
    }


@router.post("/admin/auth/reset-password")
@limiter.limit("5/hour")
def admin_reset_password(request: Request, body: AdminResetPasswordRequest):
    result = AdminAuthService.reset_password(body.token, body.new_password)
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("reason") or "Invalid reset link")
    return {"message": "Admin password updated. Sign in again and complete email verification."}


@router.get("/admin/auth/verify")
def verify_admin(_admin: None = Depends(get_current_admin)):
    return {"is_admin": True, "valid": True}


@router.get("/admin/auth/profile")
def admin_profile(request: Request, _admin: None = Depends(get_current_admin)):
    result = AdminAuthService.get_admin_profile(_current_admin_user_id(request))
    if not result.get("ok"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("reason") or "Admin not found")
    return {
        "email": result.get("email"),
        "email_masked": result.get("email_masked"),
        "last_login_at": result.get("last_login_at"),
    }


@router.post("/admin/auth/email-change/request")
@limiter.limit("5/hour")
def admin_request_email_change(
    request: Request,
    body: AdminEmailChangeRequest,
    _admin: None = Depends(get_current_admin),
):
    result = AdminAuthService.request_email_change(_current_admin_user_id(request), str(body.new_email))
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("reason") or "Could not send verification code",
        )
    return {
        "message": "Verification code sent to the new admin email.",
        "request_id": result.get("request_id"),
        "email_masked": result.get("email_masked"),
        "email_sent": bool(result.get("email_sent")),
    }


@router.post("/admin/auth/email-change/verify")
@limiter.limit("10/hour")
def admin_verify_email_change(
    request: Request,
    body: AdminEmailChangeVerifyRequest,
    _admin: None = Depends(get_current_admin),
):
    result = AdminAuthService.verify_email_change(_current_admin_user_id(request), body.request_id, body.otp)
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("reason") or "Could not verify admin email",
        )
    return {
        "message": "Admin email updated.",
        "email": result.get("email"),
        "email_masked": result.get("email_masked"),
    }


@router.post("/admin/auth/logout")
def admin_logout(request: Request, _admin: None = Depends(get_current_admin)):
    auth = request.headers.get("Authorization")
    token = (auth[7:].strip() if auth and auth.startswith("Bearer ") else None) or None
    if token:
        revoke_admin_token(token)
    return {"message": "Logged out"}
