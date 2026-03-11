"""
Centralized snapshot recalculation service.

- Single-item changes (GRN one item, promotion edit, floor price, manual override):
  → Recalculate snapshot synchronously in the same transaction.

- Bulk-impact changes (company margin update, VAT change, category-level promotion):
  → Insert into deduplicated snapshot_refresh_queue; process in background in batches.

Call schedule_snapshot_refresh() from write paths; the service detects scope and
either runs sync refresh or enqueues.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.pos_snapshot_service import refresh_pos_snapshot_for_item

logger = logging.getLogger(__name__)


class SnapshotRefreshService:
    """
    Centralized entry point for POS snapshot refresh.
    Detects single-item vs multi-item scope and either refreshes synchronously
    or enqueues for background processing.
    """

    @staticmethod
    def refresh_item_sync(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: UUID,
    ) -> None:
        """
        Recalculate item_branch_snapshot for one (item_id, branch_id) in the current transaction.
        Must run in the same transaction as ledger/balance writes so search and stock stay in sync.
        Last purchase price is read from the inventory ledger (single source of truth).
        On failure logs and re-raises so the transaction rolls back (no partial commit).
        """
        try:
            refresh_pos_snapshot_for_item(db, company_id, branch_id, item_id)
        except Exception as e:
            logger.error(
                "item_branch_snapshot sync refresh failed item=%s branch=%s: %s (transaction will roll back)",
                item_id, branch_id, e,
            )
            raise

    @staticmethod
    def enqueue_branch_refresh(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        reason: Optional[str] = None,
    ) -> None:
        """
        Enqueue a full-branch refresh (item_id = NULL). Deduplicated.
        Use for: company margin update, VAT change, category-level promotion.
        reason: optional debug label (e.g. "company_margin_change", "vat_change").
        """
        try:
            db.execute(
                text("""
                    INSERT INTO snapshot_refresh_queue (company_id, branch_id, item_id, created_at, reason)
                    SELECT :company_id, :branch_id, NULL, NOW(), :reason
                    WHERE NOT EXISTS (
                        SELECT 1 FROM snapshot_refresh_queue q
                        WHERE q.company_id = :company_id AND q.branch_id = :branch_id
                          AND q.item_id IS NULL AND q.processed_at IS NULL
                    )
                """),
                {
                    "company_id": str(company_id),
                    "branch_id": str(branch_id),
                    "reason": reason,
                },
            )
        except Exception as e:
            logger.warning("Enqueue branch refresh failed company=%s branch=%s: %s", company_id, branch_id, e)

    @staticmethod
    def enqueue_item_refreshes(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_ids: List[UUID],
    ) -> None:
        """
        Enqueue snapshot refresh for specific items in a branch. Deduplicated per (company_id, branch_id, item_id).
        Use for: multi-item promotion, bulk price update.
        """
        if not item_ids:
            return
        try:
            for item_id in item_ids:
                db.execute(
                    text("""
                        INSERT INTO snapshot_refresh_queue (company_id, branch_id, item_id, created_at)
                        SELECT :company_id, :branch_id, :item_id::uuid, NOW()
                        WHERE NOT EXISTS (
                            SELECT 1 FROM snapshot_refresh_queue q
                            WHERE q.company_id = :company_id AND q.branch_id = :branch_id
                              AND q.item_id = :item_id::uuid AND q.processed_at IS NULL
                        )
                    """),
                    {"company_id": str(company_id), "branch_id": str(branch_id), "item_id": str(item_id)},
                )
        except Exception as e:
            logger.warning("Enqueue item refreshes failed: %s", e)

    @staticmethod
    def schedule_snapshot_refresh(
        db: Session,
        company_id: UUID,
        branch_id: UUID,
        item_id: Optional[UUID] = None,
        item_ids: Optional[List[UUID]] = None,
    ) -> None:
        """
        Single entry point: detect scope and either refresh synchronously or enqueue.

        - item_id set, item_ids None → single-item: sync refresh in current transaction.
        - item_ids set, len 1 → single-item: sync refresh.
        - item_ids set, len > 1 → multi-item: enqueue each (deduplicated).
        - item_id None, item_ids None → whole branch: enqueue one branch-wide job.
        - item_ids set, len 0 → no-op.
        """
        if item_id is not None and (item_ids is None or len(item_ids or []) == 0):
            SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, item_id)
            return
        if item_ids is not None:
            if len(item_ids) == 0:
                return
            if len(item_ids) == 1:
                SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, item_ids[0])
                return
            SnapshotRefreshService.enqueue_item_refreshes(db, company_id, branch_id, item_ids)
            return
        # item_id None, item_ids None → bulk branch
        SnapshotRefreshService.enqueue_branch_refresh(db, company_id, branch_id)

    @staticmethod
    def schedule_snapshot_refresh_for_item_all_branches(
        db: Session,
        company_id: UUID,
        item_id: UUID,
    ) -> None:
        """
        Refresh one item in every branch of the company (e.g. item edit).
        Done synchronously per branch to keep consistency in same transaction.
        """
        from app.models import Branch
        branches = db.query(Branch.id).filter(
            Branch.company_id == company_id,
            Branch.is_active == True,
        ).all()
        for (branch_id,) in branches:
            SnapshotRefreshService.refresh_item_sync(db, company_id, branch_id, item_id)

    # Chunk size for branch-wide jobs: refresh this many items per transaction, then commit.
    # Prevents long locks, large memory, and slow commits when a branch has thousands of items.
    BRANCH_WIDE_CHUNK_SIZE = 200

    @staticmethod
    def process_queue_batch(
        db: Session,
        batch_size: int = 50,
        progress_callback: Optional[Callable[..., None]] = None,
        branch_wide_chunk_size: Optional[int] = None,
    ) -> int:
        """
        Process up to batch_size pending jobs from snapshot_refresh_queue.
        - Item jobs: refresh that (item_id, branch_id) in one transaction, mark processed.
        - Branch-wide jobs (item_id IS NULL): claim row, then process items in chunks of
          branch_wide_chunk_size (default BRANCH_WIDE_CHUNK_SIZE); commit after each chunk.
          Use a larger chunk size (e.g. 1000) for night batch runs to reduce commit overhead.

        progress_callback: optional callable(event: str, **kwargs). Events:
          - "job_start": job_type="branch_wide"|"single_item", company_id, branch_id, item_id (or None)
          - "branch_total": total_items=N (branch-wide only, before chunks)
          - "chunk_done": offset, refreshed, total_items, percent (branch-wide only)
          - "job_done": job_type, success=True
        """
        from app.models import Item
        chunk_size = branch_wide_chunk_size if branch_wide_chunk_size is not None else SnapshotRefreshService.BRANCH_WIDE_CHUNK_SIZE
        chunk_size = max(1, chunk_size)
        # Include rows claimed >1h ago (stuck worker)
        rows = db.execute(
            text("""
                SELECT id, company_id, branch_id, item_id
                FROM snapshot_refresh_queue
                WHERE processed_at IS NULL
                  AND (claimed_at IS NULL OR claimed_at < NOW() - INTERVAL '1 hour')
                ORDER BY created_at ASC
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
            """),
            {"batch_size": batch_size},
        ).fetchall()
        if not rows:
            return 0
        processed = 0
        for row in rows:
            qid, company_id, branch_id, item_id = row[0], UUID(str(row[1])), UUID(str(row[2])), row[3]
            try:
                if item_id is None:
                    if progress_callback:
                        progress_callback("job_start", job_type="branch_wide", company_id=company_id, branch_id=branch_id, item_id=None)
                    # Branch-wide: claim so we can commit in chunks without another worker taking the row
                    db.execute(
                        text("UPDATE snapshot_refresh_queue SET claimed_at = NOW() WHERE id = :id"),
                        {"id": str(qid)},
                    )
                    db.commit()
                    # Get total count for progress
                    total_result = db.execute(
                        text("""
                            SELECT COUNT(*) FROM items
                            WHERE company_id = :company_id AND is_active = true
                        """),
                        {"company_id": str(company_id)},
                    ).scalar()
                    total_items = total_result or 0
                    if progress_callback:
                        progress_callback("branch_total", total_items=total_items)
                    # Process items in chunks; commit after each chunk
                    offset = 0
                    while True:
                        chunk = db.execute(
                            text("""
                                SELECT id FROM items
                                WHERE company_id = :company_id AND is_active = true
                                ORDER BY id
                                LIMIT :limit OFFSET :offset
                            """),
                            {
                                "company_id": str(company_id),
                                "limit": chunk_size,
                                "offset": offset,
                            },
                        ).fetchall()
                        if not chunk:
                            break
                        for (iid,) in chunk:
                            try:
                                refresh_pos_snapshot_for_item(db, company_id, branch_id, iid)
                            except Exception as e:
                                logger.warning(
                                    "Queue branch refresh failed item=%s branch=%s: %s",
                                    iid, branch_id, e,
                                )
                        db.commit()
                        refreshed_so_far = offset + len(chunk)
                        if progress_callback and total_items > 0:
                            pct = min(100, round(100.0 * refreshed_so_far / total_items, 1))
                            progress_callback("chunk_done", offset=offset, refreshed=len(chunk), total_items=total_items, refreshed_so_far=refreshed_so_far, percent=pct)
                        offset += chunk_size
                        if len(chunk) < chunk_size:
                            break
                    db.execute(
                        text("UPDATE snapshot_refresh_queue SET processed_at = NOW() WHERE id = :id"),
                        {"id": str(qid)},
                    )
                    db.commit()
                    if progress_callback:
                        progress_callback("job_done", job_type="branch_wide", success=True)
                else:
                    if progress_callback:
                        progress_callback("job_start", job_type="single_item", company_id=company_id, branch_id=branch_id, item_id=item_id)
                    refresh_pos_snapshot_for_item(db, company_id, branch_id, UUID(str(item_id)))
                    db.execute(
                        text("UPDATE snapshot_refresh_queue SET processed_at = NOW() WHERE id = :id"),
                        {"id": str(qid)},
                    )
                    db.commit()
                    if progress_callback:
                        progress_callback("job_done", job_type="single_item", success=True)
                processed += 1
            except Exception as e:
                logger.warning("Queue job %s failed: %s", qid, e)
                db.rollback()
                if progress_callback:
                    progress_callback("job_done", job_type="branch_wide" if item_id is None else "single_item", success=False, error=str(e))
        return processed
