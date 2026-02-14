"""
Company and Branch API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import os
import shutil
from pathlib import Path
from app.dependencies import get_tenant_db
from app.models.company import Company, Branch
from app.schemas.company import (
    CompanyCreate, CompanyResponse, CompanyUpdate,
    BranchCreate, BranchResponse, BranchUpdate
)

router = APIRouter()

# Logo upload directory
UPLOAD_DIR = Path("uploads/logos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# Company endpoints
@router.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(company: CompanyCreate, db: Session = Depends(get_tenant_db)):
    """
    Create a new company
    
    **IMPORTANT: This database supports only ONE company.**
    Use /api/startup endpoint for complete initialization instead.
    """
    from app.services.startup_service import StartupService
    
    # Enforce ONE COMPANY rule
    if StartupService.check_company_exists(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company already exists. This database supports only ONE company. "
                   "Use /api/startup for complete initialization, or update the existing company."
        )
    
    try:
        # Use model_dump() for Pydantic v2, fallback to dict() for v1
        if hasattr(company, 'model_dump'):
            company_data = company.model_dump(exclude_none=False)
        else:
            company_data = company.dict()
        
        # Handle fiscal_start_date - convert empty string to None
        if 'fiscal_start_date' in company_data and company_data['fiscal_start_date'] == '':
            company_data['fiscal_start_date'] = None
        
        # Create company with the data
        db_company = Company(**company_data)
        db.add(db_company)
        db.flush()  # Get the ID before commit
        db.commit()
        db.refresh(db_company)
        
        # Return the database model directly - FastAPI will serialize it using the response_model
        return db_company
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error creating company: {error_details}")  # Log to console/terminal
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating company: {str(e)}"
        )


@router.get("/companies", response_model=List[CompanyResponse])
def get_companies(db: Session = Depends(get_tenant_db)):
    """Get all companies"""
    companies = db.query(Company).all()
    return companies


@router.get("/companies/{company_id}", response_model=CompanyResponse)
def get_company(company_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get company by ID"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.put("/companies/{company_id}", response_model=CompanyResponse)
def update_company(company_id: UUID, company_update: CompanyUpdate, db: Session = Depends(get_tenant_db)):
    """Update company"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    update_data = company_update.model_dump(exclude_unset=True) if hasattr(company_update, 'model_dump') else company_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)
    
    db.commit()
    db.refresh(company)
    return company


@router.post("/companies/{company_id}/logo", response_model=CompanyResponse)
async def upload_company_logo(
    company_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db)
):
    """
    Upload company logo
    
    Accepts image files (PNG, JPG, JPEG, GIF, WEBP)
    Returns the company with updated logo_url
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Validate file type
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Validate file size (max 5MB)
    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:  # 5MB
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 5MB"
        )
    
    try:
        # Generate unique filename
        filename = f"{company_id}_{int(os.urandom(4).hex(), 16)}{file_ext}"
        file_path = UPLOAD_DIR / filename
        
        # Save file
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)
        
        # Generate URL (relative path for now, can be absolute URL in production)
        # In production, you might want to use S3, Cloudinary, or similar
        logo_url = f"/uploads/logos/{filename}"
        
        # Update company
        company.logo_url = logo_url
        db.commit()
        db.refresh(company)
        
        return company
        
    except Exception as e:
        db.rollback()
        # Clean up file if database update fails
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading logo: {str(e)}"
        )


# Branch endpoints
@router.post("/branches", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
def create_branch(branch: BranchCreate, db: Session = Depends(get_tenant_db)):
    """
    Create a new branch
    
    **IMPORTANT: Branch code is REQUIRED and used in invoice numbering.**
    Format for invoice numbers: {BRANCH_CODE}-INV-YYYY-000001
    """
    try:
        # Verify company exists
        company = db.query(Company).filter(Company.id == branch.company_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Validate branch code is provided (schema should enforce, but double-check)
        if not branch.code or branch.code.strip() == '':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Branch code is REQUIRED. It is used in invoice numbering (format: {BRANCH_CODE}-INV-YYYY-000001)"
            )
        
        # Use model_dump() for Pydantic v2, fallback to dict() for v1
        branch_data = branch.model_dump() if hasattr(branch, 'model_dump') else branch.dict()
        db_branch = Branch(**branch_data)
        db.add(db_branch)
        db.commit()
        db.refresh(db_branch)
        return db_branch
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error creating branch: {error_details}")  # Log to console
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating branch: {str(e)}"
        )


@router.get("/branches/company/{company_id}", response_model=List[BranchResponse])
def get_branches_by_company(company_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get all branches for a company"""
    branches = db.query(Branch).filter(Branch.company_id == company_id).all()
    return branches


@router.get("/branches/{branch_id}", response_model=BranchResponse)
def get_branch(branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get branch by ID"""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch


@router.put("/branches/{branch_id}", response_model=BranchResponse)
def update_branch(branch_id: UUID, branch_update: BranchUpdate, db: Session = Depends(get_tenant_db)):
    """Update branch"""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    update_data = branch_update.model_dump(exclude_unset=True) if hasattr(branch_update, 'model_dump') else branch_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(branch, field, value)
    
    db.commit()
    db.refresh(branch)
    return branch


@router.post("/branches/{branch_id}/set-hq", response_model=BranchResponse)
def set_branch_as_hq(branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """
    Set this branch as the HQ (headquarters) branch.
    Only one branch per company can be HQ. HQ has exclusive access to:
    create items, suppliers, users, roles, and other branches.
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Clear is_hq on all other branches of the same company
    db.query(Branch).filter(
        Branch.company_id == branch.company_id,
        Branch.id != branch_id,
    ).update({Branch.is_hq: False})

    branch.is_hq = True
    db.commit()
    db.refresh(branch)
    return branch

