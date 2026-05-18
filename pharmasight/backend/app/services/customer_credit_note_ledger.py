"""
Post customer AR credit when a customer-linked credit note is finalized (posted).

Operational AR only — not financial_events / E7.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.customer_financial import CustomerLedgerEntry
from app.models.sale import CreditNote, SalesInvoice
from app.services.customer_ledger_service import CustomerLedgerService

ENTRY_CREDIT_NOTE = "credit_note"


def has_credit_note_ledger_entry(db: Session, *, company_id: UUID, credit_note_id: UUID) -> bool:
    return (
        db.query(CustomerLedgerEntry.id)
        .filter(
            CustomerLedgerEntry.company_id == company_id,
            CustomerLedgerEntry.entry_type == ENTRY_CREDIT_NOTE,
            CustomerLedgerEntry.reference_id == credit_note_id,
        )
        .first()
        is not None
    )


def post_customer_ledger_on_credit_note(
    db: Session,
    *,
    credit_note: CreditNote,
    invoice: SalesInvoice,
    company_id: UUID,
) -> CustomerLedgerEntry | None:
    """
    Credit AR when return is posted against an invoice with a linked B2B/retail customer.
    Idempotent per credit_note.id.
    """
    if not invoice.customer_id:
        return None
    if credit_note.posting_status != "posted":
        return None
    if has_credit_note_ledger_entry(db, company_id=company_id, credit_note_id=credit_note.id):
        return None

    total = Decimal(str(credit_note.total_inclusive or 0))
    if total <= 0:
        return None

    return CustomerLedgerService.create_entry(
        db,
        company_id=company_id,
        branch_id=credit_note.branch_id,
        customer_id=invoice.customer_id,
        entry_date=credit_note.credit_note_date,
        entry_type=ENTRY_CREDIT_NOTE,
        reference_id=credit_note.id,
        debit=Decimal("0"),
        credit=total,
    )
