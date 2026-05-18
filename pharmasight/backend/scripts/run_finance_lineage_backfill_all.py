#!/usr/bin/env python3
"""
One-time controlled financial event backfill for all companies/branches (E5).

Materializes lineage from existing operational records (idempotent). Does not mutate
operational truth or financial_events already emitted.

Usage (from pharmasight/backend):
  # Preview scope
  python scripts/run_finance_lineage_backfill_all.py --dry-run

  # Execute (requires explicit confirmation)
  python scripts/run_finance_lineage_backfill_all.py --yes

  # Single company
  python scripts/run_finance_lineage_backfill_all.py --yes --company-id <uuid>

  # Fixed date window
  python scripts/run_finance_lineage_backfill_all.py --yes --since 2020-01-01 --until 2026-05-18

  # After backfill, replay unresolved emission failures per company
  python scripts/run_finance_lineage_backfill_all.py --yes --replay-failures
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from uuid import UUID

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import func

from app.database import SessionLocal
from app.finance.events.backfill import run_controlled_backfill
from app.finance.events.replay import replay_unresolved_failures
from app.models import Branch, CashbookEntry, Company, Expense, FinancialEvent, SalesInvoice


@dataclass
class BranchPlan:
    company_id: UUID
    company_name: str
    branch_id: UUID
    branch_name: str
    date_from: date
    date_to: date
    cashbook_rows: int
    existing_events: int


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _safe_print(msg: str) -> None:
    """Avoid Windows charmap failures on summary lines (backfill still commits)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _min_operational_date(db, company_id: UUID, branch_id: UUID) -> Optional[date]:
    candidates: List[date] = []

    cb = (
        db.query(func.min(CashbookEntry.date))
        .filter(CashbookEntry.company_id == company_id, CashbookEntry.branch_id == branch_id)
        .scalar()
    )
    if cb:
        candidates.append(cb)

    inv = (
        db.query(func.min(SalesInvoice.invoice_date))
        .filter(SalesInvoice.company_id == company_id, SalesInvoice.branch_id == branch_id)
        .scalar()
    )
    if inv:
        candidates.append(inv)

    exp = (
        db.query(func.min(Expense.expense_date))
        .filter(
            Expense.company_id == company_id,
            Expense.branch_id == branch_id,
            Expense.status == "approved",
        )
        .scalar()
    )
    if exp:
        candidates.append(exp)

    if not candidates:
        return None
    return min(candidates)


def _count_events(db, company_id: UUID, branch_id: UUID) -> int:
    return (
        db.query(func.count(FinancialEvent.id))
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.branch_id == branch_id,
        )
        .scalar()
        or 0
    )


def build_plans(
    db,
    *,
    since_floor: Optional[date],
    until: date,
    company_id_filter: Optional[UUID],
    active_only: bool,
) -> List[BranchPlan]:
    company_q = db.query(Company)
    if company_id_filter:
        company_q = company_q.filter(Company.id == company_id_filter)
    if active_only:
        company_q = company_q.filter(Company.is_active.is_(True))

    plans: List[BranchPlan] = []
    for company in company_q.order_by(Company.name).all():
        branch_q = db.query(Branch).filter(Branch.company_id == company.id)
        if active_only:
            branch_q = branch_q.filter(Branch.is_active.is_(True))
        for branch in branch_q.order_by(Branch.name).all():
            op_min = _min_operational_date(db, company.id, branch.id)
            if op_min is None:
                continue
            date_from = op_min
            if since_floor and since_floor > date_from:
                date_from = since_floor
            if company.fiscal_start_date and company.fiscal_start_date > date_from:
                date_from = company.fiscal_start_date
            if date_from > until:
                continue

            cb_count = (
                db.query(func.count(CashbookEntry.id))
                .filter(
                    CashbookEntry.company_id == company.id,
                    CashbookEntry.branch_id == branch.id,
                    CashbookEntry.date >= date_from,
                    CashbookEntry.date <= until,
                )
                .scalar()
                or 0
            )

            plans.append(
                BranchPlan(
                    company_id=company.id,
                    company_name=company.name or str(company.id),
                    branch_id=branch.id,
                    branch_name=branch.name or str(branch.id),
                    date_from=date_from,
                    date_to=until,
                    cashbook_rows=int(cb_count),
                    existing_events=_count_events(db, company.id, branch.id),
                )
            )
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Controlled finance lineage backfill for all companies (CLI only)"
    )
    parser.add_argument("--dry-run", action="store_true", help="List planned runs only")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation (required to execute)",
    )
    parser.add_argument("--company-id", type=str, default=None, help="Limit to one company UUID")
    parser.add_argument("--since", type=str, default=None, help="Earliest date YYYY-MM-DD (floor)")
    parser.add_argument("--until", type=str, default=None, help="End date YYYY-MM-DD (default today)")
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive companies/branches",
    )
    parser.add_argument(
        "--replay-failures",
        action="store_true",
        help="After backfill, replay unresolved emission failures per company",
    )
    parser.add_argument("--replay-limit", type=int, default=500)
    args = parser.parse_args()

    until = date.fromisoformat(args.until) if args.until else _today()
    since_floor = date.fromisoformat(args.since) if args.since else None
    company_filter = UUID(args.company_id) if args.company_id else None

    db = SessionLocal()
    try:
        plans = build_plans(
            db,
            since_floor=since_floor,
            until=until,
            company_id_filter=company_filter,
            active_only=not args.include_inactive,
        )

        if not plans:
            print("No branches with operational data in scope.")
            return 0

        print(f"Planned backfill: {len(plans)} branch(es), until={until}")
        print("-" * 72)
        for p in plans:
            print(
                f"  {p.company_name} / {p.branch_name}\n"
                f"    {p.date_from} -> {p.date_to}  |  cashbook rows: {p.cashbook_rows}  |  "
                f"existing events: {p.existing_events}"
            )
        print("-" * 72)

        if args.dry_run:
            print("Dry run — no backfill executed.")
            return 0

        if not args.yes:
            print("Refusing to run without --yes (one-time operational command).")
            print("Re-run with: python scripts/run_finance_lineage_backfill_all.py --yes")
            return 1

        totals = {"created": 0, "duplicate": 0, "failed": 0, "branches_ok": 0, "branches_err": 0}
        companies_touched: set[UUID] = set()

        for i, p in enumerate(plans, 1):
            before = _count_events(db, p.company_id, p.branch_id)
            print(
                f"[{i}/{len(plans)}] Backfill {p.company_name} / {p.branch_name} "
                f"({p.date_from} -> {p.date_to})..."
            )
            try:
                outcome = run_controlled_backfill(
                    db,
                    company_id=p.company_id,
                    branch_id=p.branch_id,
                    date_from=p.date_from,
                    date_to=p.date_to,
                    actor_user_id=None,
                )
            except Exception as exc:
                totals["branches_err"] += 1
                _safe_print(f"    ERROR: {exc}")
                continue
            after = _count_events(db, p.company_id, p.branch_id)
            totals["created"] += outcome.events_created
            totals["duplicate"] += outcome.events_duplicate
            totals["failed"] += outcome.events_failed
            totals["branches_ok"] += 1
            companies_touched.add(p.company_id)
            _safe_print(
                f"    status={outcome.status} run={outcome.run_id} "
                f"emitter_counts(created/dupe/fail)={outcome.events_created}/"
                f"{outcome.events_duplicate}/{outcome.events_failed} "
                f"events_in_db: {before} -> {after} (+{after - before})"
            )

        print("=" * 72)
        print(
            f"Done. branches_ok={totals['branches_ok']} branches_err={totals['branches_err']} "
            f"run_totals(created/dupe/fail)={totals['created']}/{totals['duplicate']}/{totals['failed']}"
        )

        if args.replay_failures:
            print("Replaying unresolved emission failures per company...")
            for cid in companies_touched:
                outcomes = replay_unresolved_failures(
                    db, company_id=cid, actor_user_id=None, limit=args.replay_limit
                )
                print(f"  company {cid}: replayed {len(outcomes)} failure(s)")

        print("Re-run Treasury Reconciliation in Finance Operations to validate coverage.")
        return 0 if totals["branches_err"] == 0 else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
