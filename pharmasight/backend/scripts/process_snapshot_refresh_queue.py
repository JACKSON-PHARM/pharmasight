#!/usr/bin/env python3
"""
Process snapshot_refresh_queue in batches (background worker).

Run periodically via cron or a process manager. Each run processes up to --batch-size
pending jobs (branch-wide or single-item). Branch-wide jobs expand to all company items
for that branch.

Usage:
  cd pharmasight/backend && python -m scripts.process_snapshot_refresh_queue [--batch-size=50] [--once]
  With --once: process one batch and exit. Without: run in a loop every --interval seconds.
"""
import argparse
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Process snapshot_refresh_queue")
    parser.add_argument("--batch-size", type=int, default=50, help="Max jobs per batch")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between runs (when not --once)")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()

    try:
        from app.database import SessionLocal
        from app.services.snapshot_refresh_service import SnapshotRefreshService
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        raise SystemExit(1) from e

    while True:
        db = SessionLocal()
        try:
            n = SnapshotRefreshService.process_queue_batch(db, batch_size=args.batch_size)
            db.commit()
            if n:
                logger.info("Processed %s snapshot refresh job(s)", n)
        except Exception as e:
            logger.exception("Queue batch failed: %s", e)
            db.rollback()
        finally:
            db.close()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
