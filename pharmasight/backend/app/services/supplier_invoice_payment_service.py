"""
Single source of truth for supplier invoice paid amounts: supplier_payment_allocations.

supplier_invoice.amount_paid and balance are denormalized fields synced from
SUM(allocated_amount) per invoice. Do not set amount_paid directly elsewhere.
"""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import SupplierPaymentAllocation, SupplierInvoice


def sum_allocations_for_invoice(db: Session, invoice_id: UUID) -> Decimal:
    """Total allocated to this invoice across all supplier payments."""
    row = (
        db.query(func.coalesce(func.sum(SupplierPaymentAllocation.allocated_amount), 0))
        .filter(SupplierPaymentAllocation.supplier_invoice_id == invoice_id)
        .scalar()
    )
    return Decimal(str(row or 0))


def sync_supplier_invoice_paid_from_allocations(db: Session, invoice: SupplierInvoice) -> None:
    """
    Set amount_paid = SUM(allocations), balance and payment_status from totals.
    Safe to call after any change to invoice totals or allocation rows (same transaction).
    """
    total_paid = sum_allocations_for_invoice(db, invoice.id)
    if total_paid < 0:
        total_paid = Decimal("0")

    ti = invoice.total_inclusive or Decimal("0")
    invoice.amount_paid = total_paid

    if ti <= 0:
        invoice.balance = Decimal("0")
        invoice.payment_status = "PAID" if total_paid > 0 else "UNPAID"
        return

    bal = ti - total_paid
    if bal <= 0:
        invoice.balance = Decimal("0")
        invoice.payment_status = "PAID"
    elif total_paid <= 0:
        invoice.balance = ti
        invoice.payment_status = "UNPAID"
    else:
        invoice.balance = bal
        invoice.payment_status = "PARTIAL"


def outstanding_after_allocations(db: Session, invoice: SupplierInvoice) -> Decimal:
    """Remaining invoice balance: total_inclusive minus sum of allocation rows (for validation)."""
    ti = invoice.total_inclusive or Decimal("0")
    paid = sum_allocations_for_invoice(db, invoice.id)
    out = ti - paid
    if out < 0:
        return Decimal("0")
    return out


def prepare_supplier_invoice_for_response(db: Session, invoice: SupplierInvoice) -> None:
    """
    Recompute denormalized amount_paid / balance / payment_status from allocations,
    then flush so ORM state is ready before JSON/PDF serialization.

    Call for every SupplierInvoice returned to the client, including GET (repairs drift)
    and after any mutation in the same transaction that may have changed allocations
    or invoice totals.
    """
    sync_supplier_invoice_paid_from_allocations(db, invoice)
    db.flush()
