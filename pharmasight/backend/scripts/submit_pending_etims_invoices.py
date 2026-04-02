#!/usr/bin/env python3
"""
Process sales invoices with submission_status=pending and submit to KRA OSCU.

Run via cron or process manager (same pattern as process_snapshot_refresh_queue).

Usage:
  cd pharmasight/backend && python -m scripts.submit_pending_etims_invoices [--limit N] [--once]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit pending eTIMS sales invoices")
    parser.add_argument("--limit", type=int, default=25, help="Max invoices per run")
    parser.add_argument("--once", action="store_true", help="Single run then exit")
    parser.add_argument("--interval", type=float, default=120.0, help="Seconds between runs (if not --once)")
    args = parser.parse_args()

    try:
        from app.database import SessionLocal
        from app.services.etims.etims_submission_processor import process_pending_etims_submissions
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        sys.exit(1)

    while True:
        db = SessionLocal()
        try:
            summary = process_pending_etims_submissions(db, limit=args.limit)
            logger.info(
                "eTIMS batch: candidates=%s ok=%s failed=%s skipped=%s errors=%s",
                summary.get("candidates"),
                summary.get("submitted_ok"),
                summary.get("failed"),
                summary.get("skipped"),
                len(summary.get("errors") or []),
            )
            for err in summary.get("errors") or []:
                logger.warning("eTIMS error: %s", err)
        except Exception as e:
            logger.exception("eTIMS worker run failed: %s", e)
            db.rollback()
        finally:
            db.close()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
