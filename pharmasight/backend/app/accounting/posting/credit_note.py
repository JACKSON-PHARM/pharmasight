"""GL posting for customer credit notes."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.constants import (
    CONTROL_AR,
    CONTROL_COGS,
    CONTROL_INVENTORY,
    CONTROL_REVENUE,
    CONTROL_VAT_OUTPUT,
)
from app.accounting.coa_service import control_account_map
from app.accounting.posting.engine import post_journal_for_operation
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.inventory import InventoryLedger
from app.models.sale import CreditNote, SalesInvoice

SOURCE_CREDIT_NOTE = "credit_note"
KIND_REVENUE = "credit_note_revenue"
KIND_COGS = "credit_note_cogs"


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


def _sum_return_cogs(ledger_entries: List[InventoryLedger], credit_note_id: UUID) -> Decimal:
    total = Decimal("0")
    for e in ledger_entries:
        if e.reference_type == "credit_note" and e.reference_id == credit_note_id:
            total += abs(_money(e.total_cost))
    return total


def post_gl_for_credit_note(
    db: Session,
    credit_note: CreditNote,
    invoice: SalesInvoice,
    ledger_entries: List[InventoryLedger],
    *,
    posted_by: Optional[UUID],
) -> List[PostingResult]:
    if not invoice.customer_id:
        return []
    accounts = control_account_map(db, credit_note.company_id)
    exclusive = _money(credit_note.total_exclusive)
    vat = _money(credit_note.vat_amount)
    inclusive = _money(credit_note.total_inclusive)
    if inclusive <= 0:
        return []
    if exclusive <= 0 and inclusive > 0:
        exclusive = inclusive - vat
    results: List[PostingResult] = []
    rev_lines: List[PostingLineSpec] = [
        PostingLineSpec(
            account_id=accounts[CONTROL_REVENUE].id,
            debit=exclusive,
            description=f"Revenue reversal — {credit_note.credit_note_no}",
        ),
    ]
    if vat > 0:
        rev_lines.append(
            PostingLineSpec(
                account_id=accounts[CONTROL_VAT_OUTPUT].id,
                debit=vat,
                description=f"VAT output reversal — {credit_note.credit_note_no}",
            )
        )
    rev_lines.append(
        PostingLineSpec(
            account_id=accounts[CONTROL_AR].id,
            credit=inclusive,
            description=f"AR credit — {credit_note.credit_note_no}",
        )
    )
    results.append(
        post_journal_for_operation(
            db,
            company_id=credit_note.company_id,
            branch_id=credit_note.branch_id,
            posting_date=credit_note.credit_note_date,
            source_type=SOURCE_CREDIT_NOTE,
            source_id=credit_note.id,
            posting_kind=KIND_REVENUE,
            lines=rev_lines,
            posted_by=posted_by,
            description=f"Credit note revenue {credit_note.credit_note_no}",
            metadata={"credit_note_no": credit_note.credit_note_no},
        )
    )
    cogs = _sum_return_cogs(ledger_entries, credit_note.id)
    if cogs > 0:
        results.append(
            post_journal_for_operation(
                db,
                company_id=credit_note.company_id,
                branch_id=credit_note.branch_id,
                posting_date=credit_note.credit_note_date,
                source_type=SOURCE_CREDIT_NOTE,
                source_id=credit_note.id,
                posting_kind=KIND_COGS,
                lines=[
                    PostingLineSpec(
                        account_id=accounts[CONTROL_INVENTORY].id,
                        debit=cogs,
                        description="Stock return",
                    ),
                    PostingLineSpec(
                        account_id=accounts[CONTROL_COGS].id,
                        credit=cogs,
                        description="COGS reversal",
                    ),
                ],
                posted_by=posted_by,
                description=f"Credit note COGS {credit_note.credit_note_no}",
            )
        )
    return results
