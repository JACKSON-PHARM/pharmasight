#!/usr/bin/env python3
"""
One-off correction: reconcile or mark sales invoice payment status for a branch.

Default scope: invoice_date strictly before the first day of the current calendar month
("last month and older").

Modes (dry run unless --apply):
  Default: fix invoices where non-insurance payments fully cover total_inclusive
           but payment_status is not PAID (rounding / stale status).

  --force-mark-paid: additionally mark all BATCHED invoices in scope as PAID
                     (historical correction — use only when collections are known complete).

Usage:
  cd pharmasight/backend
  python scripts/correct_branch_invoice_payments.py \\
    --branch-id bec5d46a-7f21-45ef-945c-8c68171aa386

  python scripts/correct_branch_invoice_payments.py \\
    --branch-id bec5d46a-7f21-45ef-945c-8c68171aa386 \\
    --force-mark-paid --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import normalize_postgres_url, settings
from app.models import Branch, SalesInvoice
from app.services.invoice_payment_status import (
    apply_payment_status_from_settled,
    is_fully_settled,
    sum_settled_payments,
)


def _first_day_of_current_month(today: date) -> date:
    return today.replace(day=1)


def main() -> None:
    p = argparse.ArgumentParser(description="Correct sales invoice payment status for a branch.")
    p.add_argument("--branch-id", required=True, help="Branch UUID")
    p.add_argument("--company-id", default="", help="Optional company UUID (resolved from branch if omitted)")
    p.add_argument(
        "--before-date",
        default="",
        help="Include invoices with invoice_date < this date (YYYY-MM-DD). "
        "Default: first day of current month.",
    )
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument("--apply", action="store_true", help="Persist changes (default: dry run).")
    p.add_argument(
        "--force-mark-paid",
        action="store_true",
        help="Mark all BATCHED invoices in scope as PAID (historical correction).",
    )
    args = p.parse_args()

    branch_id = UUID(str(args.branch_id).strip())
    cutoff = (
        date.fromisoformat(str(args.before_date).strip()[:10])
        if str(args.before_date).strip()
        else _first_day_of_current_month(date.today())
    )

    url = (args.database_url or "").strip() or settings.database_connection_string
    if not url:
        print("ERROR: No database URL. Set DATABASE_URL in .env or pass --database-url.")
        sys.exit(1)
    url = normalize_postgres_url(url)

    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as db:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            print(f"ERROR: Branch not found: {branch_id}")
            sys.exit(1)
        company_id = UUID(str(args.company_id).strip()) if str(args.company_id).strip() else branch.company_id

        q = (
            db.query(SalesInvoice)
            .filter(
                SalesInvoice.branch_id == branch_id,
                SalesInvoice.company_id == company_id,
                SalesInvoice.invoice_date < cutoff,
                SalesInvoice.status.in_(["BATCHED", "PAID"]),
            )
            .order_by(SalesInvoice.invoice_date, SalesInvoice.invoice_no)
        )
        invoices = q.all()

        sync_rows = []
        force_rows = []
        for inv in invoices:
            settled = sum_settled_payments(db, inv.id)
            needs_sync = is_fully_settled(inv, settled) and (inv.payment_status or "").upper() != "PAID"
            if needs_sync:
                sync_rows.append((inv, settled))
            if args.force_mark_paid and (inv.status or "").upper() == "BATCHED":
                if (inv.payment_status or "").upper() != "PAID":
                    force_rows.append((inv, settled))

        print("\n=== Branch invoice payment correction ===")
        print(f"Branch: {branch_id} ({getattr(branch, 'name', '')})")
        print(f"Company: {company_id}")
        print(f"Cutoff: invoice_date < {cutoff.isoformat()}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
        print(f"Invoices in scope (BATCHED/PAID): {len(invoices)}")
        print(f"Fully paid but wrong status (will sync): {len(sync_rows)}")
        if args.force_mark_paid:
            print(f"BATCHED to force PAID: {len(force_rows)}")

        if sync_rows:
            print("\n--- Sync fully paid (sample up to 30) ---")
            for inv, settled in sync_rows[:30]:
                print(
                    f"  {inv.invoice_no} | date={inv.invoice_date} | "
                    f"paid={settled} / total={inv.total_inclusive} | "
                    f"status={inv.status} payment_status={inv.payment_status}"
                )
            if len(sync_rows) > 30:
                print(f"  ... and {len(sync_rows) - 30} more")

        if args.force_mark_paid and force_rows:
            print("\n--- Force mark PAID (sample up to 30) ---")
            for inv, settled in force_rows[:30]:
                print(
                    f"  {inv.invoice_no} | date={inv.invoice_date} | "
                    f"paid={settled} / total={inv.total_inclusive} | "
                    f"payment_status={inv.payment_status}"
                )
            if len(force_rows) > 30:
                print(f"  ... and {len(force_rows) - 30} more")

        if not args.apply:
            print("\nDry run complete. Re-run with --apply to persist.")
            if args.force_mark_paid:
                print("Use: --force-mark-paid --apply for historical mark-all-paid correction.")
            return

        updated = 0
        touched_ids = set()
        try:
            for inv, settled in sync_rows:
                apply_payment_status_from_settled(inv, settled)
                touched_ids.add(inv.id)
                updated += 1
            if args.force_mark_paid:
                for inv, settled in force_rows:
                    if inv.id in touched_ids:
                        continue
                    inv.payment_status = "PAID"
                    inv.status = "PAID"
                    inv.cashier_approved = True
                    if not inv.approved_at:
                        inv.approved_at = datetime.now(timezone.utc)
                    updated += 1
                    touched_ids.add(inv.id)
            db.commit()
            print(f"\nApplied updates to {updated} invoice(s).")
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    main()
