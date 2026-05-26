"""
Wholesale customers API (B2B master data)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, or_, and_
from typing import List
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.dependencies import get_tenant_db, get_current_user
from app.utils.customer_access import (
    customer_hub_sales_type_clause,
    get_customer_hub_mode,
    require_customer_hub_branch,
)
from app.models import (
    Customer,
    SalesInvoice,
    SalesInvoiceItem,
    CustomerPayment,
    CustomerLedgerEntry,
    Quotation,
    CustomerActivity,
    CustomerUser,
)
from app.schemas.customer import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerMergeRequest,
)

router = APIRouter(dependencies=[Depends(require_customer_hub_branch())])


@router.get("/search")
def search_customers(
    q: str = Query(..., min_length=2),
    company_id: UUID = Query(...),
    limit: int = Query(10, ge=1, le=20),
    mode=Depends(get_customer_hub_mode),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    search_term = f"%{q.lower()}%"
    rows = (
        db.query(
            Customer.id,
            Customer.name,
            Customer.pin,
            Customer.phone,
            Customer.contact_person,
            Customer.default_sales_type,
        )
        .filter(
            Customer.company_id == company_id,
            Customer.is_active == True,
            customer_hub_sales_type_clause(mode),
            or_(
                func.lower(Customer.name).like(search_term),
                func.lower(Customer.contact_person).like(search_term),
                func.lower(Customer.phone).like(search_term),
            ),
        )
        .order_by(Customer.name.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "pin": r.pin,
            "phone": r.phone,
            "contact_person": r.contact_person,
            "default_sales_type": r.default_sales_type,
        }
        for r in rows
    ]


@router.get("/company/{company_id}", response_model=List[CustomerResponse])
def list_customers(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    return (
        db.query(Customer)
        .filter(Customer.company_id == company_id, Customer.is_active == True)
        .order_by(Customer.name)
        .all()
    )


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    customer: CustomerCreate,
    mode=Depends(get_customer_hub_mode),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    name_key = (customer.name or "").strip().lower()
    if name_key:
        dup = (
            db.query(Customer)
            .filter(
                Customer.company_id == customer.company_id,
                func.lower(func.trim(Customer.name)) == name_key,
            )
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A customer named '{dup.name}' already exists for this company.",
            )

    db_customer = Customer(
        company_id=customer.company_id,
        name=customer.name,
        pin=customer.pin,
        contact_person=customer.contact_person,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        city=customer.city,
        county=customer.county,
        customer_type=customer.customer_type or "PHARMACY",
        default_payment_terms_days=customer.default_payment_terms_days,
        credit_limit=customer.credit_limit,
        allow_over_credit=customer.allow_over_credit or False,
        credit_enabled=customer.credit_enabled if customer.credit_enabled is not None else True,
        default_sales_type=customer.default_sales_type or default_sales_type_for_hub_mode(mode),
        opening_balance=customer.opening_balance or 0,
        notes=customer.notes,
        portal_enabled=bool(customer.portal_enabled),
    )
    db.add(db_customer)
    db.flush()
    from app.services.customer_opening_balance import ensure_opening_balance_ledger_entry

    ensure_opening_balance_ledger_entry(db, customer=db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


@router.get("/{customer_id}/portal-users")
def list_customer_portal_users(
    customer_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Phase 5 foundation: list B2B portal identities for a customer.
  Full invite/login flows are not implemented yet.
    """
    effective = getattr(request.state, "effective_company_id", None)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if effective is not None and customer.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    rows = (
        db.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer_id, CustomerUser.company_id == customer.company_id)
        .order_by(CustomerUser.email.asc())
        .all()
    )
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "is_active": u.is_active,
            "portal_enabled": customer.portal_enabled,
            "invited_at": u.invited_at.isoformat() if u.invited_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "auth_user_id": str(u.auth_user_id) if u.auth_user_id else None,
        }
        for u in rows
    ]


def _sales_invoice_balance_sort_key(inv: SalesInvoice) -> Decimal:
    b = getattr(inv, "balance", None)
    if b is None:
        return Decimal("0")
    return Decimal(str(b))


def _invoice_is_effectively_open(inv: SalesInvoice, tol: Decimal = Decimal("0.01")) -> bool:
    """True if customer still owes on this invoice (after reconciliation)."""
    ps = (getattr(inv, "payment_status", None) or "").strip().upper()
    if ps in ("UNPAID", "PARTIAL"):
        return True
    bal = getattr(inv, "balance", None)
    if bal is None:
        return False
    return Decimal(str(bal)) > tol


@router.get("/{customer_id}/invoices")
def list_customer_sales_invoices(
    customer_id: UUID,
    request: Request,
    branch_id: UUID | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Posted invoices for customer profile / refills.

    Prioritizes open (unpaid / partial / positive balance) rows first:
    sorted by outstanding balance descending, then invoice_date descending,
    then merges recent settled invoices up to ``limit``.
    """
    effective = getattr(request.state, "effective_company_id", None)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if effective is not None and customer.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")
    match_filters = [SalesInvoice.customer_id == customer_id]
    if customer.pin:
        match_filters.append(SalesInvoice.customer_pin == customer.pin)
    if customer.phone:
        match_filters.append(SalesInvoice.customer_phone == customer.phone)
    if customer.name:
        match_filters.append(func.lower(SalesInvoice.customer_name) == customer.name.strip().lower())

    q = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(
            or_(*match_filters),
            SalesInvoice.company_id == customer.company_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
        )
    )
    if branch_id:
        q = q.filter(SalesInvoice.branch_id == branch_id)

    ps_upper = func.upper(func.coalesce(SalesInvoice.payment_status, ""))
    bal_expr = func.coalesce(SalesInvoice.balance, 0)

    # Candidates likely to have arrears (not “fully settled” on row alone).
    open_q = q.filter(
        or_(
            ps_upper.in_(["UNPAID", "PARTIAL"]),
            bal_expr > Decimal("0.01"),
            and_(SalesInvoice.balance.is_(None), ps_upper != "PAID"),
        )
    ).order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.created_at.desc())

    open_candidates = open_q.limit(400).all()

    open_ids = [i.id for i in open_candidates]
    settled_q = q.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.created_at.desc())
    if open_ids:
        settled_q = settled_q.filter(~SalesInvoice.id.in_(open_ids))

    from app.services.customer_invoice_payment_service import reconcile_customer_ar_for_invoice

    invoices_merged: list[SalesInvoice] = []
    seen: set[str] = set()

    if open_candidates:
        for inv in open_candidates:
            if inv.customer_id:
                reconcile_customer_ar_for_invoice(db, inv)
        if open_candidates:
            db.commit()
        for inv in open_candidates:
            db.refresh(inv)
        open_rows = [i for i in open_candidates if _invoice_is_effectively_open(i)]
        open_rows.sort(
            key=lambda i: (-_sales_invoice_balance_sort_key(i), -(i.invoice_date or date.min).toordinal()),
        )
        seen = {str(i.id) for i in open_rows}
        invoices_merged.extend(open_rows[:limit])
        seen.update(str(i.id) for i in open_rows[:limit])

    need = limit - len(invoices_merged)
    settled_rows: list[SalesInvoice] = []
    if need > 0:
        settled_rows = settled_q.limit(need + 50).all()  # small buffer after reconcile trimming
        for inv in settled_rows:
            if inv.customer_id:
                reconcile_customer_ar_for_invoice(db, inv)
        if settled_rows:
            db.commit()
        for inv in settled_rows:
            db.refresh(inv)
        # Prefer still-recent invoices that ended up settled; skip any that are actually open now.
        for inv in settled_rows:
            if str(inv.id) in seen:
                continue
            if _invoice_is_effectively_open(inv):
                continue
            invoices_merged.append(inv)
            seen.add(str(inv.id))
            if len(invoices_merged) >= limit:
                break

    # Fallback: fewer than ``limit`` invoices total for customer.
    if len(invoices_merged) == 0 and not open_candidates:
        fallback = (
            q.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.created_at.desc())
            .limit(limit)
            .all()
        )
        for inv in fallback:
            if inv.customer_id:
                reconcile_customer_ar_for_invoice(db, inv)
        if fallback:
            db.commit()
        for inv in fallback:
            db.refresh(inv)
        invoices_merged = fallback

    invoices = invoices_merged[:limit]

    return [
        {
            "id": str(inv.id),
            "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "status": inv.status,
            "payment_status": inv.payment_status,
            "payment_mode": inv.payment_mode,
            "total_inclusive": float(inv.total_inclusive or 0),
            "balance": float(inv.balance or 0),
            "item_count": len(inv.items or []),
            "items": [
                {
                    "item_id": str(line.item_id),
                    "item_name": line.item_name or (line.item.name if line.item else ""),
                    "unit_name": line.unit_name,
                    "quantity": float(line.quantity or 0),
                    "unit_price_exclusive": float(line.unit_price_exclusive or 0),
                    "line_total_inclusive": float(line.line_total_inclusive or 0),
                }
                for line in (inv.items or [])[:8]
            ],
        }
        for inv in invoices
    ]


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: UUID,
    customer: CustomerUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    db_customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    data = customer.model_dump(exclude_unset=True)
    for key, value in data.items():
        if hasattr(db_customer, key):
            setattr(db_customer, key, value)
    db.flush()
    if "opening_balance" in data:
        from app.services.customer_opening_balance import ensure_opening_balance_ledger_entry

        ensure_opening_balance_ledger_entry(db, customer=db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: UUID,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    effective = getattr(request.state, "effective_company_id", None)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if effective is not None and customer.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    inv_c = db.query(SalesInvoice).filter(SalesInvoice.customer_id == customer_id).count()
    pay_c = db.query(CustomerPayment).filter(CustomerPayment.customer_id == customer_id).count()
    led_c = db.query(CustomerLedgerEntry).filter(CustomerLedgerEntry.customer_id == customer_id).count()
    quo_c = db.query(Quotation).filter(Quotation.customer_id == customer_id).count()
    act_c = db.query(CustomerActivity).filter(CustomerActivity.customer_id == customer_id).count()

    if inv_c or pay_c or led_c or quo_c or act_c:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This customer has related documents.",
                "counts": {
                    "invoices": inv_c,
                    "payments": pay_c,
                    "ledger_entries": led_c,
                    "quotations": quo_c,
                    "activities": act_c,
                },
            },
        )

    db.delete(customer)
    db.commit()
    return None


@router.post("/merge")
def merge_customers(
    request: Request,
    merge: CustomerMergeRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    effective = getattr(request.state, "effective_company_id", None)
    from_id = merge.from_customer_id
    to_id = merge.to_customer_id
    if str(from_id) == str(to_id):
        raise HTTPException(status_code=400, detail="Cannot merge a customer into itself")

    from_c = db.query(Customer).filter(Customer.id == from_id).first()
    to_c = db.query(Customer).filter(Customer.id == to_id).first()
    if not from_c or not to_c:
        raise HTTPException(status_code=404, detail="Customer not found")
    if from_c.company_id != to_c.company_id:
        raise HTTPException(status_code=400, detail="Customers must belong to the same company")
    if effective is not None and from_c.company_id != effective:
        raise HTTPException(status_code=403, detail="Not allowed for this company")

    try:
        db.query(SalesInvoice).filter(SalesInvoice.customer_id == from_id).update(
            {SalesInvoice.customer_id: to_id}, synchronize_session=False
        )
        db.query(Quotation).filter(Quotation.customer_id == from_id).update(
            {Quotation.customer_id: to_id}, synchronize_session=False
        )
        db.query(CustomerPayment).filter(CustomerPayment.customer_id == from_id).update(
            {CustomerPayment.customer_id: to_id}, synchronize_session=False
        )
        db.query(CustomerLedgerEntry).filter(CustomerLedgerEntry.customer_id == from_id).update(
            {CustomerLedgerEntry.customer_id: to_id, CustomerLedgerEntry.running_balance: None},
            synchronize_session=False,
        )
        db.query(CustomerActivity).filter(CustomerActivity.customer_id == from_id).update(
            {CustomerActivity.customer_id: to_id}, synchronize_session=False
        )
        db.delete(from_c)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "company_id": str(from_c.company_id),
        "from_customer_id": str(from_id),
        "to_customer_id": str(to_id),
        "deleted_source": True,
    }
