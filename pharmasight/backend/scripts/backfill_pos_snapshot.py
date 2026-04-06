#!/usr/bin/env python3
"""
Backfill item_branch_snapshot for company/branch/item combinations.

Run after applying migration 046 (table) and 049 (rename to item_branch_snapshot).
- Uses same logic as refresh_pos_snapshot_for_item (inventory_balances, ledger, purchase snapshot, pricing).
- Batched (batch_size items per commit) to avoid long locks.
- Idempotent: INSERT ... ON CONFLICT DO UPDATE.

Usage:
  cd pharmasight/backend && python -m scripts.backfill_pos_snapshot [--batch-size=200] [--company-id=UUID]
  cd pharmasight/backend && python -m scripts.backfill_pos_snapshot --company-id=... --quiet  # less SQL noise

  Full (Cartesian) backfill — DEFAULT when --inventory-only is omitted:
  Every active branch × every active item for the company. Use this when Excel had 0 stock:
  inventory_balances may be empty; snapshot rows still get current_stock=0 and items become searchable.

  inventory-only:
  Only (branch, item) pairs that already have a row in inventory_balances. Skip this when balances are empty.

  only-missing:
  Only (branch, item) pairs with NO item_branch_snapshot row yet. Use after a partial run / DNS blip — skips
  already-backfilled pairs so resume is much faster.
"""
import argparse
import logging
import sys

from sqlalchemy.exc import OperationalError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _enable_quiet_sql_logging() -> None:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="Backfill item_branch_snapshot")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Refresh this many (item,branch) pairs per commit (default 500)",
    )
    parser.add_argument("--company-id", type=str, default=None, help="Limit to one company UUID")
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Only backfill (item_id, branch_id) pairs that have inventory_balances (stock activity); faster for fixing skipped items",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Skip pairs that already have an item_branch_snapshot row (fast resume after errors or interrupt)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any pair was skipped due to errors",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress SQLAlchemy SQL echo (recommended for large full backfills)",
    )
    args = parser.parse_args()

    if args.quiet:
        _enable_quiet_sql_logging()

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
        skipped = 0
        batch_count = 0
        for (company_id,) in companies:
            cid = str(company_id)
            if args.inventory_only:
                if args.only_missing:
                    rows = db.execute(
                        text("""
                            SELECT DISTINCT ib.branch_id, ib.item_id
                            FROM inventory_balances ib
                            WHERE ib.company_id = CAST(:company_id AS uuid)
                              AND NOT EXISTS (
                                SELECT 1 FROM item_branch_snapshot s
                                WHERE s.company_id = ib.company_id
                                  AND s.branch_id = ib.branch_id
                                  AND s.item_id = ib.item_id
                              )
                        """),
                        {"company_id": cid},
                    ).fetchall()
                else:
                    rows = db.execute(
                        text("""
                            SELECT DISTINCT ib.branch_id, ib.item_id
                            FROM inventory_balances ib
                            WHERE ib.company_id = CAST(:company_id AS uuid)
                        """),
                        {"company_id": cid},
                    ).fetchall()
                pairs = [(company_id, r[0], r[1]) for r in rows]
                logger.info(
                    "Company %s: %s inventory pairs%s",
                    company_id,
                    len(pairs),
                    " (only missing snapshot)" if args.only_missing else "",
                )
            else:
                if args.only_missing:
                    rows = db.execute(
                        text("""
                            SELECT b.id AS branch_id, i.id AS item_id
                            FROM branches b
                            CROSS JOIN items i
                            WHERE b.company_id = CAST(:company_id AS uuid)
                              AND i.company_id = CAST(:company_id AS uuid)
                              AND b.is_active = true
                              AND i.is_active = true
                              AND NOT EXISTS (
                                SELECT 1 FROM item_branch_snapshot s
                                WHERE s.company_id = CAST(:company_id AS uuid)
                                  AND s.branch_id = b.id
                                  AND s.item_id = i.id
                              )
                        """),
                        {"company_id": cid},
                    ).fetchall()
                    pairs = [(company_id, r[0], r[1]) for r in rows]
                    n_br = db.execute(
                        text(
                            "SELECT COUNT(*) FROM branches WHERE company_id = CAST(:company_id AS uuid) AND is_active = true"
                        ),
                        {"company_id": cid},
                    ).scalar()
                    n_it = db.execute(
                        text(
                            "SELECT COUNT(*) FROM items WHERE company_id = CAST(:company_id AS uuid) AND is_active = true"
                        ),
                        {"company_id": cid},
                    ).scalar()
                    logger.info(
                        "Company %s: only-missing = %s pairs (of up to %s branches × %s items = %s)",
                        company_id,
                        len(pairs),
                        n_br,
                        n_it,
                        (n_br or 0) * (n_it or 0),
                    )
                else:
                    branches = db.query(Branch.id).filter(
                        Branch.company_id == company_id, Branch.is_active == True
                    ).all()
                    items = db.query(Item.id).filter(
                        Item.company_id == company_id, Item.is_active == True
                    ).all()
                    pairs = [(company_id, b, i) for (b,) in branches for (i,) in items]
                    logger.info(
                        "Company %s: full backfill %s branches × %s active items = %s snapshot rows",
                        company_id,
                        len(branches),
                        len(items),
                        len(pairs),
                    )

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
                    skipped += 1
                    logger.warning("Skip item %s branch %s: %s", item_id, branch_id, e)
                    db.rollback()
                    if isinstance(e, OperationalError) or (
                        e.__cause__ is not None and isinstance(e.__cause__, OperationalError)
                    ):
                        try:
                            db.connection().invalidate()
                        except Exception:
                            pass
                    batch_count = 0
            if batch_count:
                db.commit()
                batch_count = 0
        logger.info("Backfill complete. Total rows upserted: %s", total)
        if skipped:
            logger.warning(
                "%s pair(s) skipped due to errors — fix network/DNS/VPN, then re-run:\n"
                "  python -m scripts.backfill_pos_snapshot --company-id=<UUID> --only-missing --quiet",
                skipped,
            )
            if args.strict:
                sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
