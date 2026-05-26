"""
Helpers for sales invoice payment settlement (split payments vs invoice total).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sale import InvoicePayment, SalesInvoice

# KES: treat within 1 cent as fully settled (rounding / legacy rows).
PAYMENT_SETTLEMENT_TOLERANCE = Decimal("0.01")

# POS rows that reduce invoice / customer AR (not sale-on-account or insurer receivable).
NON_SETTLING_POS_PAYMENT_MODES = frozenset({"insurance", "credit", ""})


def _d(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def sum_settled_payments(db: Session, invoice_id: UUID) -> Decimal:
    """Real money POS payments count toward settlement (excludes insurance + credit modes)."""
    rows = (
        db.query(InvoicePayment.payment_mode, InvoicePayment.amount)
        .filter(InvoicePayment.invoice_id == invoice_id)
        .all()
    )
    total = Decimal("0")
    for mode, amount in rows:
        if (mode or "").strip().lower() in NON_SETTLING_POS_PAYMENT_MODES:
            continue
        total += _d(amount)
    return total


def outstanding_balance(invoice: SalesInvoice, settled: Optional[Decimal] = None) -> Decimal:
    total = _d(invoice.total_inclusive)
    paid = settled if settled is not None else Decimal("0")
    return total - paid


def is_fully_settled(invoice: SalesInvoice, settled: Decimal) -> bool:
    return outstanding_balance(invoice, settled) <= PAYMENT_SETTLEMENT_TOLERANCE


def apply_payment_status_from_settled(
    invoice: SalesInvoice,
    settled: Decimal,
    *,
    approved_by: Optional[UUID] = None,
) -> str:
    """
    Update invoice.payment_status (and status when fully paid).
    Returns the new payment_status string.
    """
    total = _d(invoice.total_inclusive)
    if is_fully_settled(invoice, settled):
        invoice.payment_status = "PAID"
        invoice.status = "PAID"
        invoice.cashier_approved = True
        if approved_by is not None:
            invoice.approved_by = approved_by
            invoice.approved_at = datetime.now(timezone.utc)
        return "PAID"
    if settled > PAYMENT_SETTLEMENT_TOLERANCE:
        invoice.payment_status = "PARTIAL"
        if invoice.status == "PAID":
            invoice.status = "BATCHED"
        return "PARTIAL"
    invoice.payment_status = "UNPAID"
    if invoice.status == "PAID":
        invoice.status = "BATCHED"
    return "UNPAID"


def clear_cashier_approval(invoice: SalesInvoice) -> None:
    invoice.cashier_approved = False
    invoice.approved_by = None
    invoice.approved_at = None


def revert_paid_marking(invoice: SalesInvoice, settled: Decimal) -> str:
    """
    Undo an erroneous PAID / cashier-approved state using actual settlement rows.
    Sets UNPAID, PARTIAL, or PAID from payments; clears approval when not fully settled.
    """
    clear_cashier_approval(invoice)
    new_status = apply_payment_status_from_settled(invoice, settled, approved_by=None)
    if new_status != "PAID":
        clear_cashier_approval(invoice)
    return new_status
