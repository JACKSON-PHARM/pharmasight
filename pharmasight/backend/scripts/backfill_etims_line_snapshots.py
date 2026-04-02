#!/usr/bin/env python3
"""
Backfill eTIMS line snapshot columns + submission_status=pending for BATCHED/PAID
invoices with submission_status IS NULL (legacy / pre-snapshot).

Usage:
  cd pharmasight/backend && python -m scripts.backfill_etims_line_snapshots [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill eTIMS snapshots on batched invoices")
    parser.add_argument("--dry-run", action="store_true", help="Report only; no commit")
    args = parser.parse_args()

    try:
        from app.database import SessionLocal
        from app.models import Item, SalesInvoice
        from app.services.etims.invoice_etims_snapshot import apply_etims_snapshots_on_batch
        from sqlalchemy.orm import selectinload
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        sys.exit(1)

    db = SessionLocal()
    try:
        rows = (
            db.query(SalesInvoice)
            .options(selectinload(SalesInvoice.items))
            .filter(
                SalesInvoice.status.in_(("BATCHED", "PAID")),
                SalesInvoice.submission_status.is_(None),
            )
            .all()
        )
        n = 0
        for inv in rows:
            for line in inv.items:
                if line.item is None:
                    line.item = db.query(Item).filter(Item.id == line.item_id).first()
            if args.dry_run:
                logger.info("[dry-run] would backfill invoice %s %s", inv.id, inv.invoice_no)
                n += 1
                continue
            apply_etims_snapshots_on_batch(inv)
            n += 1
        if args.dry_run:
            logger.info("Dry run: %s invoice(s) would be updated", n)
        else:
            db.commit()
            logger.info("Backfilled %s invoice(s)", n)
    except Exception as e:
        logger.exception("Backfill failed: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
