"""
User Invitation API (internal-only).

Invites are accepted using a one-time `invitation_token` stored in the tenant DB.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.dependencies import get_current_user, get_tenant_from_header, get_tenant_db
from app.schemas.invite import (
    InviteAdminRequest,
    InviteAdminResponse,
    UpdateUserMetadataRequest,
    SetupStatusResponse,
    AcceptInviteRequest,
    AcceptInviteResponse,
)
from app.models.user import User
from app.utils.auth_internal import hash_password, validate_new_password
from datetime import datetime, timezone
from app.services.startup_service import StartupService

router = APIRouter()


@router.post("/invite/admin", response_model=InviteAdminResponse, status_code=status.HTTP_201_CREATED)
def invite_admin_user(
    request: InviteAdminRequest,
    current_user_and_db: tuple = Depends(get_current_user),
):
    """
    Deprecated: Supabase Auth invite flow removed.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Supabase Auth invitation endpoints have been removed. Use internal invite flow endpoints instead.",
    )


@router.post("/invite/update-metadata", status_code=status.HTTP_200_OK)
def update_user_metadata(request: UpdateUserMetadataRequest):
    """
    Deprecated: Supabase Auth metadata updates removed.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Supabase Auth metadata endpoints have been removed.",
    )


@router.post("/invite/mark-setup-complete", status_code=status.HTTP_200_OK)
def mark_setup_complete(
    user_id: UUID = Query(..., description="Supabase Auth user ID"),
    current_user_and_db: tuple = Depends(get_current_user),
):
    """
    Deprecated: Supabase Auth metadata updates removed.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Supabase Auth metadata endpoints have been removed.",
    )


@router.post("/invite/accept", response_model=AcceptInviteResponse, status_code=status.HTTP_200_OK)
def accept_invite(
    body: AcceptInviteRequest,
    tenant=Depends(get_tenant_from_header),
    db: Session = Depends(get_tenant_db),
):
    """Accept an invite using internal `invitation_token` stored in tenant DB."""
    if not tenant:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant context required (X-Tenant-Subdomain)")
    user = db.query(User).filter(User.invitation_token == body.invitation_token, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired invitation")
    pw_error = validate_new_password(body.new_password)
    if pw_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=pw_error)
    user.password_hash = hash_password(body.new_password)
    user.password_updated_at = datetime.now(timezone.utc)
    user.password_set = True
    user.is_pending = False
    user.invitation_token = None
    user.is_active = True
    if hasattr(user, "must_change_password"):
        user.must_change_password = False
    db.commit()
    return AcceptInviteResponse(message="Password set. Sign in with your username and password.")


@router.get("/setup/status", response_model=SetupStatusResponse)
def get_setup_status(
    user_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
):
    """
    Check if user needs to complete company setup
    
    Uses the DB from the authenticated user's context (JWT/token), not the
    X-Tenant-Subdomain header, so we always check the correct tenant/legacy DB.
    This avoids redirecting default-company users to setup when the browser
    still has another tenant in storage (e.g. after visiting a client's link).
    
    Returns:
    - needs_setup: true if user needs to complete setup
    - company_exists: whether company exists in database
    - must_setup_company: value from user metadata (if available)
    
    Frontend should redirect to /setup if needs_setup is true.
    """
    _user, db = current_user_and_db
    try:
        # Check if company exists in THIS user's DB (token-based), not header-based
        company_exists = StartupService.check_company_exists(db)
        
        # TODO: Check user metadata from Supabase Auth
        # For now, we'll determine needs_setup based on company_exists
        # In production, also check user.metadata.must_setup_company
        
        needs_setup = not company_exists
        
        return SetupStatusResponse(
            needs_setup=needs_setup,
            company_exists=company_exists,
            user_id=user_id,
            must_setup_company=None  # TODO: Fetch from Supabase Auth user metadata
        )
    except Exception as e:
        # If check fails, assume setup is needed
        return SetupStatusResponse(
            needs_setup=True,
            company_exists=False,
            user_id=user_id,
            must_setup_company=None
        )
