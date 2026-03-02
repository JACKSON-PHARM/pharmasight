#!/usr/bin/env python3
"""
Backfill item_branch_snapshot for company/branch/item combinations.

Run after applying migration 046 (table) and 049 (rename to item_branch_snapshot).
- Uses same logic as refresh_pos_snapshot_for_item (inventory_balances, ledger, purchase snapshot, pricing).
- Batched (batch_size items per commit) to avoid long locks.
- Idempotent: INSERT ... ON CONFLICT DO UPDATE.

Usage:
  cd pharmasight/backend && python -m scripts.backfill_pos_snapshot [--batch-size=200] [--company-id=UUID]
  cd pharmasight/backend && python -m scripts.backfill_pos_snapshot --inventory-only  # Only items with stock (faster)
"""
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Backfill item_branch_snapshot")
    parser.add_argument("--batch-size", type=int, default=200, help="Items per commit")
    parser.add_argument("--company-id", type=str, default=None, help="Limit to one company UUID")
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Only backfill (item_id, branch_id) pairs that have inventory_balances (stock activity); faster for fixing skipped items",
    )
    args = parser.parse_args()

    try:
        from app.database import SessionLocal
        from app.models import Company, Branch, Item
        from sqlalchemy import text
        from app.services.pos_snapshot_service import refresh_pos_snapshot_for_item
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        sys.exit(1)

    db = SessionLocal()
    try:
        companies = db.query(Company.id).all()
        if args.company_id:
            companies = [c for c in companies if str(c.id) == args.company_id]
            if not companies:
                logger.error("Company %s not found", args.company_id)
                sys.exit(1)
        total = 0
        batch_count = 0
        for (company_id,) in companies:
            if args.inventory_only:
                rows = db.execute(
                    text("""
                        SELECT DISTINCT ib.branch_id, ib.item_id
                        FROM inventory_balances ib
                        WHERE ib.company_id = :company_id
                    """),
                    {"company_id": str(company_id)},
                ).fetchall()
                pairs = [(company_id, r[0], r[1]) for r in rows]
                logger.info("Company %s: %s (item, branch) pairs with inventory", company_id, len(pairs))
            else:
                branches = db.query(Branch.id).filter(
                    Branch.company_id == company_id, Branch.is_active == True
                ).all()
                items = db.query(Item.id).filter(
                    Item.company_id == company_id, Item.is_active == True
                ).all()
                pairs = [(company_id, b[0], i[0]) for (b,) in branches for (i,) in items]

            for company_id, branch_id, item_id in pairs:
                try:
                    refresh_pos_snapshot_for_item(db, company_id, branch_id, item_id)
                    total += 1
                    batch_count += 1
                    if batch_count >= args.batch_size:
                        db.commit()
                        logger.info("Committed batch: %s total so far", total)
                        batch_count = 0
                except Exception as e:
                    logger.warning("Skip item %s branch %s: %s", item_id, branch_id, e)
                    db.rollback()
                    batch_count = 0
            if batch_count:
                db.commit()
                batch_count = 0
        logger.info("Backfill complete. Total rows upserted: %s", total)
    finally:
        db.close()


if __name__ == "__main__":
    main()
