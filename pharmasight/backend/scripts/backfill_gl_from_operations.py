"""
Backfill authoritative GL journals from operational documents for all companies (idempotent).

  cd pharmasight/backend
  python -m scripts.backfill_gl_from_operations [--company-id UUID] [--from-date YYYY-MM-DD] [--to-date YYYY-MM-DD] [--branch-id UUID] [--dry-run]

Runs per company in one transaction. Safe to re-run (skips duplicate idempotency keys).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from uuid import UUID

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.accounting.backfill_gl import backfill_company_gl
from app.database import SessionLocal
from app.models.company import Company


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill GL from operational documents")
    parser.add_argument("--company-id", default=None)
    parser.add_argument("--branch-id", default=None)
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to-date", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--dry-run", action="store_true", help="Count documents only")
    args = parser.parse_args()

    from_d = date.fromisoformat(args.from_date) if args.from_date else None
    to_d = date.fromisoformat(args.to_date) if args.to_date else None
    branch_id = UUID(args.branch_id) if args.branch_id else None

    db = SessionLocal()
    exit_code = 0
    try:
        q = db.query(Company)
        if args.company_id:
            q = q.filter(Company.id == UUID(args.company_id))
        companies = q.order_by(Company.name.asc()).all()
        if not companies:
            print("No companies found.")
            return 1

        for company in companies:
            print(f"\n=== {company.name!r} ({company.id}) ===")
            try:
                result = backfill_company_gl(
                    db,
                    company.id,
                    from_date=from_d,
                    to_date=to_d,
                    branch_id=branch_id,
                    dry_run=args.dry_run,
                )
                if args.dry_run:
                    print("dry_run_counts:", result.get("dry_run_counts"))
                else:
                    db.commit()
                    for key, val in result.items():
                        if key in ("company_id", "branch_id", "from_date", "to_date", "doctrine", "dry_run"):
                            continue
                        if isinstance(val, dict) and "attempted" in val:
                            print(f"  {key}: {val}")
                    print("  totals:", result.get("totals"))
            except Exception as e:
                db.rollback()
                exit_code = 1
                print(f"  FAILED: {e}")
    finally:
        db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
