#!/usr/bin/env python3
"""
Standalone snapshot refresh runner with progress reporting.

Run from pharmasight/backend with PYTHONPATH=. so that 'app' resolves.

Usage:
  # Show queue status (pending jobs, estimated items per branch)
  python -m scripts.run_snapshot_refresh_with_progress --status

  # Process one batch of the queue and log progress (then exit)
  python -m scripts.run_snapshot_refresh_with_progress --once

  # Night batch (high throughput): quiet + large chunks. Run in one terminal per branch
  # to process multiple branches in parallel, or one process to run branches sequentially.
  python -m scripts.run_snapshot_refresh_with_progress --once --quiet --chunk-size=1000

  # Process queue in a loop every 60s with progress (background worker)
  python -m scripts.run_snapshot_refresh_with_progress
"""
import argparse
import logging
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _enable_quiet_mode() -> None:
    """Suppress SQL and noisy loggers to speed up batch refresh (less I/O)."""
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)
    # Keep our script and app.service loggers at INFO so progress still shows
    logger.setLevel(logging.INFO)


def _progress_callback(event: str, **kwargs) -> None:
    """Log progress events to stdout with timestamps."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if event == "job_start":
        job_type = kwargs.get("job_type", "?")
        cid = kwargs.get("company_id", "")
        bid = kwargs.get("branch_id", "")
        iid = kwargs.get("item_id")
        if job_type == "branch_wide":
            print(f"[{ts}] Starting branch-wide refresh (company={str(cid)[:8]}..., branch={str(bid)[:8]}...)")
        else:
            print(f"[{ts}] Starting single-item refresh (item={iid})")
    elif event == "branch_total":
        total = kwargs.get("total_items", 0)
        print(f"[{ts}] Branch has {total} active items to refresh")
    elif event == "chunk_done":
        refreshed = kwargs.get("refreshed_so_far", 0)
        total = kwargs.get("total_items", 1)
        pct = kwargs.get("percent", 0)
        print(f"[{ts}] Progress: {refreshed}/{total} items ({pct}%)")
    elif event == "job_done":
        job_type = kwargs.get("job_type", "?")
        success = kwargs.get("success", False)
        err = kwargs.get("error")
        if success:
            print(f"[{ts}] Job finished successfully ({job_type})")
        else:
            print(f"[{ts}] Job failed ({job_type}): {err}")


def run_status(db) -> None:
    """Analyze snapshot_refresh_queue: pending, in progress, and estimated items per branch."""
    from sqlalchemy import text

    # Pending (not processed, not claimed or claimed >1h ago)
    pending = db.execute(
        text("""
            SELECT id, company_id, branch_id, item_id, reason, created_at
            FROM snapshot_refresh_queue
            WHERE processed_at IS NULL
              AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '1 hour')
            ORDER BY created_at ASC
        """)
    ).fetchall()

    # In progress (claimed, not processed)
    in_progress = db.execute(
        text("""
            SELECT id, company_id, branch_id, item_id, reason, claimed_at
            FROM snapshot_refresh_queue
            WHERE processed_at IS NULL AND claimed_at IS NOT NULL
              AND claimed_at >= NOW() - INTERVAL '1 hour'
            ORDER BY claimed_at ASC
        """)
    ).fetchall()

    # Recently processed (last 24h)
    processed_recent = db.execute(
        text("""
            SELECT id, company_id, branch_id, item_id, reason, processed_at
            FROM snapshot_refresh_queue
            WHERE processed_at >= NOW() - INTERVAL '24 hours'
            ORDER BY processed_at DESC
            LIMIT 20
        """)
    ).fetchall()

    print("=== Snapshot refresh queue status ===\n")
    print(f"Pending jobs:    {len(pending)}")
    print(f"In progress:     {len(in_progress)}")
    print(f"Processed (24h): {len(processed_recent)}")

    if pending:
        print("\n--- Pending jobs ---")
        for row in pending:
            qid, cid, bid, iid, reason, created = row[0], row[1], row[2], row[3], row[4], row[5]
            scope = "branch-wide" if iid is None else f"single item {iid}"
            reason_str = f" ({reason})" if reason else ""
            print(f"  {str(qid)[:8]}... {scope}  created {created}{reason_str}")
            if iid is None:
                # Estimate items for this branch
                count_row = db.execute(
                    text("""
                        SELECT COUNT(*) FROM items
                        WHERE company_id = :cid AND is_active = true
                    """),
                    {"cid": str(cid)},
                ).scalar()
                print(f"    -> ~{count_row} items will be refreshed for this branch")

    if in_progress:
        print("\n--- In progress (claimed, not yet completed) ---")
        for row in in_progress:
            qid, cid, bid, iid, reason, claimed = row[0], row[1], row[2], row[3], row[4], row[5]
            scope = "branch-wide" if iid is None else f"item {iid}"
            print(f"  {str(qid)[:8]}... {scope}  claimed at {claimed}")

    if processed_recent:
        print("\n--- Recently completed (last 24h, sample) ---")
        for row in processed_recent[:5]:
            qid, cid, bid, iid, reason, done = row[0], row[1], row[2], row[3], row[4], row[5]
            scope = "branch-wide" if iid is None else f"item {iid}"
            print(f"  {str(qid)[:8]}... {scope}  processed at {done}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run snapshot refresh with progress, or analyze queue status.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--status", action="store_true", help="Show queue status only (no refresh)")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--batch-size", type=int, default=50, help="Max queue jobs per batch (default 50)")
    parser.add_argument("--chunk-size", type=int, default=None, metavar="N", help="Items per commit for branch-wide jobs (default 200). Use 500-2000 for night runs to reduce commit overhead.")
    parser.add_argument("--quiet", action="store_true", help="Suppress SQL logging (WARNING only). Use for night batch to speed up.")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between runs when not --once")
    args = parser.parse_args()

    if args.quiet:
        _enable_quiet_mode()

    try:
        from app.database import SessionLocal
        from app.services.snapshot_refresh_service import SnapshotRefreshService
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. Example: cd pharmasight/backend && set PYTHONPATH=. && python -m scripts.run_snapshot_refresh_with_progress --status")
        sys.exit(1)

    db = SessionLocal()
    try:
        if args.status:
            run_status(db)
            return
        n = SnapshotRefreshService.process_queue_batch(
            db,
            batch_size=args.batch_size,
            progress_callback=_progress_callback,
            branch_wide_chunk_size=args.chunk_size,
        )
        db.commit()
        if n:
            logger.info("Processed %s snapshot refresh job(s)", n)
        else:
            logger.info("No pending jobs in queue")
    except Exception as e:
        logger.exception("Error: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

    if not args.once:
        while True:
            time.sleep(args.interval)
            db = SessionLocal()
            try:
                n = SnapshotRefreshService.process_queue_batch(
                    db,
                    batch_size=args.batch_size,
                    progress_callback=_progress_callback,
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


if __name__ == "__main__":
    main()
