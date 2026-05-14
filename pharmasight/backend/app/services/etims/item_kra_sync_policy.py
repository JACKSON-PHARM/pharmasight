"""KRA item sync enqueue policy for stock-affecting workflows."""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Branch, BranchEtimsCredentials
from app.models.item import Item
from app.services.etims.kra_company_activation import company_kra_execution_enabled
from app.services.etims.kra_outbox_service import KraOutboxService

logger = logging.getLogger(__name__)


def branch_kra_submission_ready(db: Session, *, company_id: UUID, branch_id: UUID) -> bool:
    branch = (
        db.query(Branch)
        .filter(Branch.id == branch_id, Branch.company_id == company_id, Branch.is_active.is_(True))
        .first()
    )
    if not branch:
        return False
    creds = (
        db.query(BranchEtimsCredentials)
        .filter(
            BranchEtimsCredentials.company_id == company_id,
            BranchEtimsCredentials.branch_id == branch_id,
            BranchEtimsCredentials.enabled.is_(True),
        )
        .first()
    )
    if not creds:
        return False
    return (getattr(creds, "connection_status", "") or "").strip().lower() == "verified"


def auto_heal_branch_etims_connection_verified(db: Session, *, company_id: UUID, branch_id: UUID) -> None:
    """
    Match ``kra_outbox_worker`` sale path: when validation passed but connection flag lags,
    promote ``connection_status`` to ``verified`` so outbox enqueue gates succeed.
    """
    creds = (
        db.query(BranchEtimsCredentials)
        .filter(
            BranchEtimsCredentials.company_id == company_id,
            BranchEtimsCredentials.branch_id == branch_id,
        )
        .first()
    )
    if not creds or not bool(getattr(creds, "enabled", False)):
        return
    val = str(getattr(creds, "validation_status", "") or "").strip().lower()
    conn = str(getattr(creds, "connection_status", "") or "").strip().lower()
    if val == "passed" and conn != "verified":
        creds.connection_status = "verified"
        db.flush()


def enqueue_item_sync_for_stock_event(
    db: Session,
    *,
    item: Item,
    branch_id: UUID,
    source: str,
    max_attempts: int,
) -> bool:
    # Stock-affecting operations must not mutate itemCd indirectly via background saveItem sync.
    # Keep this policy as a no-op: only explicit "Sync to KRA now" should enqueue item.updated.
    _ = (db, branch_id, max_attempts)  # keep signature stable
    if company_kra_execution_enabled(db, item.company_id):
        logger.info(
            "item_sync_enqueue_skipped op=stock_event item_id=%s branch_id=%s source=%s reason=manual_sync_required",
            item.id,
            branch_id,
            source,
        )
    return False
