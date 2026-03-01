#!/usr/bin/env python3
"""
Backfill item_branch_snapshot for all company/branch/item combinations.

Run after applying migration 046 (table) and 049 (rename to item_branch_snapshot).
- Uses same logic as refresh_pos_snapshot_for_item (inventory_balances, ledger, purchase snapshot, pricing).
- Batched (batch_size items per commit) to avoid long locks.
- Idempotent: INSERT ... ON CONFLICT DO UPDATE.

Usage:
  cd pharmasight/backend && python -m scripts.backfill_pos_snapshot [--batch-size=200] [--company-id=UUID]
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
    args = parser.parse_args()

    try:
        from app.database import SessionLocal
        from app.models import Company, Branch, Item
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
            branches = db.query(Branch.id).filter(Branch.company_id == company_id, Branch.is_active == True).all()
            items = db.query(Item.id).filter(Item.company_id == company_id, Item.is_active == True).all()
            for (branch_id,) in branches:
                for (item_id,) in items:
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
