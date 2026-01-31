"""
Suppliers API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List, Optional
from uuid import UUID
from app.dependencies import get_tenant_db
from app.models import Supplier
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter()


class SupplierBase(BaseModel):
    """Supplier base schema"""
    name: str = Field(..., description="Supplier name")
    pin: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    credit_terms: Optional[int] = None  # days


class SupplierCreate(SupplierBase):
    """Create supplier request"""
    company_id: UUID


class SupplierResponse(SupplierBase):
    """Supplier response"""
    id: UUID
    company_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/search")
def search_suppliers(
    q: str = Query(..., min_length=2, description="Search query"),
    company_id: UUID = Query(..., description="Company ID"),
    limit: int = Query(10, ge=1, le=20, description="Maximum results"),
    db: Session = Depends(get_tenant_db)
):
    """
    Lightweight supplier search endpoint for ERP-style inline search.
    Returns minimal data: id, name.
    No relations, no extra fields.
    Optimized with ordering and proper NULL handling.
    """
    search_term = f"%{q.lower()}%"
    
    # Query only essential fields with proper NULL handling
    # Order by name for consistent results
    suppliers = db.query(
        Supplier.id,
        Supplier.name
    ).filter(
        Supplier.company_id == company_id,
        Supplier.is_active == True,
        or_(
            func.lower(Supplier.name).like(search_term),
            func.lower(Supplier.contact_person).like(search_term),
            func.lower(Supplier.phone).like(search_term)
        )
    ).order_by(Supplier.name.asc()).limit(limit).all()
    
    # Return minimal response
    return [
        {
            "id": str(supplier.id),
            "name": supplier.name
        }
        for supplier in suppliers
    ]


@router.get("/company/{company_id}", response_model=List[SupplierResponse])
def list_suppliers(company_id: UUID, db: Session = Depends(get_tenant_db)):
    """List all suppliers for a company"""
    suppliers = db.query(Supplier).filter(
        Supplier.company_id == company_id,
        Supplier.is_active == True
    ).order_by(Supplier.name).all()
    return suppliers


@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
def create_supplier(supplier: SupplierCreate, db: Session = Depends(get_tenant_db)):
    """Create a new supplier"""
    db_supplier = Supplier(
        company_id=supplier.company_id,
        name=supplier.name,
        pin=supplier.pin,
        contact_person=supplier.contact_person,
        phone=supplier.phone,
        email=supplier.email,
        address=supplier.address,
        credit_terms=supplier.credit_terms
    )
    db.add(db_supplier)
    db.commit()
    db.refresh(db_supplier)
    return db_supplier


@router.get("/{supplier_id}", response_model=SupplierResponse)
def get_supplier(supplier_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get supplier by ID"""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@router.put("/{supplier_id}", response_model=SupplierResponse)
def update_supplier(supplier_id: UUID, supplier: SupplierBase, db: Session = Depends(get_tenant_db)):
    """Update supplier"""
    db_supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not db_supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    
    for key, value in supplier.dict(exclude_unset=True).items():
        setattr(db_supplier, key, value)
    
    db.commit()
    db.refresh(db_supplier)
    return db_supplier
