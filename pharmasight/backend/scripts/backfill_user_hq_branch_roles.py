#!/usr/bin/env python3
"""
Assign users with no branch roles in a company to that company's HQ branch (default staff role).

Usage:
  python scripts/backfill_user_hq_branch_roles.py
  python scripts/backfill_user_hq_branch_roles.py --company-id 9c71915e-3e59-45d5-9719-56d2322ff673
  python scripts/backfill_user_hq_branch_roles.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func

from app.database import SessionLocal
from app.models.company import Branch, Company
from app.models.user import User, UserBranchRole
from app.services.branch_provisioning_service import (
    branch_ids_assigned_to_user,
    ensure_user_assigned_to_company_hq,
    hq_branch_for_company,
)
from app.services.company_context import company_ids_for_user


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill HQ branch roles for users without branch access")
    parser.add_argument("--company-id", type=str, default=None, help="Limit to one company UUID")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not commit")
    args = parser.parse_args()

    company_filter = None
    if args.company_id:
        company_filter = UUID(args.company_id.strip())

    db = SessionLocal()
    try:
        companies = db.query(Company).order_by(Company.name)
        if company_filter:
            companies = companies.filter(Company.id == company_filter)
        companies = companies.all()
        if len(companies) > 1 and not company_filter:
            print(
                "Multiple companies in DB — pass --company-id to avoid assigning users to the wrong org.",
                file=sys.stderr,
            )
            return 2

        total_added = 0
        for company in companies:
            hq = hq_branch_for_company(db, company.id)
            if not hq:
                print(f"SKIP {company.name} ({company.id}): no branches")
                continue

            users = (
                db.query(User)
                .filter(User.is_active.is_(True), User.deleted_at.is_(None))
                .order_by(func.lower(User.username))
                .all()
            )
            for user in users:
                if branch_ids_assigned_to_user(db, user.id, company.id):
                    continue
                if company_ids_for_user(db, user.id):
                    continue
                print(
                    f"{'WOULD assign' if args.dry_run else 'Assign'} "
                    f"{user.username or user.email} -> HQ {hq.name} ({hq.id}) @ {company.name}"
                )
                if not args.dry_run:
                    if ensure_user_assigned_to_company_hq(db, user.id, company.id, commit=False):
                        total_added += 1
            if not args.dry_run:
                db.commit()

        if args.dry_run:
            print("Dry run complete (no changes committed).")
        else:
            print(f"Done. New HQ assignments: {total_added}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
