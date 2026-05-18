"""
Operational AR: migrate customers.opening_balance into customer_ledger_entries.

Statement rendering must NOT read customers.opening_balance — only ledger rows
(entry_type=opening_balance). This module is used at create/update and by CLI backfill.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch
from app.models.customer import Customer
from app.models.customer_financial import CustomerLedgerEntry
from app.services.customer_ledger_service import CustomerLedgerService

ENTRY_OPENING = "opening_balance"


def resolve_opening_balance_branch_id(db: Session, company_id: UUID) -> Optional[UUID]:
    """HQ branch preferred; else earliest branch for company."""
    hq = (
        db.query(Branch.id)
        .filter(Branch.company_id == company_id, Branch.is_hq.is_(True))
        .order_by(Branch.created_at.asc())
        .first()
    )
    if hq:
        return hq[0]
    any_branch = (
        db.query(Branch.id)
        .filter(Branch.company_id == company_id)
        .order_by(Branch.created_at.asc())
        .first()
    )
    return any_branch[0] if any_branch else None


def has_opening_balance_ledger_entry(db: Session, *, company_id: UUID, customer_id: UUID) -> bool:
    return (
        db.query(CustomerLedgerEntry.id)
        .filter(
            CustomerLedgerEntry.company_id == company_id,
            CustomerLedgerEntry.customer_id == customer_id,
            CustomerLedgerEntry.entry_type == ENTRY_OPENING,
        )
        .first()
        is not None
    )


def ensure_opening_balance_ledger_entry(
    db: Session,
    *,
    customer: Customer,
    branch_id: UUID | None = None,
    entry_date=None,
) -> CustomerLedgerEntry | None:
    """
    Idempotent: creates one opening_balance ledger row when customers.opening_balance != 0
    and no opening row exists yet. Does not amend an existing row if the master field changed.
    """
    from datetime import date as date_type

    amount = Decimal(str(customer.opening_balance or 0))
    if amount == 0:
        return None
    if has_opening_balance_ledger_entry(db, company_id=customer.company_id, customer_id=customer.id):
        return None

    bid = branch_id or resolve_opening_balance_branch_id(db, customer.company_id)
    if not bid:
        return None

    ed = entry_date or date_type.today()
    debit = amount if amount > 0 else Decimal("0")
    credit = (-amount) if amount < 0 else Decimal("0")
    return CustomerLedgerService.create_entry(
        db,
        company_id=customer.company_id,
        branch_id=bid,
        customer_id=customer.id,
        entry_date=ed,
        entry_type=ENTRY_OPENING,
        reference_id=customer.id,
        debit=debit,
        credit=credit,
    )
