#!/usr/bin/env python3
"""
Bulk snapshot refresh: one direct SQL statement per branch (~10k items in seconds).

Use when you need to refresh 6 branches × 10k items in under 2 hours. This runs
a single set-based SQL per (company_id, branch_id) instead of 10k Python round-trips.

Run from pharmasight/backend with PYTHONPATH=. so that 'app' resolves.

Usage:
  # Process all pending branch-wide jobs in the queue (one SQL per branch)
  python -m scripts.run_bulk_snapshot_refresh

  # Process one branch only (pass company_id and branch_id)
  python -m scripts.run_bulk_snapshot_refresh --company-id <uuid> --branch-id <uuid>

  # Dry run: show which jobs would be processed
  python -m scripts.run_bulk_snapshot_refresh --dry-run

  # After stopping the slow per-item worker: pick up its claimed job immediately
  python -m scripts.run_bulk_snapshot_refresh --include-claimed

  # If the DB has a short statement_timeout (e.g. 2 min), allow longer for the bulk query
  python -m scripts.run_bulk_snapshot_refresh --statement-timeout 30min
  python -m scripts.run_bulk_snapshot_refresh --statement-timeout 0   # no limit
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from uuid import UUID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk refresh item_branch_snapshot via direct SQL (one query per branch).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--company-id", type=str, default=None, help="Run for this company only")
    parser.add_argument("--branch-id", type=str, default=None, help="Run for this branch only (requires --company-id)")
    parser.add_argument("--dry-run", action="store_true", help="Only list pending jobs, do not run")
    parser.add_argument(
        "--include-claimed",
        action="store_true",
        help="Also process jobs claimed by another worker (e.g. after stopping the slow per-item refresh)",
    )
    parser.add_argument(
        "--statement-timeout",
        type=str,
        default="30min",
        help="PostgreSQL statement_timeout for the bulk query (e.g. 30min, 1h, 0 for no limit). Default 30min.",
    )
    args = parser.parse_args()

    try:
        from sqlalchemy import text
        from app.database import SessionLocal
    except ImportError as e:
        logger.error("Import failed. Run from backend with PYTHONPATH=. %s", e)
        sys.exit(1)

    sql_path = Path(__file__).resolve().parent / "bulk_refresh_branch_snapshot.sql"
    if not sql_path.exists():
        logger.error("SQL file not found: %s", sql_path)
        sys.exit(1)
    bulk_sql = sql_path.read_text(encoding="utf-8")

    db = SessionLocal()
    try:
        if args.company_id and args.branch_id:
            company_id = UUID(args.company_id)
            branch_id = UUID(args.branch_id)
            jobs = [(None, company_id, branch_id)]
        elif args.company_id or args.branch_id:
            logger.error("Provide both --company-id and --branch-id for single-branch run")
            sys.exit(1)
        else:
            claimed_filter = "" if args.include_claimed else "AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '1 hour')"
            rows = db.execute(
                text(f"""
                    SELECT id, company_id, branch_id
                    FROM snapshot_refresh_queue
                    WHERE processed_at IS NULL
                      AND item_id IS NULL
                      {claimed_filter}
                    ORDER BY created_at ASC
                """)
            ).fetchall()
            jobs = [(r[0], r[1], r[2]) for r in rows]

        if not jobs:
            logger.info("No pending branch-wide snapshot jobs in queue")
            return

        if args.dry_run:
            for qid, cid, bid in jobs:
                logger.info("Would process: company_id=%s branch_id=%s queue_id=%s", cid, bid, qid)
            return

        for qid, company_id, branch_id in jobs:
            cid_str = str(company_id)
            bid_str = str(branch_id)
            logger.info("Bulk refreshing snapshot for company=%s branch=%s ...", cid_str[:8], bid_str[:8])
            try:
                if qid is not None:
                    db.execute(
                        text("UPDATE snapshot_refresh_queue SET claimed_at = NOW() WHERE id = :id"),
                        {"id": str(qid)},
                    )
                    db.commit()
                # Raise statement_timeout so the bulk INSERT is not canceled (default DB is often 2 min)
                db.execute(text("SET statement_timeout = :t"), {"t": args.statement_timeout})
                db.commit()
                logger.info(
                    "Executing bulk SQL for branch %s (statement_timeout=%s)...",
                    bid_str[:8],
                    args.statement_timeout,
                )
                t0 = time.perf_counter()
                db.execute(text(bulk_sql), {"company_id": cid_str, "branch_id": bid_str})
                db.commit()
                elapsed = time.perf_counter() - t0
                if qid is not None:
                    db.execute(
                        text("UPDATE snapshot_refresh_queue SET processed_at = NOW() WHERE id = :id"),
                        {"id": str(qid)},
                    )
                    db.commit()
                logger.info("Bulk refresh done for branch %s in %.1f s", bid_str[:8], elapsed)
            except Exception as e:
                logger.exception("Bulk refresh failed for branch %s: %s", bid_str[:8], e)
                db.rollback()
                if qid is not None:
                    try:
                        db.execute(
                            text("UPDATE snapshot_refresh_queue SET claimed_at = NULL WHERE id = :id"),
                            {"id": str(qid)},
                        )
                        db.commit()
                    except Exception:
                        db.rollback()
                raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
