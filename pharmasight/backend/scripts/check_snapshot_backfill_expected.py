#!/usr/bin/env python3
"""
Validate item_branch_snapshot backfill completeness.

Expected = sum over each company of (active_items × active_branches).
The backfill only processes Item.is_active=True and Branch.is_active=True.

If there is a gap, users may not find items in search and create duplicates,
or see wrong/zero stock. Always validate after backfill and fix gaps (re-run
backfill or refresh_snapshot_for_search for missing items).

Usage:
  cd pharmasight/backend && python -m scripts.check_snapshot_backfill_expected
  python -m scripts.check_snapshot_backfill_expected --strict          # exit 1 if gap
  python -m scripts.check_snapshot_backfill_expected --show-missing    # list missing (item_id, branch_id) per company
  python -m scripts.check_snapshot_backfill_expected --show-missing --limit=200
"""
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Validate item_branch_snapshot backfill")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 if expected != actual")
    parser.add_argument("--show-missing", action="store_true", help="Print sample of missing (company, item_id, branch_id) pairs")
    parser.add_argument("--limit", type=int, default=50, help="Max missing pairs to show (default 50)")
    args = parser.parse_args()

    try:
        from app.database import SessionLocal
        from app.models import Company, Branch, Item
        from sqlalchemy import text
    except ImportError as e:
        print("Import failed. Run from backend with PYTHONPATH=.", e)
        sys.exit(1)

    db = SessionLocal()
    try:
        # Actual snapshot row count
        actual = db.execute(text("SELECT COUNT(*) FROM item_branch_snapshot")).scalar() or 0

        # Per-company: active items, active branches, expected snapshot rows
        companies = db.query(Company.id, Company.name).all()
        total_expected = 0
        company_expected = {}
        print("Company (active items × active branches) = expected snapshot rows")
        print("-" * 60)
        for (company_id, company_name) in companies:
            active_items = db.query(Item.id).filter(
                Item.company_id == company_id, Item.is_active == True
            ).count()
            active_branches = db.query(Branch.id).filter(
                Branch.company_id == company_id, Branch.is_active == True
            ).count()
            expected = active_items * active_branches
            total_expected += expected
            company_expected[str(company_id)] = (expected, company_name or str(company_id))
            name = (company_name or str(company_id))[:40]
            print(f"  {name}: {active_items} × {active_branches} = {expected}")

        all_items = db.query(Item.id).filter(Item.is_active == True).count()
        all_inactive_items = db.query(Item.id).filter(Item.is_active == False).count()
        all_branches = db.query(Branch.id).filter(Branch.is_active == True).count()

        print("-" * 60)
        print(f"Total expected snapshot rows: {total_expected}")
        print(f"Actual item_branch_snapshot rows: {actual}")
        gap = total_expected - actual
        if total_expected != actual:
            print(f"Gap: {gap} (backfill incomplete — run backfill or refresh_snapshot_for_search for missing items)")
        print()
        print("Note: Backfill only includes Item.is_active=True and Branch.is_active=True.")
        print(f"Active items group-wide: {all_items}; inactive: {all_inactive_items}; active branches: {all_branches}")

        if args.show_missing and gap > 0:
            # Find (company_id, item_id, branch_id) that should exist but don't
            limit = max(1, min(args.limit, 500))
            missing = db.execute(text("""
                WITH expected AS (
                    SELECT i.company_id, i.id AS item_id, b.id AS branch_id
                    FROM items i
                    CROSS JOIN branches b
                    WHERE i.company_id = b.company_id
                      AND i.is_active = true
                      AND b.is_active = true
                ),
                actual AS (
                    SELECT company_id, item_id, branch_id FROM item_branch_snapshot
                )
                SELECT e.company_id, e.item_id, e.branch_id
                FROM expected e
                LEFT JOIN actual a ON a.company_id = e.company_id AND a.item_id = e.item_id AND a.branch_id = e.branch_id
                WHERE a.item_id IS NULL
                LIMIT :lim
            """), {"lim": limit}).fetchall()
            print()
            print(f"Sample of missing snapshot rows (up to {len(missing)}):")
            for row in missing:
                print(f"  company_id={row[0]} item_id={row[1]} branch_id={row[2]}")

        if args.strict and total_expected != actual:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
