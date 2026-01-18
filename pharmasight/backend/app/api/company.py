"""
Company and Branch API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.models.company import Company, Branch
from app.schemas.company import (
    CompanyCreate, CompanyResponse, CompanyUpdate,
    BranchCreate, BranchResponse, BranchUpdate
)

router = APIRouter()


# Company endpoints
@router.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(company: CompanyCreate, db: Session = Depends(get_db)):
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
def get_companies(db: Session = Depends(get_db)):
    """Get all companies"""
    companies = db.query(Company).all()
    return companies


@router.get("/companies/{company_id}", response_model=CompanyResponse)
def get_company(company_id: UUID, db: Session = Depends(get_db)):
    """Get company by ID"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.put("/companies/{company_id}", response_model=CompanyResponse)
def update_company(company_id: UUID, company_update: CompanyUpdate, db: Session = Depends(get_db)):
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


# Branch endpoints
@router.post("/branches", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
def create_branch(branch: BranchCreate, db: Session = Depends(get_db)):
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
def get_branches_by_company(company_id: UUID, db: Session = Depends(get_db)):
    """Get all branches for a company"""
    branches = db.query(Branch).filter(Branch.company_id == company_id).all()
    return branches


@router.get("/branches/{branch_id}", response_model=BranchResponse)
def get_branch(branch_id: UUID, db: Session = Depends(get_db)):
    """Get branch by ID"""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch


@router.put("/branches/{branch_id}", response_model=BranchResponse)
def update_branch(branch_id: UUID, branch_update: BranchUpdate, db: Session = Depends(get_db)):
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

