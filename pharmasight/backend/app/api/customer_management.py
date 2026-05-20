"""
Customer management API: AR payments, ledger, aging, statement, CRM activities.
company_id from session only.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, List, Optional, Dict, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import Response
from sqlalchemy import func, and_, case
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import literal_column

from app.dependencies import get_tenant_db, get_current_user, get_tenant_optional, _user_has_permission, ensure_user_has_branch_access
from app.finance.governance.access import guard_finance_branch_query_param
from app.finance.governance.classification import MANAGEMENT
from app.models import (
    Customer,
    SalesInvoice,
    CustomerPayment,
    CustomerPaymentAllocation,
    CustomerLedgerEntry,
    CustomerActivity,
    Branch,
    Company,
    User,
)
from app.services.customer_ledger_service import CustomerLedgerService
from app.services.customer_invoice_payment_service import (
    prepare_customer_invoice_for_response,
    outstanding_after_settlements,
)
from app.services.cashbook_service import ensure_cashbook_entry_for_customer_payment
from app.schemas.customer_management import (
    CustomerPaymentCreate,
    CustomerPaymentResponse,
    CustomerPaymentAllocationResponse,
    CustomerLedgerEntryResponse,
    CustomerAgingRow,
    AgingBucket,
    CustomerAgingReportResponse,
    CustomerStatementResponse,
    CustomerStatementLine,
    CustomerStatementIntegrity,
    CustomerActivityCreate,
    CustomerActivityUpdate,
    CustomerActivityResponse,
    CustomerAnalyticsResponse,
)

from app.utils.customer_access import (
    customer_hub_sales_type_clause,
    get_customer_hub_mode,
    require_customer_hub_branch,
)
from app.services.customer_statement_service import (
    StatementBuildContext,
    build_operational_customer_statement,
)
from app.services.document_pdf_generator import build_customer_statement_pdf

router = APIRouter(dependencies=[Depends(require_customer_hub_branch())])


def _effective_company_id(request: Request) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if not cid:
        raise HTTPException(status_code=403, detail="Company context required")
    return cid


def _sales_invoice_effective_due_sql():
    days = func.coalesce(Customer.default_payment_terms_days, 0)
    return func.coalesce(
        SalesInvoice.due_date,
        SalesInvoice.invoice_date + days * literal_column("interval '1 day'"),
    )


@router.get("/enriched-list")
def list_customers_enriched(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    mode=Depends(get_customer_hub_mode),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    today = date.today()
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

    customers = (
        db.query(Customer)
        .filter(
            Customer.company_id == company_id,
            Customer.is_active == True,
            customer_hub_sales_type_clause(mode),
        )
        .order_by(Customer.name.asc())
        .all()
    )

    eff_due = _sales_invoice_effective_due_sql()
    overdue_case = case(
        (and_(eff_due < today, SalesInvoice.balance > 0), SalesInvoice.balance),
        else_=0,
    )
    inv_q = db.query(
        SalesInvoice.customer_id,
        func.coalesce(func.sum(SalesInvoice.balance), 0).label("outstanding"),
        func.coalesce(func.sum(overdue_case), 0).label("overdue"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            SalesInvoice.invoice_date >= month_start,
                            SalesInvoice.invoice_date <= month_end,
                            SalesInvoice.status.in_(["BATCHED", "PAID"]),
                        ),
                        SalesInvoice.total_inclusive,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("this_month"),
    ).join(Customer, Customer.id == SalesInvoice.customer_id).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.customer_id.isnot(None),
        SalesInvoice.status.in_(["BATCHED", "PAID"]),
    )
    if branch_id:
        inv_q = inv_q.filter(SalesInvoice.branch_id == branch_id)
    inv_q = inv_q.group_by(SalesInvoice.customer_id)
    inv_rows = {str(r.customer_id): r for r in inv_q.all() if r.customer_id}

    result = []
    for c in customers:
        r = inv_rows.get(str(c.id))
        outstanding = Decimal(str(r.outstanding)) if r else Decimal("0")
        overdue = Decimal(str(r.overdue)) if r and r.overdue else Decimal("0")
        this_month = Decimal(str(r.this_month)) if r and r.this_month else Decimal("0")
        result.append({
            "id": str(c.id),
            "company_id": str(c.company_id),
            "name": c.name,
            "pin": c.pin,
            "contact_person": c.contact_person,
            "phone": c.phone,
            "email": c.email,
            "address": c.address,
            "city": c.city,
            "county": c.county,
            "customer_type": c.customer_type,
            "default_payment_terms_days": c.default_payment_terms_days,
            "credit_limit": float(c.credit_limit) if c.credit_limit is not None else None,
            "allow_over_credit": c.allow_over_credit or False,
            "credit_enabled": c.credit_enabled if c.credit_enabled is not None else True,
            "default_sales_type": c.default_sales_type,
            "opening_balance": float(c.opening_balance) if c.opening_balance is not None else 0,
            "notes": c.notes,
            "portal_enabled": c.portal_enabled or False,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "outstanding_balance": float(outstanding),
            "overdue_amount": float(overdue),
            "this_month_sales": float(this_month),
        })
    result.sort(
        key=lambda r: (-float(r["overdue_amount"]), -float(r["outstanding_balance"]), (r["name"] or "").lower()),
    )
    return result


@router.post("/payments", response_model=CustomerPaymentResponse, status_code=status.HTTP_201_CREATED)
def create_customer_payment(
    body: CustomerPaymentCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    user = current_user_and_db[0]

    customer = db.query(Customer).filter(
        Customer.id == body.customer_id, Customer.company_id == company_id
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    branch = db.query(Branch).filter(Branch.id == body.branch_id, Branch.company_id == company_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    total_allocated = Decimal("0")
    allocations_by_invoice: Dict[UUID, Tuple[SalesInvoice, Decimal]] = {}
    q2 = Decimal("0.01")

    if body.allocations:
        for alloc in body.allocations:
            inv = (
                db.query(SalesInvoice)
                .filter(
                    SalesInvoice.id == alloc.sales_invoice_id,
                    SalesInvoice.company_id == company_id,
                    SalesInvoice.customer_id == body.customer_id,
                )
                .with_for_update()
                .first()
            )
            if not inv:
                raise HTTPException(status_code=404, detail=f"Invoice {alloc.sales_invoice_id} not found for customer")
            if inv.status not in ("BATCHED", "PAID"):
                raise HTTPException(status_code=400, detail=f"Invoice {inv.invoice_no} is not posted")
            outstanding = outstanding_after_settlements(db, inv).quantize(q2, rounding=ROUND_HALF_UP)
            existing = allocations_by_invoice.get(inv.id, (inv, Decimal("0")))[1]
            new_total = (existing + alloc.allocated_amount).quantize(q2, rounding=ROUND_HALF_UP)
            if new_total > outstanding:
                raise HTTPException(
                    status_code=400,
                    detail=f"Allocation exceeds balance for {inv.invoice_no}",
                )
            total_allocated += alloc.allocated_amount
            allocations_by_invoice[inv.id] = (inv, new_total)

    if body.allocations and total_allocated.quantize(q2, rounding=ROUND_HALF_UP) > body.amount.quantize(
        q2, rounding=ROUND_HALF_UP
    ):
        raise HTTPException(status_code=400, detail="Total allocated exceeds payment amount")

    try:
        payment = CustomerPayment(
            company_id=company_id,
            branch_id=body.branch_id,
            customer_id=body.customer_id,
            payment_date=body.payment_date,
            method=body.method,
            reference=body.reference,
            amount=body.amount,
            is_allocated=bool(allocations_by_invoice),
            created_by=user.id,
        )
        db.add(payment)
        db.flush()

        for inv, total_alloc in allocations_by_invoice.values():
            db.add(
                CustomerPaymentAllocation(
                    customer_payment_id=payment.id,
                    sales_invoice_id=inv.id,
                    allocated_amount=total_alloc,
                )
            )
        db.flush()
        for inv_id in allocations_by_invoice.keys():
            inv_row = db.query(SalesInvoice).with_for_update().filter(SalesInvoice.id == inv_id).first()
            if inv_row:
                prepare_customer_invoice_for_response(db, inv_row)

        CustomerLedgerService.create_entry(
            db,
            company_id=company_id,
            branch_id=body.branch_id,
            customer_id=body.customer_id,
            entry_date=body.payment_date,
            entry_type="payment",
            reference_id=payment.id,
            debit=Decimal("0"),
            credit=body.amount,
        )
        ensure_cashbook_entry_for_customer_payment(db, payment=payment)

        try:
            from app.accounting.posting.customer_payment import post_gl_for_customer_payment

            post_gl_for_customer_payment(db, payment, posted_by=user.id)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "accounting: GL customer payment failed for payment %s (non-fatal)",
                payment.id,
            )

        db.commit()
        db.refresh(payment)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    try:
        from app.finance.events.hooks import on_customer_payment_financial_event

        on_customer_payment_financial_event(db, payment)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "financial_events: customer payment hook failed (non-fatal) payment=%s",
            payment.id,
        )

    payment = (
        db.query(CustomerPayment)
        .options(
            selectinload(CustomerPayment.allocations),
            selectinload(CustomerPayment.customer),
            selectinload(CustomerPayment.branch),
        )
        .filter(CustomerPayment.id == payment.id)
        .first()
    )
    return CustomerPaymentResponse(
        id=payment.id,
        company_id=payment.company_id,
        branch_id=payment.branch_id,
        customer_id=payment.customer_id,
        payment_date=payment.payment_date,
        method=payment.method,
        reference=payment.reference,
        amount=payment.amount,
        is_allocated=payment.is_allocated or False,
        created_by=payment.created_by,
        created_at=payment.created_at,
        allocations=[
            CustomerPaymentAllocationResponse(
                id=a.id,
                customer_payment_id=a.customer_payment_id,
                sales_invoice_id=a.sales_invoice_id,
                allocated_amount=a.allocated_amount,
                invoice_no=getattr(a.sales_invoice, "invoice_no", None) if getattr(a, "sales_invoice", None) else None,
            )
            for a in payment.allocations
        ],
        customer_name=payment.customer.name if payment.customer else None,
        branch_name=payment.branch.name if payment.branch else None,
    )


@router.get("/payments", response_model=List[CustomerPaymentResponse])
def list_customer_payments(
    request: Request,
    customer_id: Optional[UUID] = Query(None),
    branch_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    q = db.query(CustomerPayment).filter(CustomerPayment.company_id == company_id)
    if customer_id:
        q = q.filter(CustomerPayment.customer_id == customer_id)
    if branch_id:
        q = q.filter(CustomerPayment.branch_id == branch_id)
    if date_from:
        q = q.filter(CustomerPayment.payment_date >= date_from)
    if date_to:
        q = q.filter(CustomerPayment.payment_date <= date_to)
    payments = (
        q.order_by(CustomerPayment.payment_date.desc(), CustomerPayment.created_at.desc())
        .offset(offset)
        .limit(limit)
        .options(
            selectinload(CustomerPayment.allocations),
            selectinload(CustomerPayment.customer),
            selectinload(CustomerPayment.branch),
        )
        .all()
    )
    return [
        CustomerPaymentResponse(
            id=p.id,
            company_id=p.company_id,
            branch_id=p.branch_id,
            customer_id=p.customer_id,
            payment_date=p.payment_date,
            method=p.method,
            reference=p.reference,
            amount=p.amount,
            is_allocated=p.is_allocated or False,
            created_by=p.created_by,
            created_at=p.created_at,
            allocations=[
                CustomerPaymentAllocationResponse(
                    id=a.id,
                    customer_payment_id=a.customer_payment_id,
                    sales_invoice_id=a.sales_invoice_id,
                    allocated_amount=a.allocated_amount,
                )
                for a in p.allocations
            ],
            customer_name=p.customer.name if p.customer else None,
            branch_name=p.branch.name if p.branch else None,
        )
        for p in payments
    ]


@router.get("/ledger", response_model=List[CustomerLedgerEntryResponse])
def list_customer_ledger(
    request: Request,
    customer_id: UUID = Query(...),
    branch_id: Optional[UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    q = db.query(CustomerLedgerEntry).filter(
        CustomerLedgerEntry.company_id == company_id,
        CustomerLedgerEntry.customer_id == customer_id,
    )
    if branch_id:
        q = q.filter(CustomerLedgerEntry.branch_id == branch_id)
    if date_from:
        q = q.filter(CustomerLedgerEntry.date >= date_from)
    if date_to:
        q = q.filter(CustomerLedgerEntry.date <= date_to)
    entries = (
        q.order_by(CustomerLedgerEntry.date.asc(), CustomerLedgerEntry.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [CustomerLedgerEntryResponse.model_validate(e) for e in entries]


@router.get("/reports/aging", response_model=CustomerAgingReportResponse)
def get_customer_aging_report(
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    as_of_date: Optional[date] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    company_id = _effective_company_id(request)
    report_ctx = guard_finance_branch_query_param(
        db,
        user=user,
        company_id=company_id,
        permission="wholesale.ar.view",
        classification=MANAGEMENT,
        branch_id=branch_id,
        registry_id="customers.aging",
    )
    as_of = as_of_date or date.today()
    eff_due = _sales_invoice_effective_due_sql()

    b0_30 = case(
        (eff_due.is_(None), SalesInvoice.balance),
        (eff_due >= as_of - timedelta(days=30), SalesInvoice.balance),
        else_=0,
    )
    b31_60 = case(
        (and_(eff_due >= as_of - timedelta(days=60), eff_due < as_of - timedelta(days=30)), SalesInvoice.balance),
        else_=0,
    )
    b61_90 = case(
        (and_(eff_due >= as_of - timedelta(days=90), eff_due < as_of - timedelta(days=60)), SalesInvoice.balance),
        else_=0,
    )
    b90_plus = case((eff_due < as_of - timedelta(days=90), SalesInvoice.balance), else_=0)

    q = db.query(
        SalesInvoice.customer_id,
        Customer.name.label("customer_name"),
        func.coalesce(func.sum(SalesInvoice.balance), 0).label("total_outstanding"),
        func.coalesce(func.sum(b0_30), 0).label("current"),
        func.coalesce(func.sum(b31_60), 0).label("b31"),
        func.coalesce(func.sum(b61_90), 0).label("b61"),
        func.coalesce(func.sum(b90_plus), 0).label("b90"),
    ).join(Customer, Customer.id == SalesInvoice.customer_id).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.customer_id.isnot(None),
        (SalesInvoice.balance.is_(None) | (SalesInvoice.balance > 0)),
        SalesInvoice.status.in_(["BATCHED", "PAID"]),
    )
    q = report_ctx.apply_branch_filter(q, SalesInvoice.branch_id, branch_id)
    q = q.group_by(SalesInvoice.customer_id, Customer.name)
    rows = q.all()

    result_rows = []
    bucket_totals = {"current": Decimal("0"), "d30": Decimal("0"), "d60": Decimal("0"), "d90": Decimal("0")}
    for r in rows:
        total = Decimal(str(r.total_outstanding or 0))
        if total <= 0:
            continue
        c0 = Decimal(str(r.current or 0))
        c31 = Decimal(str(r.b31 or 0))
        c61 = Decimal(str(r.b61 or 0))
        c90p = Decimal(str(r.b90 or 0))
        bucket_totals["current"] += c0
        bucket_totals["d30"] += c31
        bucket_totals["d60"] += c61
        bucket_totals["d90"] += c90p
        result_rows.append(
            CustomerAgingRow(
                customer_id=r.customer_id,
                customer_name=r.customer_name or "",
                current=c0,
                days_1_30=c31,
                days_31_60=c61,
                days_61_90=c61,
                days_over_90=c90p,
                total_outstanding=total,
            )
        )

    return CustomerAgingReportResponse(
        as_of_date=as_of,
        branch_id=branch_id,
        rows=result_rows,
        buckets=[
            AgingBucket(label="Current", amount=bucket_totals["current"]),
            AgingBucket(label="1-30", amount=bucket_totals["d30"]),
            AgingBucket(label="31-60", amount=bucket_totals["d60"]),
            AgingBucket(label="90+", amount=bucket_totals["d90"]),
        ],
    )


def _require_customer_statement_access(
    db: Session,
    user,
    *,
    branch_id: Optional[UUID],
) -> None:
    if not _user_has_permission(db, user.id, "customers.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: customers.view")
    if branch_id is not None:
        ensure_user_has_branch_access(db, user.id, branch_id)


def _statement_response_from_build(data: dict) -> CustomerStatementResponse:
    integrity_raw = data.get("statement_integrity") or {}
    return CustomerStatementResponse(
        customer_id=data["customer_id"],
        customer_name=data["customer_name"],
        customer_pin=data.get("customer_pin"),
        company_id=data.get("company_id"),
        company_name=data.get("company_name"),
        branch_id=data.get("branch_id"),
        branch_name=data.get("branch_name"),
        from_date=data["from_date"],
        to_date=data["to_date"],
        opening_balance=data["opening_balance"],
        closing_balance=data["closing_balance"],
        lines=[
            CustomerStatementLine(
                date=ln["date"],
                entry_type=ln["entry_type"],
                description=ln.get("description"),
                reference=ln.get("reference"),
                debit=ln["debit"],
                credit=ln["credit"],
                balance=ln["balance"],
            )
            for ln in data.get("lines") or []
        ],
        statement_integrity=CustomerStatementIntegrity(**integrity_raw) if integrity_raw else None,
        prepared_by=data.get("prepared_by"),
        doctrine=data.get("doctrine", "operational_ar_v1"),
    )


@router.get("/statement", response_model=CustomerStatementResponse)
def get_customer_statement(
    request: Request,
    customer_id: UUID = Query(...),
    from_date: date = Query(...),
    to_date: date = Query(...),
    branch_id: Optional[UUID] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Operational AR customer statement (customer_ledger_entries only).
    Stable order: date, created_at, id. Includes statement_integrity certificate.
    """
    user = current_user_and_db[0]
    company_id = _effective_company_id(request)
    _require_customer_statement_access(db, user, branch_id=branch_id)

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be on or before to_date")

    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == company_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    branch = db.query(Branch).filter(Branch.id == branch_id).first() if branch_id else None
    if branch_id and not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    prepared_by = getattr(user, "full_name", None) or getattr(user, "username", None) or str(user.id)
    built = build_operational_customer_statement(
        db,
        StatementBuildContext(
            company=company,
            branch=branch,
            customer=customer,
            from_date=from_date,
            to_date=to_date,
            branch_id=branch_id,
            prepared_by=prepared_by,
        ),
    )
    return _statement_response_from_build(built)


@router.get("/statement/pdf")
def get_customer_statement_pdf(
    request: Request,
    customer_id: UUID = Query(...),
    from_date: date = Query(...),
    to_date: date = Query(...),
    branch_id: Optional[UUID] = Query(None),
    block_on_fail: bool = Query(False, description="If true, return 409 when integrity status is FAIL"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    tenant: Optional[Any] = Depends(get_tenant_optional),
):
    """PDF export for operational AR statement. FAIL integrity → DRAFT watermark unless block_on_fail."""
    from app.services.tenant_storage_service import resolve_company_logo_bytes

    user = current_user_and_db[0]

    company_id = _effective_company_id(request)
    _require_customer_statement_access(db, user, branch_id=branch_id)

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be on or before to_date")

    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == company_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    branch = db.query(Branch).filter(Branch.id == branch_id).first() if branch_id else None
    if branch_id and not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    prepared_by = getattr(user, "full_name", None) or getattr(user, "username", None) or str(user.id)
    built = build_operational_customer_statement(
        db,
        StatementBuildContext(
            company=company,
            branch=branch,
            customer=customer,
            from_date=from_date,
            to_date=to_date,
            branch_id=branch_id,
            prepared_by=prepared_by,
        ),
    )
    integrity = built.get("statement_integrity") or {}
    integrity_status = integrity.get("status", "PASS")
    if block_on_fail and integrity_status == "FAIL":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Statement failed operational AR integrity checks. PDF blocked.",
                "statement_integrity": integrity,
            },
        )

    logo_bytes = resolve_company_logo_bytes(getattr(company, "logo_url", None) if company else None, tenant=tenant)
    try:
        pdf_bytes = build_customer_statement_pdf(
            company_name=company.name if company else "—",
            company_address=getattr(company, "address", None) if company else None,
            company_phone=getattr(company, "phone", None) if company else None,
            company_pin=getattr(company, "pin", None) if company else None,
            company_logo_bytes=logo_bytes,
            branch_name=branch.name if branch else None,
            branch_address=getattr(branch, "address", None) if branch else None,
            customer_name=customer.name,
            customer_pin=customer.pin,
            from_date=from_date,
            to_date=to_date,
            opening_balance=built["opening_balance"],
            closing_balance=built["closing_balance"],
            lines=built.get("lines") or [],
            prepared_by=prepared_by,
            generated_at_utc=integrity.get("generated_at_utc"),
            integrity_status=integrity_status,
            doctrine=built.get("doctrine", "operational_ar_v1"),
            integrity_warnings=integrity.get("warnings") or [],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate statement PDF: {e}") from e

    prefix = "DRAFT-" if integrity_status == "FAIL" else ""
    safe_name = (customer.name or "customer").replace(" ", "-")[:40]
    filename = f"{prefix}customer-statement-{safe_name}-{from_date}-{to_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Statement-Integrity": integrity_status,
        },
    )


# --- CRM activities ---
@router.get("/activities", response_model=List[CustomerActivityResponse])
def list_customer_activities(
    request: Request,
    customer_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    q = db.query(CustomerActivity).filter(CustomerActivity.company_id == company_id)
    if customer_id:
        q = q.filter(CustomerActivity.customer_id == customer_id)
    if status_filter:
        q = q.filter(CustomerActivity.status == status_filter)
    acts = (
        q.order_by(CustomerActivity.due_date.asc().nullslast(), CustomerActivity.created_at.desc())
        .limit(limit)
        .options(selectinload(CustomerActivity.customer))
        .all()
    )
    return [
        CustomerActivityResponse(
            id=a.id,
            company_id=a.company_id,
            customer_id=a.customer_id,
            activity_type=a.activity_type,
            subject=a.subject,
            notes=a.notes,
            due_date=a.due_date,
            status=a.status,
            assigned_user_id=a.assigned_user_id,
            completed_at=a.completed_at,
            created_by=a.created_by,
            created_at=a.created_at,
            updated_at=a.updated_at,
            customer_name=a.customer.name if a.customer else None,
        )
        for a in acts
    ]


@router.get("/follow-ups", response_model=List[CustomerActivityResponse])
def list_follow_ups(
    request: Request,
    due_before: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    cutoff = due_before or date.today()
    acts = (
        db.query(CustomerActivity)
        .filter(
            CustomerActivity.company_id == company_id,
            CustomerActivity.status == "open",
            CustomerActivity.due_date.isnot(None),
            CustomerActivity.due_date <= cutoff,
        )
        .order_by(CustomerActivity.due_date.asc())
        .limit(limit)
        .options(selectinload(CustomerActivity.customer))
        .all()
    )
    return [
        CustomerActivityResponse(
            id=a.id,
            company_id=a.company_id,
            customer_id=a.customer_id,
            activity_type=a.activity_type,
            subject=a.subject,
            notes=a.notes,
            due_date=a.due_date,
            status=a.status,
            assigned_user_id=a.assigned_user_id,
            completed_at=a.completed_at,
            created_by=a.created_by,
            created_at=a.created_at,
            updated_at=a.updated_at,
            customer_name=a.customer.name if a.customer else None,
        )
        for a in acts
    ]


@router.post("/activities", response_model=CustomerActivityResponse, status_code=status.HTTP_201_CREATED)
def create_customer_activity(
    body: CustomerActivityCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    user = current_user_and_db[0]
    customer = db.query(Customer).filter(
        Customer.id == body.customer_id, Customer.company_id == company_id
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    act = CustomerActivity(
        company_id=company_id,
        customer_id=body.customer_id,
        activity_type=body.activity_type,
        subject=body.subject,
        notes=body.notes,
        due_date=body.due_date,
        assigned_user_id=body.assigned_user_id,
        status="open",
        created_by=user.id,
    )
    db.add(act)
    db.commit()
    db.refresh(act)
    return CustomerActivityResponse(
        id=act.id,
        company_id=act.company_id,
        customer_id=act.customer_id,
        activity_type=act.activity_type,
        subject=act.subject,
        notes=act.notes,
        due_date=act.due_date,
        status=act.status,
        assigned_user_id=act.assigned_user_id,
        completed_at=act.completed_at,
        created_by=act.created_by,
        created_at=act.created_at,
        updated_at=act.updated_at,
        customer_name=customer.name,
    )


@router.patch("/activities/{activity_id}", response_model=CustomerActivityResponse)
def update_customer_activity(
    activity_id: UUID,
    body: CustomerActivityUpdate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    act = db.query(CustomerActivity).filter(
        CustomerActivity.id == activity_id, CustomerActivity.company_id == company_id
    ).first()
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(act, k, v)
    if data.get("status") == "completed" and not act.completed_at:
        act.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(act)
    customer = db.query(Customer).filter(Customer.id == act.customer_id).first()
    return CustomerActivityResponse(
        id=act.id,
        company_id=act.company_id,
        customer_id=act.customer_id,
        activity_type=act.activity_type,
        subject=act.subject,
        notes=act.notes,
        due_date=act.due_date,
        status=act.status,
        assigned_user_id=act.assigned_user_id,
        completed_at=act.completed_at,
        created_by=act.created_by,
        created_at=act.created_at,
        updated_at=act.updated_at,
        customer_name=customer.name if customer else None,
    )


@router.get("/reports/analytics/{customer_id}", response_model=CustomerAnalyticsResponse)
def get_customer_analytics(
    customer_id: UUID,
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    company_id = _effective_company_id(request)
    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == company_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    today = date.today()
    d30 = today - timedelta(days=30)
    d90 = today - timedelta(days=90)
    d365 = today - timedelta(days=365)

    def _sum_since(since: date) -> Decimal:
        q = db.query(func.coalesce(func.sum(SalesInvoice.total_inclusive), 0)).filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.status.in_(["BATCHED", "PAID"]),
            SalesInvoice.invoice_date >= since,
        )
        if branch_id:
            q = q.filter(SalesInvoice.branch_id == branch_id)
        return Decimal(str(q.scalar() or 0))

    outstanding = CustomerLedgerService.get_outstanding_balance(
        db, customer_id, company_id, branch_id=branch_id
    )
    eff_due = _sales_invoice_effective_due_sql()
    overdue_q = db.query(func.coalesce(func.sum(SalesInvoice.balance), 0)).join(
        Customer, Customer.id == SalesInvoice.customer_id
    ).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.balance > 0,
        eff_due < today,
    )
    if branch_id:
        overdue_q = overdue_q.filter(SalesInvoice.branch_id == branch_id)
    overdue = Decimal(str(overdue_q.scalar() or 0))

    open_fu = db.query(func.count(CustomerActivity.id)).filter(
        CustomerActivity.company_id == company_id,
        CustomerActivity.customer_id == customer_id,
        CustomerActivity.status == "open",
    ).scalar() or 0

    return CustomerAnalyticsResponse(
        customer_id=customer_id,
        customer_name=customer.name,
        sales_30d=_sum_since(d30),
        sales_90d=_sum_since(d90),
        sales_365d=_sum_since(d365),
        outstanding_balance=outstanding,
        overdue_amount=overdue,
        open_follow_ups=int(open_fu),
    )
