#!/usr/bin/env python3
"""
Process snapshot_refresh_queue in batches (background worker).

Run periodically via cron or a process manager. Each run processes up to --batch-size
pending jobs (branch-wide or single-item). Branch-wide jobs expand to all company items
for that branch.

Usage:
  cd pharmasight/backend && python -m scripts.process_snapshot_refresh_queue [--batch-size=50] [--once]
  Night batch (faster): --once --quiet --chunk-size=1000
"""
import argparse
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _enable_quiet_mode() -> None:
    """Suppress SQL logging to speed up batch refresh."""
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="Process snapshot_refresh_queue")
    parser.add_argument("--batch-size", type=int, default=50, help="Max jobs per batch")
    parser.add_argument("--chunk-size", type=int, default=None, metavar="N", help="Items per commit for branch-wide (default 200). Use 1000 for night runs.")
    parser.add_argument("--quiet", action="store_true", help="Suppress SQL logging (faster).")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between runs (when not --once)")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()

    if args.quiet:
        _enable_quiet_mode()

    try:
        from app.database import SessionLocal
        from app.services.snapshot_refresh_service import SnapshotRefreshService
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        raise SystemExit(1) from e

    while True:
        db = SessionLocal()
        try:
            n = SnapshotRefreshService.process_queue_batch(
                db,
                batch_size=args.batch_size,
                branch_wide_chunk_size=args.chunk_size,
            )
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
