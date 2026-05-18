"""
Idempotent backfill: customers.opening_balance -> customer_ledger_entries (opening_balance).

Run manually after migration 141:
  python -m scripts.backfill_customer_opening_balance_ledger [--dry-run]

Statement rendering does not read customers.opening_balance; this script materializes history.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.customer import Customer
from app.services.customer_opening_balance import ensure_opening_balance_ledger_entry, has_opening_balance_ledger_entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill customer opening balance ledger rows")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not commit")
    parser.add_argument("--company-id", default=None, help="Limit to one company UUID")
    args = parser.parse_args()

    db = SessionLocal()
    created = 0
    skipped = 0
    try:
        q = db.query(Customer)
        if args.company_id:
            from uuid import UUID

            q = q.filter(Customer.company_id == UUID(args.company_id))
        for customer in q.all():
            amt = Decimal(str(customer.opening_balance or 0))
            if amt == 0:
                skipped += 1
                continue
            if has_opening_balance_ledger_entry(db, company_id=customer.company_id, customer_id=customer.id):
                skipped += 1
                continue
            if args.dry_run:
                print(f"would create opening_balance for {customer.id} {customer.name!r} amount={amt}")
                created += 1
                continue
            entry = ensure_opening_balance_ledger_entry(db, customer=customer)
            if entry:
                created += 1
                print(f"created opening_balance ledger for {customer.id} {customer.name!r}")
            else:
                skipped += 1
        if not args.dry_run:
            db.commit()
        print(f"done: created={created} skipped={skipped} dry_run={args.dry_run}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
