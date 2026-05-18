"""GL posting for manual stock adjustments."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.accounting.constants import CONTROL_INVENTORY, CONTROL_INVENTORY_SHRINKAGE
from app.accounting.coa_service import control_account_map
from app.accounting.posting.engine import post_journal_for_operation
from app.accounting.posting.types import PostingLineSpec, PostingResult
from app.models.inventory import InventoryLedger

SOURCE_STOCK_ADJUSTMENT = "inventory_ledger"
KIND_ADJUSTMENT = "stock_adjustment"


def _money(v) -> Decimal:
    return Decimal(str(v or 0))


def post_gl_for_stock_adjustment(
    db: Session,
    ledger_entry: InventoryLedger,
    *,
    posted_by: Optional[UUID],
) -> PostingResult:
    total_cost = abs(_money(ledger_entry.total_cost))
    if total_cost <= 0:
        return PostingResult(False, None, "zero_cost")
    accounts = control_account_map(db, ledger_entry.company_id)
    inv = accounts[CONTROL_INVENTORY]
    shrink = accounts[CONTROL_INVENTORY_SHRINKAGE]
    qty = _money(ledger_entry.quantity_delta)
    from datetime import date as date_type

    if ledger_entry.created_at:
        posting_date = ledger_entry.created_at.date()
    else:
        posting_date = date_type.today()

    if qty > 0:
        lines = [
            PostingLineSpec(account_id=inv.id, debit=total_cost, description="Stock increase"),
            PostingLineSpec(account_id=shrink.id, credit=total_cost, description="Adjustment offset"),
        ]
    else:
        lines = [
            PostingLineSpec(account_id=shrink.id, debit=total_cost, description="Shrinkage/adjustment"),
            PostingLineSpec(account_id=inv.id, credit=total_cost, description="Stock decrease"),
        ]
    return post_journal_for_operation(
        db,
        company_id=ledger_entry.company_id,
        branch_id=ledger_entry.branch_id,
        posting_date=posting_date,
        source_type=SOURCE_STOCK_ADJUSTMENT,
        source_id=ledger_entry.id,
        posting_kind=KIND_ADJUSTMENT,
        lines=lines,
        posted_by=posted_by,
        description=f"Stock adjustment {ledger_entry.id}",
        metadata={"quantity_delta": str(qty)},
    )
