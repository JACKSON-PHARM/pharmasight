#!/usr/bin/env python3
"""
Refresh item_branch_snapshot for all items whose name/sku/barcode matches a search term.

Use when snapshot search (single path) does not find an item that exists in the items table
(e.g. "doloact mr" not in dropdown). This populates or updates snapshot rows so the next search finds them.

Usage:
  cd pharmasight/backend
  python -m scripts.refresh_snapshot_for_search doloact
  python -m scripts.refresh_snapshot_for_search doloact --company-id UUID
"""
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Refresh item_branch_snapshot for items matching a search term (so snapshot search finds them)"
    )
    parser.add_argument("term", help="Search term (e.g. doloact, abz)")
    parser.add_argument("--company-id", type=str, default=None, help="Limit to one company UUID")
    parser.add_argument("--batch-size", type=int, default=50, help="Commit every N item×branch upserts")
    args = parser.parse_args()

    try:
        from sqlalchemy import or_, and_, func
        from app.database import SessionLocal
        from app.models import Branch, Item
        from app.services.pos_snapshot_service import refresh_pos_snapshot_for_item
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        sys.exit(1)

    term = (args.term or "").strip().lower()
    if len(term) < 2:
        logger.error("Search term must be at least 2 characters")
        sys.exit(1)

    pattern = f"%{term}%"
    db = SessionLocal()
    try:
        q = db.query(Item.id, Item.company_id, Item.name).filter(
            Item.is_active == True,
            or_(
                func.lower(Item.name).like(pattern),
                and_(Item.sku.isnot(None), func.lower(Item.sku).like(pattern)),
                and_(Item.barcode.isnot(None), func.lower(Item.barcode).like(pattern)),
            ),
        )
        if args.company_id:
            from uuid import UUID
            try:
                q = q.filter(Item.company_id == UUID(args.company_id))
            except ValueError:
                logger.error("Invalid company-id UUID: %s", args.company_id)
                sys.exit(1)
        items = q.all()
        if not items:
            logger.info("No active items match %r", term)
            return
        logger.info("Found %s item(s) matching %r", len(items), term)
        total = 0
        batch = 0
        for (item_id, company_id, name) in items:
            branches = db.query(Branch.id).filter(
                Branch.company_id == company_id, Branch.is_active == True
            ).all()
            for (branch_id,) in branches:
                try:
                    refresh_pos_snapshot_for_item(db, company_id, branch_id, item_id)
                    total += 1
                    batch += 1
                    if batch >= args.batch_size:
                        db.commit()
                        logger.info("Committed batch: %s total so far", total)
                        batch = 0
                except Exception as e:
                    logger.warning("Skip item %s branch %s: %s", item_id, branch_id, e)
                    db.rollback()
                    batch = 0
        if batch:
            db.commit()
        logger.info("Done. Refreshed %s snapshot row(s) for items matching %r. Search again to see them.", total, term)
    finally:
        db.close()


if __name__ == "__main__":
    main()
