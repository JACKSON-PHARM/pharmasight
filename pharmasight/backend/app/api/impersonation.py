"""
PLATFORM_ADMIN-only impersonation API.

Allows platform admins to temporarily act as a company user for troubleshooting.
Every impersonation is logged to admin_impersonation_log. Tokens are short-lived (15 min).
Company isolation is preserved: the token grants only the impersonated user's permissions.
"""
import hashlib
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_admin, get_effective_company_id_for_user
from app.models.company import Company, Branch
from app.models.user import User, UserBranchRole, UserRole
from app.services.impersonation_service import log_impersonation_start
from app.utils.auth_internal import (
    create_impersonation_access_token,
    IMPERSONATION_TOKEN_EXPIRE_MINUTES,
)
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


def _admin_identifier_from_request(request: Request) -> str:
    """Derive a stable, non-reversible identifier for the admin session (for audit log)."""
    auth = request.headers.get("Authorization") or ""
    token = (auth[7:].strip() if auth.startswith("Bearer ") else "") or ""
    if not token:
        return "platform_admin"
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def _client_ip(request: Request) -> Optional[str]:
    """Client IP; respects X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    if request.client:
        return (request.client.host or "")[:45]
    return None


def _get_user_for_company(db: Session, company_id: UUID) -> User:
    """
    Return a user who has access to the given company (via UserBranchRole -> Branch).
    Prefer a user with role 'admin'. Single-DB: companies and users are in the same DB.
    """
    # UserBranchRole -> Branch where branch.company_id == company_id; prefer admin role
    admin_role = db.query(UserRole).filter(UserRole.role_name == "admin").first()
    if admin_role:
        row = (
            db.query(User)
            .join(UserBranchRole, UserBranchRole.user_id == User.id)
            .join(Branch, Branch.id == UserBranchRole.branch_id)
            .filter(
                Branch.company_id == company_id,
                UserBranchRole.role_id == admin_role.id,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
            .first()
        )
        if row:
            return row
    # Fallback: any user with a branch in this company
    row = (
        db.query(User)
        .join(UserBranchRole, UserBranchRole.user_id == User.id)
        .join(Branch, Branch.id == UserBranchRole.branch_id)
        .filter(
            Branch.company_id == company_id,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
        )
        .first()
    )
    if row:
        return row
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No active user found for this company. Ensure at least one user is assigned to a branch.",
    )


class ImpersonateCompanyBody(BaseModel):
    """Optional body for POST /impersonate/{company_id}."""
    reason: Optional[str] = Field(None, max_length=500, description="Optional reason for audit log")


class ImpersonateUserBody(BaseModel):
    """Optional body for POST /impersonate-user/{user_id}."""
    reason: Optional[str] = Field(None, max_length=500, description="Optional reason for audit log")


class ImpersonationResponse(BaseModel):
    """Response for impersonation endpoints."""
    access_token: str
    expires_in_minutes: int = IMPERSONATION_TOKEN_EXPIRE_MINUTES
    impersonation: bool = True
    user_id: str
    company_id: str
    email: str
    message: str = "Use this token as Authorization: Bearer <access_token>. Frontend should show admin impersonation banner."


@router.post("/impersonate/{company_id}", response_model=ImpersonationResponse)
@limiter.limit("5/minute")
def impersonate_company(
    request: Request,
    company_id: UUID,
    body: Optional[ImpersonateCompanyBody] = Body(None),
    _admin: None = Depends(get_current_admin),
):
    """
    **PLATFORM_ADMIN only.** Start an impersonation session as a user in the given company.

    Picks an active user with access to the company (prefers admin role). Returns a short-lived
    JWT (15 min) that authenticates as that user. Use the token in Authorization header when
    calling the main app API; the frontend must show an "Admin impersonation" banner.

    Every call is logged to `admin_impersonation_log` (admin_identifier, company_id, user_id, IP, reason).
    Rate limited: 5 requests per minute per IP.
    """
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found",
            )
        user = _get_user_for_company(db, company_id)
        company_id_str = str(company_id)
        effective_company_id = get_effective_company_id_for_user(db, user)
        if effective_company_id != company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected user does not belong to the requested company.",
            )
        tenant_subdomain = None  # Single-DB: no tenant routing
        admin_id = _admin_identifier_from_request(request)
        token = create_impersonation_access_token(
            user_id=str(user.id),
            email=user.email or "",
            tenant_subdomain=tenant_subdomain,
            company_id=company_id_str,
            impersonated_by=admin_id,
        )
        log_impersonation_start(
            db=db,
            admin_identifier=admin_id,
            company_id=company_id,
            user_id=user.id,
            client_ip=_client_ip(request),
            reason=body.reason if body else None,
        )
        return ImpersonationResponse(
            access_token=token,
            user_id=str(user.id),
            company_id=company_id_str,
            email=user.email or "",
        )
    finally:
        db.close()


@router.post("/impersonate-user/{user_id}", response_model=ImpersonationResponse)
@limiter.limit("5/minute")
def impersonate_user(
    request: Request,
    user_id: UUID,
    body: Optional[ImpersonateUserBody] = Body(None),
    _admin: None = Depends(get_current_admin),
):
    """
    **PLATFORM_ADMIN only.** Start an impersonation session as a specific user.

    Returns a short-lived JWT (15 min) that authenticates as that user. The user must exist
    and be active. Every call is logged. Rate limited: 5 per minute per IP.
    """
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.id == user_id, User.deleted_at.is_(None), User.is_active.is_(True))
            .first()
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or inactive",
            )
        effective_company_id = get_effective_company_id_for_user(db, user)
        if not effective_company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has no company (no branch assignment). Cannot impersonate.",
            )
        company_id_str = str(effective_company_id)
        tenant_subdomain = None
        admin_id = _admin_identifier_from_request(request)
        token = create_impersonation_access_token(
            user_id=str(user.id),
            email=user.email or "",
            tenant_subdomain=tenant_subdomain,
            company_id=company_id_str,
            impersonated_by=admin_id,
        )
        log_impersonation_start(
            db=db,
            admin_identifier=admin_id,
            company_id=effective_company_id,
            user_id=user.id,
            client_ip=_client_ip(request),
            reason=body.reason if body else None,
        )
        return ImpersonationResponse(
            access_token=token,
            user_id=str(user.id),
            company_id=company_id_str,
            email=user.email or "",
        )
    finally:
        db.close()
