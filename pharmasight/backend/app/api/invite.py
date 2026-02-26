"""
User Invitation API

Handles inviting admin users via Supabase Auth.
This endpoint requires admin privileges and uses Supabase Service Role Key.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.dependencies import get_tenant_db, get_current_user
from app.services.invite_service import InviteService
from app.services.startup_service import StartupService
from app.schemas.invite import (
    InviteAdminRequest,
    InviteAdminResponse,
    UpdateUserMetadataRequest,
    SetupStatusResponse
)
from uuid import UUID

router = APIRouter()


@router.post("/invite/admin", response_model=InviteAdminResponse, status_code=status.HTTP_201_CREATED)
def invite_admin_user(
    request: InviteAdminRequest,
    current_user_and_db: tuple = Depends(get_current_user),
):
    """
    Invite an admin user via Supabase Auth
    
    This endpoint:
    1. Creates a user in Supabase Auth (no password)
    2. Sends invite email to user
    3. Sets metadata: role=company_admin, must_setup_company=true
    4. Returns user ID for app database record creation
    
    **Security**: This endpoint requires Supabase Service Role Key.
    Should be protected by additional admin authentication in production.
    
    **Email**: Invite email will be sent from pharmasightsolutions@gmail.com
    (configured in Supabase project settings)
    """
    try:
        result = InviteService.invite_admin_user(
            email=request.email,
            full_name=request.full_name,
            redirect_to=request.redirect_to or "/setup"
        )
        
        if result["success"]:
            return InviteAdminResponse(**result)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to invite admin user")
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error inviting admin user: {str(e)}"
        )


@router.post("/invite/update-metadata", status_code=status.HTTP_200_OK)
def update_user_metadata(request: UpdateUserMetadataRequest):
    """
    Update user metadata in Supabase Auth
    
    Used to update user metadata after setup completion.
    """
    try:
        result = InviteService.update_user_metadata(
            user_id=str(request.user_id),
            metadata=request.metadata
        )
        
        if result["success"]:
            return {"success": True, "message": result["message"]}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to update user metadata")
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating user metadata: {str(e)}"
        )


@router.post("/invite/mark-setup-complete", status_code=status.HTTP_200_OK)
def mark_setup_complete(
    user_id: UUID = Query(..., description="Supabase Auth user ID"),
    current_user_and_db: tuple = Depends(get_current_user),
):
    """
    Mark company setup as complete for a user
    
    Updates user metadata: must_setup_company = false
    """
    try:
        result = InviteService.mark_setup_complete(str(user_id))
        
        if result["success"]:
            return {"success": True, "message": result["message"]}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to mark setup as complete")
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error marking setup as complete: {str(e)}"
        )


@router.get("/setup/status", response_model=SetupStatusResponse)
def get_setup_status(
    user_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Check if user needs to complete company setup
    
    Returns:
    - needs_setup: true if user needs to complete setup
    - company_exists: whether company exists in database
    - must_setup_company: value from user metadata (if available)
    
    Frontend should redirect to /setup if needs_setup is true.
    """
    try:
        # Check if company exists
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
