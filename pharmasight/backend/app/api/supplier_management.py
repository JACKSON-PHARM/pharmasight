"""
Supplier Management API: payments, allocations, returns, ledger, aging, metrics, statement.
company_id is resolved from session only (never from request body).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import func, and_, case
from sqlalchemy.orm import Session, selectinload

from app.dependencies import get_tenant_db, get_current_user, require_document_belongs_to_user_company
from app.models import (
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierReturn,
    SupplierReturnLine,
    SupplierLedgerEntry,
    InventoryLedger,
    Item,
    Branch,
    User,
)
from app.services.inventory_service import InventoryService
from app.services.snapshot_service import SnapshotService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.supplier_ledger_service import SupplierLedgerService
from app.schemas.supplier_management import (
    SupplierPaymentCreate,
    SupplierPaymentResponse,
    SupplierPaymentAllocationResponse,
    SupplierReturnCreate,
    SupplierReturnResponse,
    SupplierReturnLineResponse,
    SupplierLedgerEntryResponse,
    SupplierAgingRow,
    AgingReportResponse,
    SupplierMonthlyMetricsResponse,
    SupplierStatementResponse,
    SupplierStatementLine,
)

router = APIRouter()


def _effective_company_id(request: Request) -> UUID:
    """Resolve company_id from session only. Never from body."""
    cid = getattr(request.state, "effective_company_id", None)
    if not cid:
        raise HTTPException(status_code=403, detail="Company context required")
    return cid


# --- Enriched supplier list (for UI with balances) ---
@router.get("/enriched-list")
def list_suppliers_enriched(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    List all suppliers with outstanding, overdue, this_month_purchases.
    For suppliers list page with balance columns.
    """
    company_id = _effective_company_id(request)
    today = date.today()
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

    suppliers = db.query(Supplier).filter(
        Supplier.company_id == company_id,
        Supplier.is_active == True,
    ).order_by(Supplier.name.asc()).all()

    # Subquery: outstanding and overdue per supplier (from invoices)
    inv_q = db.query(
        SupplierInvoice.supplier_id,
        func.coalesce(func.sum(SupplierInvoice.balance), 0).label("outstanding"),
        func.coalesce(func.sum(
            case((and_(SupplierInvoice.due_date.isnot(None), SupplierInvoice.due_date < today), SupplierInvoice.balance), else_=0)
        ), 0).label("overdue"),
        func.coalesce(func.sum(
            case((and_(
                SupplierInvoice.invoice_date >= month_start,
                SupplierInvoice.invoice_date <= month_end,
                SupplierInvoice.status == "BATCHED",
            ), SupplierInvoice.total_inclusive), else_=0)
        ), 0).label("this_month"),
    ).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.status == "BATCHED",
    )
    if branch_id:
        inv_q = inv_q.filter(SupplierInvoice.branch_id == branch_id)
    inv_q = inv_q.group_by(SupplierInvoice.supplier_id)
    inv_rows = {str(r.supplier_id): r for r in inv_q.all()}

    result = []
    for s in suppliers:
        r = inv_rows.get(str(s.id))
        outstanding = Decimal(str(r.outstanding)) if r else Decimal("0")
        overdue = Decimal(str(r.overdue)) if r and r.overdue else Decimal("0")
        this_month = Decimal(str(r.this_month)) if r and r.this_month else Decimal("0")
        result.append({
            "id": str(s.id),
            "company_id": str(s.company_id),
            "name": s.name,
            "pin": s.pin,
            "contact_person": s.contact_person,
            "phone": s.phone,
            "email": s.email,
            "address": s.address,
            "credit_terms": s.credit_terms,
            "default_payment_terms_days": getattr(s, "default_payment_terms_days", None),
            "credit_limit": float(s.credit_limit) if getattr(s, "credit_limit", None) is not None else None,
            "allow_over_credit": getattr(s, "allow_over_credit", False) or False,
            "opening_balance": float(s.opening_balance) if getattr(s, "opening_balance", None) is not None else 0,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if hasattr(s.created_at, "isoformat") else str(s.created_at),
            "updated_at": s.updated_at.isoformat() if hasattr(s.updated_at, "isoformat") else str(s.updated_at),
            "outstanding_balance": float(outstanding),
            "overdue_amount": float(overdue),
            "this_month_purchases": float(this_month),
        })
    return result


# --- Payments ---
@router.post("/payments", response_model=SupplierPaymentResponse, status_code=status.HTTP_201_CREATED)
def create_supplier_payment(
    body: SupplierPaymentCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Create a supplier payment. If allocations are provided, allocates to invoices,
    updates invoice balances, and creates ledger credit entries. Prevents over-allocation.
    """
    company_id = _effective_company_id(request)
    user = current_user_and_db[0]

    # Validate supplier belongs to company
    supplier = db.query(Supplier).filter(
        Supplier.id == body.supplier_id,
        Supplier.company_id == company_id,
    ).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Validate branch
    branch = db.query(Branch).filter(
        Branch.id == body.branch_id,
        Branch.company_id == company_id,
    ).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    total_allocated = Decimal("0")
    allocations_by_invoice: Dict[UUID, Tuple[SupplierInvoice, Decimal]] = {}  # invoice_id -> (inv, total_alloc_to_this_inv)
    if body.allocations:
        for alloc in body.allocations:
            inv = db.query(SupplierInvoice).filter(
                SupplierInvoice.id == alloc.supplier_invoice_id,
                SupplierInvoice.company_id == company_id,
                SupplierInvoice.supplier_id == body.supplier_id,
            ).with_for_update().first()
            if not inv:
                raise HTTPException(
                    status_code=404,
                    detail=f"Invoice {alloc.supplier_invoice_id} not found or not for this supplier",
                )
            if inv.status != "BATCHED":
                raise HTTPException(
                    status_code=400,
                    detail=f"Invoice {inv.invoice_number} is not posted (BATCHED). Cannot allocate payment.",
                )
            balance = inv.balance if inv.balance is not None else (inv.total_inclusive or Decimal("0")) - (inv.amount_paid or Decimal("0"))
            existing = allocations_by_invoice.get(inv.id, (inv, Decimal("0")))[1]
            new_total_alloc = existing + alloc.allocated_amount
            if new_total_alloc > balance:
                raise HTTPException(
                    status_code=400,
                    detail=f"Allocation total ({new_total_alloc}) exceeds invoice balance {balance} for {inv.invoice_number}",
                )
            total_allocated += alloc.allocated_amount
            allocations_by_invoice[inv.id] = (inv, new_total_alloc)

    if body.allocations and total_allocated > body.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Total allocated ({total_allocated}) cannot exceed payment amount ({body.amount})",
        )

    try:
        payment = SupplierPayment(
            company_id=company_id,
            branch_id=body.branch_id,
            supplier_id=body.supplier_id,
            payment_date=body.payment_date,
            method=body.method,
            reference=body.reference,
            amount=body.amount,
            is_allocated=bool(allocations_to_create),
            created_by=user.id,
        )
        db.add(payment)
        db.flush()

        for inv, total_alloc in allocations_by_invoice.values():
            alloc_row = SupplierPaymentAllocation(
                supplier_payment_id=payment.id,
                supplier_invoice_id=inv.id,
                allocated_amount=total_alloc,
            )
            db.add(alloc_row)
            inv.amount_paid = (inv.amount_paid or Decimal("0")) + total_alloc
            inv.balance = (inv.total_inclusive or Decimal("0")) - inv.amount_paid
            if inv.balance <= 0:
                inv.payment_status = "PAID"
                inv.balance = Decimal("0")
            else:
                inv.payment_status = "PARTIAL"
        # Ledger: one credit entry = full payment amount
        SupplierLedgerService.create_entry(
            db,
            company_id=company_id,
            branch_id=body.branch_id,
            supplier_id=body.supplier_id,
            entry_date=body.payment_date,
            entry_type="payment",
            reference_id=payment.id,
            debit=Decimal("0"),
            credit=body.amount,
        )

        db.commit()
        db.refresh(payment)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    # Load relations for response
    payment = db.query(SupplierPayment).options(
        selectinload(SupplierPayment.allocations),
        selectinload(SupplierPayment.supplier),
        selectinload(SupplierPayment.branch),
    ).filter(SupplierPayment.id == payment.id).first()
    out = SupplierPaymentResponse(
        id=payment.id,
        company_id=payment.company_id,
        branch_id=payment.branch_id,
        supplier_id=payment.supplier_id,
        payment_date=payment.payment_date,
        method=payment.method,
        reference=payment.reference,
        amount=payment.amount,
        is_allocated=payment.is_allocated or False,
        created_by=payment.created_by,
        created_at=payment.created_at,
        allocations=[
            SupplierPaymentAllocationResponse(
                id=a.id,
                supplier_payment_id=a.supplier_payment_id,
                supplier_invoice_id=a.supplier_invoice_id,
                allocated_amount=a.allocated_amount,
                invoice_number=getattr(a.supplier_invoice, "invoice_number", None) if a.supplier_invoice else None,
                created_at=a.created_at,
            )
            for a in payment.allocations
        ],
        supplier_name=payment.supplier.name if payment.supplier else None,
        branch_name=payment.branch.name if payment.branch else None,
    )
    return out


@router.get("/payments", response_model=List[SupplierPaymentResponse])
def list_supplier_payments(
    request: Request,
    supplier_id: Optional[UUID] = Query(None),
    branch_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: Optional[int] = Query(100, ge=1, le=500),
    offset: Optional[int] = Query(0, ge=0),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """List supplier payments. company_id from session. Supports pagination."""
    company_id = _effective_company_id(request)
    q = db.query(SupplierPayment).filter(SupplierPayment.company_id == company_id)
    if supplier_id:
        q = q.filter(SupplierPayment.supplier_id == supplier_id)
    if branch_id:
        q = q.filter(SupplierPayment.branch_id == branch_id)
    if date_from:
        q = q.filter(SupplierPayment.payment_date >= date_from)
    if date_to:
        q = q.filter(SupplierPayment.payment_date <= date_to)
    payments = q.order_by(SupplierPayment.payment_date.desc()).offset(offset).limit(limit).options(
        selectinload(SupplierPayment.allocations).selectinload(SupplierPaymentAllocation.supplier_invoice),
        selectinload(SupplierPayment.supplier),
        selectinload(SupplierPayment.branch),
    ).all()
    return [
        SupplierPaymentResponse(
            id=p.id,
            company_id=p.company_id,
            branch_id=p.branch_id,
            supplier_id=p.supplier_id,
            payment_date=p.payment_date,
            method=p.method,
            reference=p.reference,
            amount=p.amount,
            is_allocated=p.is_allocated or False,
            created_by=p.created_by,
            created_at=p.created_at,
            allocations=[
                SupplierPaymentAllocationResponse(
                    id=a.id,
                    supplier_payment_id=a.supplier_payment_id,
                    supplier_invoice_id=a.supplier_invoice_id,
                    allocated_amount=a.allocated_amount,
                    invoice_number=getattr(a.supplier_invoice, "invoice_number", None) if getattr(a, "supplier_invoice", None) else None,
                    created_at=a.created_at,
                )
                for a in p.allocations
            ],
            supplier_name=p.supplier.name if p.supplier else None,
            branch_name=p.branch.name if p.branch else None,
        )
        for p in payments
    ]


# --- Returns ---
@router.post("/returns", response_model=SupplierReturnResponse, status_code=status.HTTP_201_CREATED)
def create_supplier_return(
    body: SupplierReturnCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Create a supplier return (pending). Stock is reduced when status is set to approved."""
    company_id = _effective_company_id(request)
    user = current_user_and_db[0]

    supplier = db.query(Supplier).filter(Supplier.id == body.supplier_id, Supplier.company_id == company_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    branch = db.query(Branch).filter(Branch.id == body.branch_id, Branch.company_id == company_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    total_value = sum(line.line_total for line in body.lines)
    ret = SupplierReturn(
        company_id=company_id,
        branch_id=body.branch_id,
        supplier_id=body.supplier_id,
        linked_invoice_id=body.linked_invoice_id,
        return_date=body.return_date,
        reason=body.reason,
        total_value=total_value,
        status="pending",
        created_by=user.id,
    )
    db.add(ret)
    db.flush()
    for line in body.lines:
        db.add(SupplierReturnLine(
            supplier_return_id=ret.id,
            item_id=line.item_id,
            batch_number=line.batch_number,
            expiry_date=line.expiry_date,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
            line_total=line.line_total,
        ))
    db.commit()
    db.refresh(ret)
    ret = db.query(SupplierReturn).options(
        selectinload(SupplierReturn.lines).selectinload(SupplierReturnLine.item),
        selectinload(SupplierReturn.supplier),
        selectinload(SupplierReturn.branch),
    ).filter(SupplierReturn.id == ret.id).first()
    return SupplierReturnResponse(
        id=ret.id,
        company_id=ret.company_id,
        branch_id=ret.branch_id,
        supplier_id=ret.supplier_id,
        linked_invoice_id=ret.linked_invoice_id,
        return_date=ret.return_date,
        reason=ret.reason,
        total_value=ret.total_value,
        status=ret.status,
        created_by=ret.created_by,
        created_at=ret.created_at,
        lines=[SupplierReturnLineResponse(
            id=l.id, supplier_return_id=l.supplier_return_id, item_id=l.item_id,
            batch_number=l.batch_number, expiry_date=l.expiry_date,
            quantity=l.quantity, unit_cost=l.unit_cost, line_total=l.line_total,
            item_name=l.item.name if l.item else None,
        ) for l in ret.lines],
        supplier_name=ret.supplier.name if ret.supplier else None,
        branch_name=ret.branch.name if ret.branch else None,
    )


@router.patch("/returns/{return_id}/approve", response_model=SupplierReturnResponse)
def approve_supplier_return(
    return_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Approve supplier return: reduce stock (InventoryLedger negative), create ledger credit,
    optionally adjust linked invoice balance. Prevents negative stock.
    """
    company_id = _effective_company_id(request)
    user = current_user_and_db[0]

    ret = db.query(SupplierReturn).options(
        selectinload(SupplierReturn.lines).selectinload(SupplierReturnLine.item),
        selectinload(SupplierReturn.supplier),
        selectinload(SupplierReturn.branch),
    ).filter(
        SupplierReturn.id == return_id,
        SupplierReturn.company_id == company_id,
    ).with_for_update().first()
    if not ret:
        raise HTTPException(status_code=404, detail="Return not found")
    if ret.status != "pending":
        raise HTTPException(status_code=400, detail=f"Return status is {ret.status}. Only pending can be approved.")

    # Check stock availability (quantity in return line = base units)
    for line in ret.lines:
        current = InventoryService.get_current_stock(db, line.item_id, ret.branch_id)
        if current < float(line.quantity):
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for item {line.item.name or line.item_id}. Available: {current}, return: {line.quantity}",
            )

    try:
        for line in ret.lines:
            # Negative ledger entry (reduction)
            entry = InventoryLedger(
                company_id=company_id,
                branch_id=ret.branch_id,
                item_id=line.item_id,
                batch_number=line.batch_number,
                expiry_date=line.expiry_date,
                transaction_type="PURCHASE",  # reversal
                reference_type="supplier_return",
                reference_id=ret.id,
                quantity_delta=-float(line.quantity),
                unit_cost=line.unit_cost,
                total_cost=line.unit_cost * line.quantity,
                created_by=user.id,
            )
            db.add(entry)
            SnapshotService.upsert_inventory_balance(
                db, company_id, ret.branch_id, line.item_id, Decimal(str(-float(line.quantity))),
            )
            SnapshotRefreshService.schedule_snapshot_refresh(db, company_id, ret.branch_id, item_id=line.item_id)

        # Ledger credit
        SupplierLedgerService.create_entry(
            db,
            company_id=company_id,
            branch_id=ret.branch_id,
            supplier_id=ret.supplier_id,
            entry_date=ret.return_date,
            entry_type="return",
            reference_id=ret.id,
            debit=Decimal("0"),
            credit=ret.total_value,
        )
        ret.status = "credited"
        db.commit()
        db.refresh(ret)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return SupplierReturnResponse(
        id=ret.id,
        company_id=ret.company_id,
        branch_id=ret.branch_id,
        supplier_id=ret.supplier_id,
        linked_invoice_id=ret.linked_invoice_id,
        return_date=ret.return_date,
        reason=ret.reason,
        total_value=ret.total_value,
        status=ret.status,
        created_by=ret.created_by,
        created_at=ret.created_at,
        lines=[SupplierReturnLineResponse(
            id=l.id, supplier_return_id=l.supplier_return_id, item_id=l.item_id,
            batch_number=l.batch_number, expiry_date=l.expiry_date,
            quantity=l.quantity, unit_cost=l.unit_cost, line_total=l.line_total,
            item_name=l.item.name if l.item else None,
        ) for l in ret.lines],
        supplier_name=ret.supplier.name if ret.supplier else None,
        branch_name=ret.branch.name if ret.branch else None,
    )


@router.get("/returns", response_model=List[SupplierReturnResponse])
def list_supplier_returns(
    request: Request,
    supplier_id: Optional[UUID] = Query(None),
    branch_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: Optional[int] = Query(100, ge=1, le=500),
    offset: Optional[int] = Query(0, ge=0),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    q = db.query(SupplierReturn).filter(SupplierReturn.company_id == company_id)
    if supplier_id:
        q = q.filter(SupplierReturn.supplier_id == supplier_id)
    if branch_id:
        q = q.filter(SupplierReturn.branch_id == branch_id)
    if status_filter:
        q = q.filter(SupplierReturn.status == status_filter)
    returns = q.order_by(SupplierReturn.return_date.desc()).offset(offset).limit(limit).options(
        selectinload(SupplierReturn.lines).selectinload(SupplierReturnLine.item),
        selectinload(SupplierReturn.supplier),
        selectinload(SupplierReturn.branch),
    ).all()
    return [
        SupplierReturnResponse(
            id=r.id, company_id=r.company_id, branch_id=r.branch_id, supplier_id=r.supplier_id,
            linked_invoice_id=r.linked_invoice_id, return_date=r.return_date, reason=r.reason,
            total_value=r.total_value, status=r.status, created_by=r.created_by, created_at=r.created_at,
            lines=[SupplierReturnLineResponse(
                id=l.id, supplier_return_id=l.supplier_return_id, item_id=l.item_id,
                batch_number=l.batch_number, expiry_date=l.expiry_date,
                quantity=l.quantity, unit_cost=l.unit_cost, line_total=l.line_total,
                item_name=l.item.name if l.item else None,
            ) for l in r.lines],
            supplier_name=r.supplier.name if r.supplier else None,
            branch_name=r.branch.name if r.branch else None,
        )
        for r in returns
    ]


# --- Ledger ---
@router.get("/ledger", response_model=List[SupplierLedgerEntryResponse])
def list_supplier_ledger(
    request: Request,
    supplier_id: UUID = Query(...),
    branch_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: Optional[int] = Query(200, ge=1, le=1000),
    offset: Optional[int] = Query(0, ge=0),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    q = db.query(SupplierLedgerEntry).filter(
        SupplierLedgerEntry.company_id == company_id,
        SupplierLedgerEntry.supplier_id == supplier_id,
    )
    if branch_id:
        q = q.filter(SupplierLedgerEntry.branch_id == branch_id)
    if date_from:
        q = q.filter(SupplierLedgerEntry.date >= date_from)
    if date_to:
        q = q.filter(SupplierLedgerEntry.date <= date_to)
    entries = q.order_by(SupplierLedgerEntry.date.asc(), SupplierLedgerEntry.created_at.asc()).offset(offset).limit(limit).all()
    return [
        SupplierLedgerEntryResponse(
            id=e.id, company_id=e.company_id, branch_id=e.branch_id, supplier_id=e.supplier_id,
            date=e.date, entry_type=e.entry_type, reference_id=e.reference_id,
            debit=e.debit, credit=e.credit, running_balance=e.running_balance, created_at=e.created_at,
        )
        for e in entries
    ]


# --- Aging ---
@router.get("/reports/aging", response_model=AgingReportResponse)
def get_supplier_aging_report(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    as_of_date: Optional[date] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Aging buckets: 0-30, 31-60, 61-90, 90+ days overdue. Based on invoice due_date and balance."""
    company_id = _effective_company_id(request)
    as_of = as_of_date or date.today()

    # Invoices with balance > 0; due_date for aging buckets
    b0_30_case = case(
        (SupplierInvoice.due_date.is_(None), SupplierInvoice.balance),
        (SupplierInvoice.due_date >= as_of - timedelta(days=30), SupplierInvoice.balance),
        else_=0,
    )
    b31_60_case = case(
        (and_(
            SupplierInvoice.due_date >= as_of - timedelta(days=60),
            SupplierInvoice.due_date < as_of - timedelta(days=30),
        ), SupplierInvoice.balance),
        else_=0,
    )
    b61_90_case = case(
        (and_(
            SupplierInvoice.due_date >= as_of - timedelta(days=90),
            SupplierInvoice.due_date < as_of - timedelta(days=60),
        ), SupplierInvoice.balance),
        else_=0,
    )
    b90_plus_case = case(
        (SupplierInvoice.due_date < as_of - timedelta(days=90), SupplierInvoice.balance),
        else_=0,
    )
    overdue_case = case(
        (SupplierInvoice.due_date < as_of, SupplierInvoice.balance),
        else_=0,
    )
    q = db.query(
        SupplierInvoice.supplier_id,
        Supplier.name.label("supplier_name"),
        func.coalesce(func.sum(SupplierInvoice.balance), 0).label("total_outstanding"),
        func.coalesce(func.sum(b0_30_case), 0).label("b0_30"),
        func.coalesce(func.sum(b31_60_case), 0).label("b31_60"),
        func.coalesce(func.sum(b61_90_case), 0).label("b61_90"),
        func.coalesce(func.sum(b90_plus_case), 0).label("b90_plus"),
        func.coalesce(func.sum(overdue_case), 0).label("overdue"),
    ).join(Supplier, Supplier.id == SupplierInvoice.supplier_id).filter(
        SupplierInvoice.company_id == company_id,
        (SupplierInvoice.balance.is_(None) | (SupplierInvoice.balance > 0)),
        SupplierInvoice.status == "BATCHED",
    )
    if branch_id:
        q = q.filter(SupplierInvoice.branch_id == branch_id)
    q = q.group_by(SupplierInvoice.supplier_id, Supplier.name)
    rows = q.all()

    # Build response: one row per supplier with outstanding
    suppliers_list = []
    for r in rows:
        total = r.total_outstanding or Decimal("0")
        if total <= 0:
            continue
        b0_30 = r.b0_30 or Decimal("0")
        b31_60 = r.b31_60 or Decimal("0")
        b61_90 = r.b61_90 or Decimal("0")
        b90_plus = r.b90_plus or Decimal("0")
        overdue = r.overdue or Decimal("0")
        suppliers_list.append(SupplierAgingRow(
            supplier_id=r.supplier_id,
            supplier_name=r.supplier_name or "",
            total_outstanding=total,
            bucket_0_30=b0_30,
            bucket_31_60=b31_60,
            bucket_61_90=b61_90,
            bucket_90_plus=b90_plus,
            overdue_amount=overdue,
        ))

    total_out = sum(s.total_outstanding for s in suppliers_list)
    return AgingReportResponse(
        as_of_date=as_of,
        branch_id=branch_id,
        suppliers=suppliers_list,
        totals=AgingBucket(bucket="total", amount=total_out, count=len(suppliers_list)),
    )


# --- Monthly metrics ---
@router.get("/reports/metrics", response_model=SupplierMonthlyMetricsResponse)
def get_supplier_monthly_metrics(
    request: Request,
    month: str = Query(..., description="YYYY-MM"),
    branch_id: Optional[UUID] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    try:
        year, m = int(month[:4]), int(month[5:7])
        start = date(year, m, 1)
        if m == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, m + 1, 1) - timedelta(days=1)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    # Total purchases (invoices posted in month)
    q_inv = db.query(func.coalesce(func.sum(SupplierInvoice.total_inclusive), 0)).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.status == "BATCHED",
        SupplierInvoice.invoice_date >= start,
        SupplierInvoice.invoice_date <= end,
    )
    if branch_id:
        q_inv = q_inv.filter(SupplierInvoice.branch_id == branch_id)
    total_purchases = q_inv.scalar() or Decimal("0")

    # Total payments in month
    q_pay = db.query(func.coalesce(func.sum(SupplierPayment.amount), 0)).filter(
        SupplierPayment.company_id == company_id,
        SupplierPayment.payment_date >= start,
        SupplierPayment.payment_date <= end,
    )
    if branch_id:
        q_pay = q_pay.filter(SupplierPayment.branch_id == branch_id)
    total_payments = q_pay.scalar() or Decimal("0")

    # Total returns (credited) in month
    q_ret = db.query(func.coalesce(func.sum(SupplierReturn.total_value), 0)).filter(
        SupplierReturn.company_id == company_id,
        SupplierReturn.status == "credited",
        SupplierReturn.return_date >= start,
        SupplierReturn.return_date <= end,
    )
    if branch_id:
        q_ret = q_ret.filter(SupplierReturn.branch_id == branch_id)
    total_returns = q_ret.scalar() or Decimal("0")

    # Net outstanding: sum of ledger (debit - credit) as at end of month
    # Simplified: sum invoice balances for BATCHED invoices that exist as of end date
    q_bal = db.query(func.coalesce(func.sum(SupplierInvoice.balance), 0)).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.status == "BATCHED",
        SupplierInvoice.invoice_date <= end,
    )
    if branch_id:
        q_bal = q_bal.filter(SupplierInvoice.branch_id == branch_id)
    net_outstanding = q_bal.scalar() or Decimal("0")

    # Overdue: invoices with due_date < end and balance > 0
    q_over = db.query(func.coalesce(func.sum(SupplierInvoice.balance), 0)).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.status == "BATCHED",
        SupplierInvoice.due_date.isnot(None),
        SupplierInvoice.due_date < end,
        SupplierInvoice.balance > 0,
    )
    if branch_id:
        q_over = q_over.filter(SupplierInvoice.branch_id == branch_id)
    overdue_amount = q_over.scalar() or Decimal("0")

    # Top suppliers by purchase value in month
    top_q = db.query(
        SupplierInvoice.supplier_id,
        Supplier.name,
        func.sum(SupplierInvoice.total_inclusive).label("total"),
    ).join(Supplier, Supplier.id == SupplierInvoice.supplier_id).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.status == "BATCHED",
        SupplierInvoice.invoice_date >= start,
        SupplierInvoice.invoice_date <= end,
    )
    if branch_id:
        top_q = top_q.filter(SupplierInvoice.branch_id == branch_id)
    top_q = top_q.group_by(SupplierInvoice.supplier_id, Supplier.name).order_by(func.sum(SupplierInvoice.total_inclusive).desc()).limit(10)
    top_suppliers = [{"supplier_id": str(r.supplier_id), "name": r.name, "total": float(r.total)} for r in top_q.all()]

    # Average payment days: (payment_date - invoice_date) for allocated payments (simplified: skip if no allocations)
    avg_days = None
    pay_inv_q = db.query(
        SupplierPayment.payment_date,
        SupplierInvoice.invoice_date,
    ).join(SupplierPaymentAllocation, SupplierPaymentAllocation.supplier_payment_id == SupplierPayment.id).join(
        SupplierInvoice, SupplierInvoice.id == SupplierPaymentAllocation.supplier_invoice_id,
    ).filter(
        SupplierPayment.company_id == company_id,
        SupplierPayment.payment_date >= start,
        SupplierPayment.payment_date <= end,
    )
    if branch_id:
        pay_inv_q = pay_inv_q.filter(SupplierPayment.branch_id == branch_id)
    pay_inv_rows = pay_inv_q.all()
    if pay_inv_rows:
        days_list = [(r.payment_date - r.invoice_date).days for r in pay_inv_rows if r.invoice_date]
        if days_list:
            avg_days = sum(days_list) / len(days_list)

    return SupplierMonthlyMetricsResponse(
        month=month,
        company_id=company_id,
        branch_id=branch_id,
        total_purchases=total_purchases,
        total_payments=total_payments,
        total_returns=total_returns,
        net_outstanding=net_outstanding,
        overdue_amount=overdue_amount,
        top_suppliers_by_purchase=top_suppliers,
        average_payment_days=avg_days,
    )


# --- Statement (printable) ---
@router.get("/statement", response_model=SupplierStatementResponse)
def get_supplier_statement(
    request: Request,
    supplier_id: UUID = Query(...),
    branch_id: Optional[UUID] = Query(None),
    from_date: date = Query(...),
    to_date: date = Query(...),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Supplier statement: ledger lines with running balance. For printable view."""
    company_id = _effective_company_id(request)
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.company_id == company_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    entries = db.query(SupplierLedgerEntry).filter(
        SupplierLedgerEntry.company_id == company_id,
        SupplierLedgerEntry.supplier_id == supplier_id,
        SupplierLedgerEntry.date >= from_date,
        SupplierLedgerEntry.date <= to_date,
    )
    if branch_id:
        entries = entries.filter(SupplierLedgerEntry.branch_id == branch_id)
    entries = entries.order_by(SupplierLedgerEntry.date.asc(), SupplierLedgerEntry.created_at.asc()).all()

    # Opening balance: sum of entries before from_date
    opening_q = db.query(
        func.coalesce(func.sum(SupplierLedgerEntry.debit), 0) - func.coalesce(func.sum(SupplierLedgerEntry.credit), 0),
    ).filter(
        SupplierLedgerEntry.company_id == company_id,
        SupplierLedgerEntry.supplier_id == supplier_id,
        SupplierLedgerEntry.date < from_date,
    )
    if branch_id:
        opening_q = opening_q.filter(SupplierLedgerEntry.branch_id == branch_id)
    opening_balance = opening_q.scalar() or Decimal("0")

    lines = []
    running = opening_balance
    for e in entries:
        running = running + e.debit - e.credit
        desc = e.entry_type
        if e.entry_type == "invoice":
            desc = "Invoice"
        elif e.entry_type == "payment":
            desc = "Payment"
        elif e.entry_type == "return":
            desc = "Return"
        elif e.entry_type == "adjustment":
            desc = "Adjustment"
        elif e.entry_type == "opening_balance":
            desc = "Opening balance"
        lines.append(SupplierStatementLine(
            date=e.date,
            description=desc,
            reference=str(e.reference_id) if e.reference_id else None,
            debit=e.debit,
            credit=e.credit,
            balance=running,
        ))
    closing_balance = running

    branch_name = None
    if branch_id:
        b = db.query(Branch).filter(Branch.id == branch_id, Branch.company_id == company_id).first()
        branch_name = b.name if b else None

    return SupplierStatementResponse(
        supplier_id=supplier_id,
        supplier_name=supplier.name,
        branch_id=branch_id,
        branch_name=branch_name,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        lines=lines,
    )
