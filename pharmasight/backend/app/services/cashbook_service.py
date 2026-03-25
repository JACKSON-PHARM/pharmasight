"""
Cashbook service: create money-movement tracking entries.

Cashbook is a tracking layer, so this service only *adds* cashbook entries
when sourced events occur (expenses approved, supplier payments created, etc.).
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CashbookEntry, Expense, SupplierPayment, SalesInvoice, InvoicePayment

SOURCE_TYPE_EXPENSE = "expense"
SOURCE_TYPE_SUPPLIER_PAYMENT = "supplier_payment"
SOURCE_TYPE_SALE = "sale"


def _normalize_cashbook_payment_mode(payment_mode: str) -> str:
    m = (payment_mode or "").strip().lower()
    if m in ("cash", "mpesa", "bank"):
        return m
    # Be conservative for future/migration values; cashbook only supports cash/mpesa/bank.
    # If an unexpected value exists, treat it as bank (cashless).
    return "bank"


def _normalize_supplier_method_to_cashbook_payment_mode(method: str) -> str:
    m = (method or "").strip().lower()
    if m == "cash":
        return "cash"
    if m == "mpesa":
        return "mpesa"
    # bank/card/cheque/other => bank
    return "bank"


def _normalize_sale_payment_mode_to_cashbook(payment_mode: str) -> Optional[str]:
    """
    Cashbook only supports cash/mpesa/bank.
    For sales payments:
    - credit => None (no real cash inflow)
    - cash/mpesa => mapped directly
    - card/insurance/other => bank
    """
    m = (payment_mode or "").strip().lower()
    if m == "credit":
        return None
    if m == "cash":
        return "cash"
    if m == "mpesa":
        return "mpesa"
    # card/insurance/bank/cheque => bank (cashless inflow)
    return "bank"

def create_cashbook_entry_if_missing(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    entry_date: date,
    amount: Decimal,
    payment_mode: str,
    source_type: str,
    source_id: UUID,
    reference_number: Optional[str],
    description: Optional[str],
    created_by: UUID,
    entry_type: str,
) -> Optional[CashbookEntry]:
    """
    Insert a cashbook entry if it doesn't already exist.

    Deduplication is based on (company_id, source_type, source_id).
    """

    if not source_type or not source_id:
        raise HTTPException(status_code=400, detail="source_type and source_id are required")

    payment_mode_norm = _normalize_cashbook_payment_mode(payment_mode)

    existing = (
        db.query(CashbookEntry)
        .filter(
            CashbookEntry.company_id == company_id,
            CashbookEntry.source_type == source_type,
            CashbookEntry.source_id == source_id,
        )
        .first()
    )
    if existing:
        return None

    entry = CashbookEntry(
        company_id=company_id,
        branch_id=branch_id,
        date=entry_date,
        type=entry_type,
        amount=amount,
        payment_mode=payment_mode_norm,
        source_type=source_type,
        source_id=source_id,
        reference_number=reference_number,
        description=description,
        created_by=created_by,
    )
    db.add(entry)
    return entry


def create_outflow_cashbook_entry_if_missing(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    entry_date: date,
    amount: Decimal,
    payment_mode: str,
    source_type: str,
    source_id: UUID,
    reference_number: Optional[str],
    description: Optional[str],
    created_by: UUID,
) -> Optional[CashbookEntry]:
    return create_cashbook_entry_if_missing(
        db,
        company_id=company_id,
        branch_id=branch_id,
        entry_date=entry_date,
        amount=amount,
        payment_mode=payment_mode,
        source_type=source_type,
        source_id=source_id,
        reference_number=reference_number,
        description=description,
        created_by=created_by,
        entry_type="outflow",
    )


def ensure_cashbook_entry_for_expense_if_approved(db: Session, *, expense) -> Optional[CashbookEntry]:
    """
    Create cashbook outflow for an expense when (and only when) it is approved.

    Expects `expense` to have:
    - id
    - company_id, branch_id
    - status
    - amount, expense_date, payment_mode
    - reference_number, description
    - created_by
    """

    if getattr(expense, "status", None) != "approved":
        return None

    return create_outflow_cashbook_entry_if_missing(
        db,
        company_id=expense.company_id,
        branch_id=expense.branch_id,
        entry_date=expense.expense_date,
        amount=expense.amount,
        payment_mode=getattr(expense, "payment_mode", None),
        source_type=SOURCE_TYPE_EXPENSE,
        source_id=expense.id,
        reference_number=getattr(expense, "reference_number", None),
        description=getattr(expense, "description", None),
        created_by=expense.created_by,
    )


def ensure_cashbook_entry_for_supplier_payment(db: Session, *, payment) -> Optional[CashbookEntry]:
    """
    Create cashbook outflow for a supplier payment.

    Expects `payment` to have:
    - id
    - company_id, branch_id
    - method, payment_date, amount
    - reference
    - created_by
    """

    return create_outflow_cashbook_entry_if_missing(
        db,
        company_id=payment.company_id,
        branch_id=payment.branch_id,
        entry_date=payment.payment_date,
        amount=payment.amount,
        payment_mode=_normalize_supplier_method_to_cashbook_payment_mode(getattr(payment, "method", None)),
        source_type=SOURCE_TYPE_SUPPLIER_PAYMENT,
        source_id=payment.id,
        reference_number=getattr(payment, "reference", None),
        description=f"Supplier payment" if getattr(payment, "reference", None) is None else f"Supplier payment ({payment.reference})",
        created_by=payment.created_by,
    )


def ensure_implicit_invoice_payment_for_paid_invoice_if_missing(
    db: Session,
    *,
    invoice: SalesInvoice,
    created_by: UUID,
) -> bool:
    """
    Legacy batched-cash invoices were PAID without InvoicePayment rows. Create one
    full payment + cashbook inflow when still missing (same rules as batch_sales_invoice).

    Returns True if a new InvoicePayment was inserted.
    """
    if getattr(invoice, "status", None) != "PAID":
        return False
    if _normalize_sale_payment_mode_to_cashbook(getattr(invoice, "payment_mode", None)) is None:
        return False
    existing_pay = (
        db.query(func.coalesce(func.sum(InvoicePayment.amount), 0))
        .filter(InvoicePayment.invoice_id == invoice.id)
        .scalar()
    ) or Decimal("0")
    existing_pay = Decimal(str(existing_pay))
    total_inv = Decimal(str(invoice.total_inclusive or 0))
    remainder = total_inv - existing_pay
    if remainder <= Decimal("0.01"):
        return False

    mode = (getattr(invoice, "payment_mode", None) or "cash").strip().lower()
    actor = invoice.approved_by or invoice.batched_by or invoice.created_by or created_by
    paid_at_inv = datetime.combine(invoice.invoice_date, time.min, tzinfo=timezone.utc)
    ip = InvoicePayment(
        invoice_id=invoice.id,
        payment_mode=mode,
        amount=remainder,
        payment_reference=None,
        paid_by=actor,
        paid_at=paid_at_inv,
    )
    db.add(ip)
    db.flush()
    ensure_cashbook_entry_for_invoice_payment_if_cash(
        db,
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        invoice_payment=ip,
        invoice_no=invoice.invoice_no,
        created_by=actor,
        entry_date=invoice.invoice_date,
    )
    return True


def ensure_cashbook_entry_for_invoice_payment_if_cash(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    invoice_payment,
    invoice_no: Optional[str],
    created_by: UUID,
    entry_date: Optional[date] = None,
) -> Optional[CashbookEntry]:
    """
    Create cashbook inflow entry for sales invoice payments when the payment_mode
    represents real money (cash/mpesa/bank). Skip 'credit'.
    """
    payment_mode_norm = _normalize_sale_payment_mode_to_cashbook(getattr(invoice_payment, "payment_mode", None))
    if payment_mode_norm is None:
        return None

    if entry_date is None:
        # invoice_payment.paid_at is TIMESTAMP with server_default in DB; if not populated
        # yet, fall back to created_at or today's date.
        paid_at = getattr(invoice_payment, "paid_at", None)
        if paid_at is not None:
            entry_date = paid_at.date()
        else:
            created_at = getattr(invoice_payment, "created_at", None)
            entry_date = created_at.date() if created_at is not None else date.today()

    return create_cashbook_entry_if_missing(
        db,
        company_id=company_id,
        branch_id=branch_id,
        entry_date=entry_date,
        amount=getattr(invoice_payment, "amount", Decimal("0")),
        payment_mode=payment_mode_norm,
        source_type=SOURCE_TYPE_SALE,
        source_id=invoice_payment.id,
        reference_number=getattr(invoice_payment, "payment_reference", None),
        description=f"Sale payment ({invoice_no})" if invoice_no else "Sale payment",
        created_by=created_by,
        entry_type="inflow",
    )


def backfill_cashbook_entries(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    start_date: date,
    end_date: date,
    created_by: UUID,
) -> Dict[str, int]:
    """
    Backfill cashbook entries from existing approved expenses, supplier payments,
    and sales invoice payments (cash/mpesa/bank only) for the given branch/date range.

    Idempotent via dedupe (unique constraint + pre-checks).
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be <= end_date")

    inserted = 0

    # ----------------------------
    # PAID invoices with no invoice_payments (legacy batched-cash)
    # ----------------------------
    orphan_invoices = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status == "PAID",
            SalesInvoice.invoice_date >= start_date,
            SalesInvoice.invoice_date <= end_date,
        )
        .all()
    )
    for inv in orphan_invoices:
        if ensure_implicit_invoice_payment_for_paid_invoice_if_missing(db, invoice=inv, created_by=created_by):
            inserted += 1

    # ----------------------------
    # Approved expenses (outflow)
    # ----------------------------
    exp_rows = (
        db.query(Expense)
        .filter(
            Expense.company_id == company_id,
            Expense.branch_id == branch_id,
            Expense.status == "approved",
            Expense.expense_date >= start_date,
            Expense.expense_date <= end_date,
        )
        .all()
    )
    exp_ids = [e.id for e in exp_rows]
    existing_exp_ids = set()
    if exp_ids:
        existing_exp_ids = {
            r[0]
            for r in db.query(CashbookEntry.source_id)
            .filter(
                CashbookEntry.company_id == company_id,
                CashbookEntry.source_type == SOURCE_TYPE_EXPENSE,
                CashbookEntry.source_id.in_(exp_ids),
            )
            .all()
        }
    for e in exp_rows:
        if e.id in existing_exp_ids:
            continue
        entry = create_outflow_cashbook_entry_if_missing(
            db,
            company_id=e.company_id,
            branch_id=e.branch_id,
            entry_date=e.expense_date,
            amount=e.amount,
            payment_mode=getattr(e, "payment_mode", None),
            source_type=SOURCE_TYPE_EXPENSE,
            source_id=e.id,
            reference_number=getattr(e, "reference_number", None),
            description=getattr(e, "description", None),
            created_by=e.created_by,
        )
        if entry is not None:
            inserted += 1

    # ----------------------------
    # Supplier payments (outflow)
    # ----------------------------
    pay_rows = (
        db.query(SupplierPayment)
        .filter(
            SupplierPayment.company_id == company_id,
            SupplierPayment.branch_id == branch_id,
            SupplierPayment.payment_date >= start_date,
            SupplierPayment.payment_date <= end_date,
        )
        .all()
    )
    pay_ids = [p.id for p in pay_rows]
    existing_pay_ids = set()
    if pay_ids:
        existing_pay_ids = {
            r[0]
            for r in db.query(CashbookEntry.source_id)
            .filter(
                CashbookEntry.company_id == company_id,
                CashbookEntry.source_type == SOURCE_TYPE_SUPPLIER_PAYMENT,
                CashbookEntry.source_id.in_(pay_ids),
            )
            .all()
        }

    for p in pay_rows:
        if p.id in existing_pay_ids:
            continue
        entry = create_outflow_cashbook_entry_if_missing(
            db,
            company_id=p.company_id,
            branch_id=p.branch_id,
            entry_date=p.payment_date,
            amount=p.amount,
            payment_mode=_normalize_supplier_method_to_cashbook_payment_mode(getattr(p, "method", None)),
            source_type=SOURCE_TYPE_SUPPLIER_PAYMENT,
            source_id=p.id,
            reference_number=getattr(p, "reference", None),
            description=f"Supplier payment ({p.reference})" if getattr(p, "reference", None) else "Supplier payment",
            created_by=p.created_by if getattr(p, "created_by", None) else created_by,
        )
        if entry is not None:
            inserted += 1

    # ----------------------------
    # PAID invoices with no invoice_payment rows (legacy batched cash / no POST /payments)
    # ----------------------------
    paid_invoices = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status == "PAID",
            SalesInvoice.invoice_date >= start_date,
            SalesInvoice.invoice_date <= end_date,
        )
        .all()
    )
    for inv in paid_invoices:
        if _normalize_sale_payment_mode_to_cashbook(getattr(inv, "payment_mode", None)) is None:
            continue
        existing_sum = (
            db.query(func.coalesce(func.sum(InvoicePayment.amount), 0))
            .filter(InvoicePayment.invoice_id == inv.id)
            .scalar()
        ) or Decimal("0")
        total_inv = Decimal(str(inv.total_inclusive or 0))
        remainder = total_inv - existing_sum
        if remainder <= Decimal("0.01"):
            continue
        pm = (inv.payment_mode or "cash").strip().lower()
        ip = InvoicePayment(
            invoice_id=inv.id,
            payment_mode=pm,
            amount=remainder,
            payment_reference=None,
            paid_by=inv.batched_by or inv.approved_by or inv.created_by,
            paid_at=datetime.combine(inv.invoice_date, time.min, tzinfo=timezone.utc),
        )
        db.add(ip)
    db.flush()

    # ----------------------------
    # Sale invoice payments (inflow) — align range with invoice business date, not payment row created_at
    # ----------------------------
    sale_pay_rows = (
        db.query(InvoicePayment, SalesInvoice.invoice_no, SalesInvoice.invoice_date)
        .join(SalesInvoice, SalesInvoice.id == InvoicePayment.invoice_id)
        .filter(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.invoice_date >= start_date,
            SalesInvoice.invoice_date <= end_date,
        )
        .all()
    )
    # Filter out credit payments in Python (depends on payment_mode values).
    sale_pay_rows = [
        (ip, inv_no, inv_d)
        for (ip, inv_no, inv_d) in sale_pay_rows
        if _normalize_sale_payment_mode_to_cashbook(getattr(ip, "payment_mode", None)) is not None
    ]

    sale_pay_ids = [ip.id for (ip, _, _) in sale_pay_rows]
    existing_sale_ids = set()
    if sale_pay_ids:
        existing_sale_ids = {
            r[0]
            for r in db.query(CashbookEntry.source_id)
            .filter(
                CashbookEntry.company_id == company_id,
                CashbookEntry.source_type == SOURCE_TYPE_SALE,
                CashbookEntry.source_id.in_(sale_pay_ids),
            )
            .all()
        }

    for ip, inv_no, inv_date in sale_pay_rows:
        # Reconcile existing sale cashbook entries so historical totals line up with
        # the actual payment timestamp (older versions may have recorded date=TODAY).
        if ip.id in existing_sale_ids:
            existing_entry = (
                db.query(CashbookEntry)
                .filter(
                    CashbookEntry.company_id == company_id,
                    CashbookEntry.source_type == SOURCE_TYPE_SALE,
                    CashbookEntry.source_id == ip.id,
                )
                .first()
            )
            expected_payment_mode = payment_mode_norm = _normalize_sale_payment_mode_to_cashbook(getattr(ip, "payment_mode", None))
            if existing_entry is not None and expected_payment_mode is not None:
                paid_at = getattr(ip, "paid_at", None)
                expected_date = paid_at.date() if paid_at is not None else inv_date
                changed = False
                if existing_entry.type != "inflow":
                    existing_entry.type = "inflow"
                    changed = True
                if existing_entry.date != expected_date:
                    existing_entry.date = expected_date
                    changed = True
                if existing_entry.payment_mode != expected_payment_mode:
                    existing_entry.payment_mode = expected_payment_mode
                    changed = True
                # Keep amount as-is if dedupe worked; still reconcile if different.
                try:
                    if Decimal(existing_entry.amount) != getattr(ip, "amount", Decimal("0")):
                        existing_entry.amount = getattr(ip, "amount", Decimal("0"))
                        changed = True
                except Exception:
                    pass
                if changed:
                    db.add(existing_entry)
            continue
        payment_mode_norm = _normalize_sale_payment_mode_to_cashbook(getattr(ip, "payment_mode", None))
        if payment_mode_norm is None:
            continue
        paid_at = getattr(ip, "paid_at", None)
        entry_date = paid_at.date() if paid_at is not None else inv_date
        entry = create_cashbook_entry_if_missing(
            db,
            company_id=company_id,
            branch_id=branch_id,
            entry_date=entry_date,
            amount=getattr(ip, "amount", Decimal("0")),
            payment_mode=payment_mode_norm,
            source_type=SOURCE_TYPE_SALE,
            source_id=ip.id,
            reference_number=getattr(ip, "payment_reference", None),
            description=f"Sale payment ({inv_no})" if inv_no else "Sale payment",
            created_by=created_by,
            entry_type="inflow",
        )
        if entry is not None:
            inserted += 1

    return {"inserted": inserted}

