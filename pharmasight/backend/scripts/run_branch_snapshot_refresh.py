"""
Run a full branch snapshot refresh so item_branch_snapshot is rebuilt for all items.
This applies the latest pricing logic, including Excel default costs as fallbacks.

Usage (from backend directory):
  python scripts/run_branch_snapshot_refresh.py
"""
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from uuid import UUID

from app.database import SessionLocal
from app.services.snapshot_refresh_service import SnapshotRefreshService

# Default: your current company/branch
COMPANY_ID = "9c71915e-3e59-45d5-9719-56d2322ff673"
BRANCH_ID = "bec5d46a-7f21-45ef-945c-8c68171aa386"


def main() -> None:
    company_id = UUID(COMPANY_ID)
    branch_id = UUID(BRANCH_ID)
    db = SessionLocal()
    try:
        # Enqueue a branch-wide refresh job
        print(f"Enqueuing branch-wide snapshot refresh for company={company_id} branch={branch_id}...")
        SnapshotRefreshService.enqueue_branch_refresh(db, company_id, branch_id)
        db.commit()

        # Process queue until no more jobs
        total_processed = 0
        while True:
            processed = SnapshotRefreshService.process_queue_batch(db, batch_size=50)
            if processed <= 0:
                break
            total_processed += processed
            print(f"Processed {processed} snapshot_refresh_queue jobs (running total={total_processed})")

        print(f"Done. Total jobs processed: {total_processed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
    sys.exit(0)

