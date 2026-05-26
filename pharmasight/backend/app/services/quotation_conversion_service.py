"""
Helpers for quotation ↔ sales invoice conversion lifecycle.

When a quotation is converted to a draft invoice, quotations.converted_to_invoice_id
references the invoice. That FK must be cleared before the invoice can be deleted or
converted back to a quotation.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Quotation, QuotationItem, SalesInvoice, SalesInvoiceItem


def find_quotation_linked_to_invoice(db: Session, invoice_id: UUID) -> Optional[Quotation]:
    return (
        db.query(Quotation)
        .filter(Quotation.converted_to_invoice_id == invoice_id)
        .first()
    )


def release_quotations_linked_to_invoice(db: Session, invoice_id: UUID) -> List[Quotation]:
    """Clear conversion link so the draft invoice can be removed; reopen as draft."""
    quotations = (
        db.query(Quotation)
        .filter(Quotation.converted_to_invoice_id == invoice_id)
        .all()
    )
    for quotation in quotations:
        quotation.converted_to_invoice_id = None
        if quotation.status == "converted":
            quotation.status = "draft"
    return quotations


def _sync_quotation_items_from_invoice(
    db: Session,
    quotation: Quotation,
    invoice_items: List[SalesInvoiceItem],
) -> None:
    for existing in list(quotation.items or []):
        db.delete(existing)
    db.flush()
    for invoice_item in invoice_items:
        db.add(
            QuotationItem(
                quotation_id=quotation.id,
                item_id=invoice_item.item_id,
                unit_name=invoice_item.unit_name,
                quantity=invoice_item.quantity,
                unit_price_exclusive=invoice_item.unit_price_exclusive,
                discount_percent=invoice_item.discount_percent,
                discount_amount=invoice_item.discount_amount,
                vat_rate=invoice_item.vat_rate,
                vat_amount=invoice_item.vat_amount,
                line_total_exclusive=invoice_item.line_total_exclusive,
                line_total_inclusive=invoice_item.line_total_inclusive,
            )
        )


def reopen_source_quotation_from_invoice(
    db: Session,
    invoice: SalesInvoice,
) -> Optional[Quotation]:
    """
    If this draft invoice came from a quotation conversion, restore that quotation
    from the current invoice lines and clear the link (caller deletes the invoice).
    """
    quotation = find_quotation_linked_to_invoice(db, invoice.id)
    if not quotation:
        return None

    quotation.converted_to_invoice_id = None
    quotation.status = "draft"
    quotation.quotation_date = invoice.invoice_date
    if getattr(invoice, "customer_id", None):
        quotation.customer_id = invoice.customer_id
    quotation.customer_name = invoice.customer_name
    quotation.customer_pin = invoice.customer_pin
    quotation.total_exclusive = invoice.total_exclusive
    quotation.vat_rate = invoice.vat_rate
    quotation.vat_amount = invoice.vat_amount
    quotation.discount_amount = invoice.discount_amount
    quotation.total_inclusive = invoice.total_inclusive

    _sync_quotation_items_from_invoice(db, quotation, list(invoice.items or []))
    return quotation
