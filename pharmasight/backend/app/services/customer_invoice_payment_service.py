"""
Sync sales invoice amount_paid / balance from customer allocations + POS invoice_payments.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer_financial import CustomerLedgerEntry
from app.models.customer_financial import CustomerPaymentAllocation
from app.models.sale import SalesInvoice, InvoicePayment
from app.services.invoice_payment_status import (
    NON_SETTLING_POS_PAYMENT_MODES,
    apply_payment_status_from_settled,
    sum_settled_payments,
)


def sum_allocations_for_invoice(db: Session, invoice_id: UUID) -> Decimal:
    row = (
        db.query(func.coalesce(func.sum(CustomerPaymentAllocation.allocated_amount), 0))
        .filter(CustomerPaymentAllocation.sales_invoice_id == invoice_id)
        .scalar()
    )
    return Decimal(str(row or 0))


def total_settled_on_invoice(db: Session, invoice: SalesInvoice) -> Decimal:
    """AR allocations + non-insurance POS payments."""
    alloc = sum_allocations_for_invoice(db, invoice.id)
    pos = sum_settled_payments(db, invoice.id)
    return alloc + pos


def sync_customer_invoice_paid_from_settlements(db: Session, invoice: SalesInvoice) -> None:
    total_paid = total_settled_on_invoice(db, invoice)
    if total_paid < 0:
        total_paid = Decimal("0")

    ti = invoice.total_inclusive or Decimal("0")
    invoice.amount_paid = total_paid

    if ti <= 0:
        invoice.balance = Decimal("0")
        if total_paid > 0:
            invoice.payment_status = "PAID"
        return

    bal = ti - total_paid
    if bal <= 0:
        invoice.balance = Decimal("0")
        invoice.payment_status = "PAID"
        if invoice.status == "BATCHED":
            invoice.status = "PAID"
    elif total_paid <= 0:
        invoice.balance = ti
        if invoice.payment_status not in ("UNPAID", "PARTIAL", "PAID"):
            invoice.payment_status = "UNPAID"
    else:
        invoice.balance = bal
        invoice.payment_status = "PARTIAL"
        if invoice.status == "PAID":
            invoice.status = "BATCHED"


def _pos_payment_settles_ar(payment: InvoicePayment) -> bool:
    mode = (getattr(payment, "payment_mode", None) or "").strip().lower()
    return mode not in NON_SETTLING_POS_PAYMENT_MODES


def ensure_customer_ledger_credits_for_invoice_payments(
    db: Session,
    invoice: SalesInvoice,
) -> int:
    """Backfill missing customer ledger credits for settled POS payments (idempotent)."""
    if not getattr(invoice, "customer_id", None):
        return 0
    payments = (
        db.query(InvoicePayment)
        .filter(InvoicePayment.invoice_id == invoice.id)
        .order_by(InvoicePayment.created_at.asc())
        .all()
    )
    created = 0
    for payment in payments:
        if not _pos_payment_settles_ar(payment):
            continue
        before = (
            db.query(CustomerLedgerEntry.id)
            .filter(
                CustomerLedgerEntry.company_id == invoice.company_id,
                CustomerLedgerEntry.customer_id == invoice.customer_id,
                CustomerLedgerEntry.entry_type == "payment",
                CustomerLedgerEntry.reference_id == payment.id,
            )
            .first()
        )
        post_customer_ledger_for_invoice_payment(db, invoice, payment)
        if not before:
            after = (
                db.query(CustomerLedgerEntry.id)
                .filter(
                    CustomerLedgerEntry.company_id == invoice.company_id,
                    CustomerLedgerEntry.customer_id == invoice.customer_id,
                    CustomerLedgerEntry.entry_type == "payment",
                    CustomerLedgerEntry.reference_id == payment.id,
                )
                .first()
            )
            if after:
                created += 1
    return created


def reconcile_customer_ar_for_invoice(
    db: Session,
    invoice: SalesInvoice,
    *,
    approved_by: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Align invoice balance/status with settlements and customer ledger credits.
    Used after POS payment collection and when repairing credit-sale mismatches.
    """
    ledger_credits_ensured = 0
    if getattr(invoice, "customer_id", None):
        ledger_credits_ensured = ensure_customer_ledger_credits_for_invoice_payments(db, invoice)
        sync_customer_invoice_paid_from_settlements(db, invoice)
        settled = total_settled_on_invoice(db, invoice)
        if (invoice.payment_status or "").upper() == "PAID":
            invoice.cashier_approved = True
            if approved_by is not None:
                invoice.approved_by = approved_by
                invoice.approved_at = datetime.now(timezone.utc)
        elif (invoice.payment_status or "").upper() != "PARTIAL":
            invoice.cashier_approved = False
            invoice.approved_by = None
            invoice.approved_at = None
    else:
        settled = sum_settled_payments(db, invoice.id)
        apply_payment_status_from_settled(invoice, settled, approved_by=approved_by)

    return {
        "settled_amount": str(settled),
        "ledger_credits_ensured": ledger_credits_ensured,
        "payment_status": invoice.payment_status,
        "status": invoice.status,
        "balance": str(invoice.balance or 0),
        "amount_paid": str(invoice.amount_paid or 0),
    }


def post_customer_ledger_for_invoice_payment(
    db: Session,
    invoice: SalesInvoice,
    payment: InvoicePayment,
) -> None:
    """Credit customer AR for direct POS invoice payments, idempotently."""
    if not getattr(invoice, "customer_id", None):
        return
    if not _pos_payment_settles_ar(payment):
        return
    amount = Decimal(str(getattr(payment, "amount", 0) or 0))
    if amount <= 0:
        return

    existing = (
        db.query(CustomerLedgerEntry.id)
        .filter(
            CustomerLedgerEntry.company_id == invoice.company_id,
            CustomerLedgerEntry.customer_id == invoice.customer_id,
            CustomerLedgerEntry.entry_type == "payment",
            CustomerLedgerEntry.reference_id == payment.id,
        )
        .first()
    )
    if existing:
        return

    paid_at = getattr(payment, "paid_at", None)
    entry_date = paid_at.date() if paid_at is not None else None
    if entry_date is None:
        from datetime import date

        entry_date = date.today()

    db.add(
        CustomerLedgerEntry(
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            customer_id=invoice.customer_id,
            date=entry_date,
            entry_type="payment",
            reference_id=payment.id,
            debit=Decimal("0"),
            credit=amount,
        )
    )


def outstanding_after_settlements(db: Session, invoice: SalesInvoice) -> Decimal:
    ti = invoice.total_inclusive or Decimal("0")
    paid = total_settled_on_invoice(db, invoice)
    out = ti - paid
    return out if out > 0 else Decimal("0")


def ensure_customer_ledger_invoice_debit(db: Session, invoice: SalesInvoice) -> bool:
    """
    Backfill missing AR invoice debit on customer ledger (legacy credit sales).
    Idempotent: skips when an invoice row already exists for this sales invoice.
    """
    if not getattr(invoice, "customer_id", None):
        return False
    total = Decimal(str(invoice.total_inclusive or 0))
    if total <= 0:
        return False
    existing = (
        db.query(CustomerLedgerEntry.id)
        .filter(
            CustomerLedgerEntry.company_id == invoice.company_id,
            CustomerLedgerEntry.customer_id == invoice.customer_id,
            CustomerLedgerEntry.entry_type == "invoice",
            CustomerLedgerEntry.reference_id == invoice.id,
        )
        .first()
    )
    if existing:
        return False
    from app.services.customer_ledger_service import CustomerLedgerService

    CustomerLedgerService.create_entry(
        db,
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        customer_id=invoice.customer_id,
        entry_date=invoice.invoice_date,
        entry_type="invoice",
        reference_id=invoice.id,
        debit=total,
        credit=Decimal("0"),
    )
    return True


def repair_customer_ar_for_statement(
    db: Session,
    *,
    company_id: UUID,
    customer_id: UUID,
    branch_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Reconcile invoice rows and backfill missing ledger debits/credits before statements.
    """
    from app.models import Customer
    from app.services.customer_opening_balance import ensure_opening_balance_ledger_entry

    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.company_id == company_id)
        .first()
    )
    if not customer:
        return {"invoices_touched": 0, "invoice_debits_backfilled": 0, "ledger_credits_ensured": 0}

    ensure_opening_balance_ledger_entry(db, customer=customer, branch_id=branch_id)

    q = db.query(SalesInvoice).filter(
        SalesInvoice.company_id == company_id,
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status.in_(["BATCHED", "PAID"]),
    )
    if branch_id is not None:
        q = q.filter(SalesInvoice.branch_id == branch_id)
    invoices = q.order_by(SalesInvoice.invoice_date.asc()).all()

    debits_backfilled = 0
    credits_ensured = 0
    for inv in invoices:
        if ensure_customer_ledger_invoice_debit(db, inv):
            debits_backfilled += 1
        result = reconcile_customer_ar_for_invoice(db, inv)
        credits_ensured += int(result.get("ledger_credits_ensured") or 0)

    if invoices:
        db.commit()

    return {
        "invoices_touched": len(invoices),
        "invoice_debits_backfilled": debits_backfilled,
        "ledger_credits_ensured": credits_ensured,
    }


def prepare_customer_invoice_for_response(db: Session, invoice: SalesInvoice) -> None:
    sync_customer_invoice_paid_from_settlements(db, invoice)
    db.flush()
