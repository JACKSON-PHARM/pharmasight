"""
Sync sales invoice amount_paid / balance from customer allocations + POS invoice_payments.
"""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer_financial import CustomerPaymentAllocation
from app.models.sale import SalesInvoice, InvoicePayment
from app.services.invoice_payment_status import sum_settled_payments


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


def outstanding_after_settlements(db: Session, invoice: SalesInvoice) -> Decimal:
    ti = invoice.total_inclusive or Decimal("0")
    paid = total_settled_on_invoice(db, invoice)
    out = ti - paid
    return out if out > 0 else Decimal("0")


def prepare_customer_invoice_for_response(db: Session, invoice: SalesInvoice) -> None:
    sync_customer_invoice_paid_from_settlements(db, invoice)
    db.flush()
