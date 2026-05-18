"""
Seed opening GL balances per branch from operational subledgers (inventory valuation + cashbook).

  python -m scripts.seed_opening_gl_balances [--company-id UUID] [--as-of-date YYYY-MM-DD]

Idempotent: skips branches that already have a POSTED opening_balance journal.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.constants import CONTROL_CASH, CONTROL_INVENTORY, CONTROL_RETAINED_EARNINGS
from app.accounting.coa_service import control_account_map, provision_default_chart_of_accounts
from app.accounting.fiscal_period_service import ensure_company_accounting_ready
from app.accounting.inventory_valuation import branch_inventory_valuation
from app.accounting.posting.engine import build_idempotency_key, post_journal_safe
from app.accounting.posting.types import PostingLineSpec
from app.accounting.reconciliation.control_accounts import cashbook_derived_balance
from app.database import SessionLocal
from app.models.accounting import GlJournalEntry
from app.models.company import Branch, Company

SOURCE_BRANCH = "branch"
KIND_OPENING = "opening_balance"


def _opening_already_posted(db, company_id: UUID, branch_id: UUID) -> bool:
    key = build_idempotency_key(SOURCE_BRANCH, branch_id, KIND_OPENING)
    return (
        db.query(GlJournalEntry.id)
        .filter(
            GlJournalEntry.company_id == company_id,
            GlJournalEntry.idempotency_key == key,
            GlJournalEntry.status == "POSTED",
        )
        .first()
        is not None
    )


def seed_branch_opening(
    db,
    *,
    company_id: UUID,
    branch_id: UUID,
    as_of: date,
    dry_run: bool,
) -> str:
    if _opening_already_posted(db, company_id, branch_id):
        return "skipped_existing"

    inv_val = branch_inventory_valuation(
        db, company_id=company_id, branch_id=branch_id, as_of_date=as_of
    )
    cash_val = cashbook_derived_balance(
        db, company_id=company_id, branch_id=branch_id, as_of_date=as_of
    )
    total = inv_val + cash_val
    if total <= 0:
        return "skipped_zero"

    accounts = control_account_map(db, company_id)
    inv_acct = accounts[CONTROL_INVENTORY]
    cash_acct = accounts[CONTROL_CASH]
    equity_acct = accounts[CONTROL_RETAINED_EARNINGS]

    lines = []
    if inv_val > 0:
        lines.append(
            PostingLineSpec(
                account_id=inv_acct.id,
                debit=inv_val,
                description="Opening inventory (operational valuation)",
            )
        )
    if cash_val > 0:
        lines.append(
            PostingLineSpec(
                account_id=cash_acct.id,
                debit=cash_val,
                description="Opening cash (cashbook-derived)",
            )
        )
    lines.append(
        PostingLineSpec(
            account_id=equity_acct.id,
            credit=total,
            description="Opening equity offset",
        )
    )

    if dry_run:
        return f"dry_run inv={inv_val} cash={cash_val} equity_cr={total}"

    ensure_company_accounting_ready(db, company_id, as_of)
    result = post_journal_safe(
        db,
        company_id=company_id,
        branch_id=branch_id,
        posting_date=as_of,
        source_type=SOURCE_BRANCH,
        source_id=branch_id,
        posting_kind=KIND_OPENING,
        lines=lines,
        posted_by=None,
        description=f"Opening balances branch {branch_id}",
        metadata={"inventory": str(inv_val), "cash": str(cash_val)},
    )
    if result.created:
        return f"posted journal={result.journal_entry_id}"
    return f"failed {result.message}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", default=None)
    parser.add_argument("--as-of-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of_date) if args.as_of_date else date.today()

    db = SessionLocal()
    try:
        q = db.query(Company)
        if args.company_id:
            q = q.filter(Company.id == UUID(args.company_id))
        for company in q.all():
            provision_default_chart_of_accounts(db, company.id)
            branches = db.query(Branch).filter(Branch.company_id == company.id).all()
            for branch in branches:
                status = seed_branch_opening(
                    db,
                    company_id=company.id,
                    branch_id=branch.id,
                    as_of=as_of,
                    dry_run=args.dry_run,
                )
                print(f"{company.name!r} branch {branch.id}: {status}")
            if not args.dry_run:
                db.commit()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
