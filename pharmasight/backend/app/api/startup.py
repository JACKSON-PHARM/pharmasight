"""
Company Startup/Initialization API

Handles the complete company setup flow.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from app.dependencies import get_tenant_db
from app.services.startup_service import StartupService
from app.services.invite_service import InviteService
from app.schemas.startup import StartupRequest, StartupResponse

router = APIRouter()


@router.post("/startup", response_model=StartupResponse, status_code=status.HTTP_201_CREATED)
def initialize_company(startup: StartupRequest, db: Session = Depends(get_tenant_db)):
    """
    Complete company initialization (multi-company safe).
    - If no company exists: creates first company, branch, assigns user.
    - If user already has a company (e.g. from invite): completes setup for that company.
    - If other companies exist but user has none: creates a new company for this user.
    """
    try:
        # Prepare data dictionaries
        company_data = startup.company.model_dump() if hasattr(startup.company, 'model_dump') else startup.company.dict()
        admin_data = startup.admin_user.model_dump() if hasattr(startup.admin_user, 'model_dump') else startup.admin_user.dict()
        branch_data = startup.branch.model_dump() if hasattr(startup.branch, 'model_dump') else startup.branch.dict()
        
        # Handle fiscal_start_date - convert empty string to None
        if 'fiscal_start_date' in company_data and company_data['fiscal_start_date'] == '':
            company_data['fiscal_start_date'] = None
        
        # Initialize company
        result = StartupService.initialize_company(
            db=db,
            company_data=company_data,
            admin_user_data=admin_data,
            branch_data=branch_data
        )
        
        # Mark setup as complete in Supabase Auth user metadata
        try:
            user_id = admin_data.get('id')
            if user_id:
                InviteService.mark_setup_complete(str(user_id))
        except Exception as e:
            # Log error but don't fail the request
            # Setup is complete in database, metadata update is optional
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to update user metadata after setup: {str(e)}")
        
        return StartupResponse(**result)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        db.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error initializing company: {error_details}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error initializing company: {str(e)}"
        )


@router.get("/startup/status")
def get_startup_status(db: Session = Depends(get_tenant_db)):
    """
    Check if company has been initialized
    
    Returns whether the database has been initialized with a company.
    """
    try:
        company_exists = StartupService.check_company_exists(db)
        company_id = None
        
        if company_exists:
            company_id = StartupService.get_company_id(db)
        
        return {
            "initialized": company_exists,
            "company_id": str(company_id) if company_id else None
        }
    except Exception as e:
        # If database query fails, assume not initialized
        import traceback
        print(f"Error checking startup status: {traceback.format_exc()}")
        return {
            "initialized": False,
            "company_id": None,
            "error": str(e)
        }

