"""
Suppliers API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List, Optional
from uuid import UUID
from app.dependencies import get_tenant_db, get_current_user
from app.models import (
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    SupplierReturn,
    SupplierLedgerEntry,
    GRN,
    PurchaseOrder,
    Item,
    DailyOrderBook,
    OrderBookHistory,
    ItemBranchPurchaseSnapshot,
    ItemBranchSnapshot,
)
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
    default_payment_terms_days: Optional[int] = None
    credit_limit: Optional[float] = None
    allow_over_credit: Optional[bool] = None
    opening_balance: Optional[float] = None
    requires_supplier_invoice_number: Optional[bool] = Field(
        default=False,
        description="When true, supplier invoices require external supplier invoice number",
    )


class SupplierUpdate(BaseModel):
    """Supplier update schema - all optional"""
    name: Optional[str] = None
    pin: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    credit_terms: Optional[int] = None
    default_payment_terms_days: Optional[int] = None
    credit_limit: Optional[float] = None
    allow_over_credit: Optional[bool] = None
    opening_balance: Optional[float] = None
    requires_supplier_invoice_number: Optional[bool] = None


class SupplierMergeRequest(BaseModel):
    """
    Merge supplier A into supplier B.

    Implementation detail:
    We reassign all FK references from `from_supplier_id` -> `to_supplier_id`,
    null out any precomputed ledger running balances for the moved entries
    (frontend recalculates when running_balance is missing/NULL), then delete
    the source supplier record.
    """
    from_supplier_id: UUID
    to_supplier_id: UUID


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
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
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
def list_suppliers(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """List all suppliers for a company"""
    suppliers = db.query(Supplier).filter(
        Supplier.company_id == company_id,
        Supplier.is_active == True
    ).order_by(Supplier.name).all()
    return suppliers


@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
def create_supplier(
    supplier: SupplierCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Create a new supplier"""
    name_key = (supplier.name or "").strip().lower()
    if name_key:
        dup = db.query(Supplier).filter(
            Supplier.company_id == supplier.company_id,
            func.lower(func.trim(Supplier.name)) == name_key,
        ).first()
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A supplier named '{dup.name}' already exists for this company.",
            )

    db_supplier = Supplier(
        company_id=supplier.company_id,
        name=supplier.name,
        pin=supplier.pin,
        contact_person=supplier.contact_person,
        phone=supplier.phone,
        email=supplier.email,
        address=supplier.address,
        credit_terms=supplier.credit_terms,
        default_payment_terms_days=supplier.default_payment_terms_days,
        credit_limit=supplier.credit_limit,
        allow_over_credit=supplier.allow_over_credit or False,
        opening_balance=supplier.opening_balance or 0,
        requires_supplier_invoice_number=bool(supplier.requires_supplier_invoice_number),
    )
    db.add(db_supplier)
    db.commit()
    db.refresh(db_supplier)
    return db_supplier


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    supplier_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Permanently remove a supplier only when it has no purchase documents, payments, or ledger history.
    Use this to clean up mistaken duplicates. Otherwise deactivate suppliers from the UI if needed.
    """
    effective = getattr(request.state, "effective_company_id", None)
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if effective is not None and supplier.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    inv_c = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == supplier_id).count()
    pay_c = db.query(SupplierPayment).filter(SupplierPayment.supplier_id == supplier_id).count()
    ret_c = db.query(SupplierReturn).filter(SupplierReturn.supplier_id == supplier_id).count()
    led_c = db.query(SupplierLedgerEntry).filter(SupplierLedgerEntry.supplier_id == supplier_id).count()
    grn_c = db.query(GRN).filter(GRN.supplier_id == supplier_id).count()
    po_c = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == supplier_id).count()

    if inv_c or pay_c or ret_c or led_c or grn_c or po_c:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This supplier has related documents. Remove or reassign them before deleting.",
                "counts": {
                    "invoices": inv_c,
                    "payments": pay_c,
                    "returns": ret_c,
                    "ledger_entries": led_c,
                    "grns": grn_c,
                    "purchase_orders": po_c,
                },
            },
        )

    db.query(Item).filter(Item.default_supplier_id == supplier_id).update(
        {Item.default_supplier_id: None},
        synchronize_session=False,
    )
    db.delete(supplier)
    db.commit()
    return None


@router.get("/{supplier_id}", response_model=SupplierResponse)
def get_supplier(
    supplier_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get supplier by ID"""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@router.put("/{supplier_id}", response_model=SupplierResponse)
def update_supplier(
    supplier_id: UUID,
    supplier: SupplierUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Update supplier"""
    db_supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not db_supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    
    data = supplier.model_dump(exclude_unset=True) if hasattr(supplier, 'model_dump') else supplier.dict(exclude_unset=True)
    for key, value in data.items():
        if hasattr(db_supplier, key):
            setattr(db_supplier, key, value)
    
    db.commit()
    db.refresh(db_supplier)
    return db_supplier


@router.post("/merge")
def merge_suppliers(
    request: Request,
    merge: SupplierMergeRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Merge one supplier into another (move references, then delete duplicate).
    """
    effective = getattr(request.state, "effective_company_id", None)

    from_id = merge.from_supplier_id
    to_id = merge.to_supplier_id
    if str(from_id) == str(to_id):
        raise HTTPException(status_code=400, detail="Cannot merge a supplier into itself")

    from_supplier = db.query(Supplier).filter(Supplier.id == from_id).first()
    to_supplier = db.query(Supplier).filter(Supplier.id == to_id).first()
    if not from_supplier or not to_supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    if from_supplier.company_id != to_supplier.company_id:
        raise HTTPException(status_code=400, detail="Suppliers must belong to the same company")

    if effective is not None and from_supplier.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    company_id = from_supplier.company_id

    try:
        # Move core supplier-linked documents
        db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == from_id).update(
            {SupplierInvoice.supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(SupplierPayment).filter(SupplierPayment.supplier_id == from_id).update(
            {SupplierPayment.supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(SupplierReturn).filter(SupplierReturn.supplier_id == from_id).update(
            {SupplierReturn.supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(SupplierLedgerEntry).filter(SupplierLedgerEntry.supplier_id == from_id).update(
            {
                SupplierLedgerEntry.supplier_id: to_id,
                # Ensure frontend balance is correct after reassignment.
                SupplierLedgerEntry.running_balance: None,
            },
            synchronize_session=False,
        )
        db.query(GRN).filter(GRN.supplier_id == from_id).update(
            {GRN.supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == from_id).update(
            {PurchaseOrder.supplier_id: to_id},
            synchronize_session=False,
        )

        # Order book references (FKs can otherwise block deletion)
        db.query(DailyOrderBook).filter(DailyOrderBook.supplier_id == from_id).update(
            {DailyOrderBook.supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(OrderBookHistory).filter(OrderBookHistory.supplier_id == from_id).update(
            {OrderBookHistory.supplier_id: to_id},
            synchronize_session=False,
        )

        # Search snapshots / defaults used across the UI
        db.query(Item).filter(Item.default_supplier_id == from_id).update(
            {Item.default_supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(ItemBranchPurchaseSnapshot).filter(ItemBranchPurchaseSnapshot.last_supplier_id == from_id).update(
            {ItemBranchPurchaseSnapshot.last_supplier_id: to_id},
            synchronize_session=False,
        )
        db.query(ItemBranchSnapshot).filter(ItemBranchSnapshot.last_supplier_id == from_id).update(
            {ItemBranchSnapshot.last_supplier_id: to_id},
            synchronize_session=False,
        )

        db.flush()

        # Pre-check so we fail fast with a useful error message.
        inv_c = db.query(SupplierInvoice).filter(SupplierInvoice.supplier_id == from_id).count()
        pay_c = db.query(SupplierPayment).filter(SupplierPayment.supplier_id == from_id).count()
        ret_c = db.query(SupplierReturn).filter(SupplierReturn.supplier_id == from_id).count()
        led_c = db.query(SupplierLedgerEntry).filter(SupplierLedgerEntry.supplier_id == from_id).count()
        grn_c = db.query(GRN).filter(GRN.supplier_id == from_id).count()
        po_c = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == from_id).count()

        ob_c = db.query(DailyOrderBook).filter(DailyOrderBook.supplier_id == from_id).count()
        obh_c = db.query(OrderBookHistory).filter(OrderBookHistory.supplier_id == from_id).count()

        if inv_c or pay_c or ret_c or led_c or grn_c or po_c or ob_c or obh_c:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Merge reassignment did not fully clear references; cannot delete source supplier.",
                    "counts": {
                        "invoices": inv_c,
                        "payments": pay_c,
                        "returns": ret_c,
                        "ledger_entries": led_c,
                        "grns": grn_c,
                        "purchase_orders": po_c,
                        "daily_order_book": ob_c,
                        "order_book_history": obh_c,
                    },
                },
            )

        source = db.query(Supplier).filter(Supplier.id == from_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="Source supplier missing")

        db.delete(source)
        db.commit()

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "company_id": company_id,
        "from_supplier_id": from_id,
        "to_supplier_id": to_id,
        "deleted_source": True,
    }
