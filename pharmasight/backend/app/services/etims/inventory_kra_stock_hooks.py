"""Enqueue KRA OSCU stock updates when inventory changes locally.

- **Stock-in** (``insertStockIO`` + ``saveStockMaster``): positive movements on transaction types
  covered by ``should_enqueue_kra_stock_in``. Root ``sarTyCd`` and line ``ioTyCd`` are derived from the
  ledger (``kra_stock_push_service``) — e.g. purchase ``02``/``1``, adjustment ``06``/``3``, transfer ``04``/``1``.
- **Ledger align** (``saveStockMaster`` from current PharmaSight ledger only): all other non-zero
  ledger rows (sales, transfer out, purchase return, reduce adjust) so OSCU ``rsdQty`` tracks local stock.
"""
from __future__ import annotations

import logging
from typing import Any

from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession

from app.config import settings
from app.models.inventory import InventoryLedger
from app.models.item import Item
from app.models.kra_event_outbox import KraEventOutbox
from app.services.etims.item_kra_sync_policy import (
    auto_heal_branch_etims_connection_verified,
    branch_kra_submission_ready,
)
from app.services.etims.kra_company_activation import company_kra_execution_enabled
from app.services.etims.kra_outbox_service import KraOutboxService
from app.services.etims.kra_stock_push_service import should_enqueue_kra_stock_in

logger = logging.getLogger(__name__)

_ledger_listener_registered = False


def enqueue_kra_stock_in_for_ledger(
    db: Any, ledger: InventoryLedger | None, *, source: str
) -> tuple[bool, str | None, KraEventOutbox | None]:
    """
    Transactional outbox event ``inventory.stock_in`` keyed by ``inventory_ledger.id``.

    Returns ``(enqueued, note, outbox_row)`` where ``outbox_row`` is the durable job row when
    enqueued (callers may run ``process_inventory_stock_in_outbox_row`` in the same request).
    ``note`` explains skip reasons or that KRA runs server-side (not in browser DevTools).
    """
    if ledger is None or not should_enqueue_kra_stock_in(ledger):
        return False, None, None
    if not company_kra_execution_enabled(db, ledger.company_id):
        return False, "KRA is off for this company (no sync queued).", None
    auto_heal_branch_etims_connection_verified(db, company_id=ledger.company_id, branch_id=ledger.branch_id)
    if not branch_kra_submission_ready(db, company_id=ledger.company_id, branch_id=ledger.branch_id):
        return (
            False,
            "KRA stock sync not queued: enable branch eTIMS and verify connection in Settings.",
            None,
        )
    row = KraOutboxService.enqueue_inventory_stock_in(
        db,
        ledger=ledger,
        source=source,
        max_attempts=max(int(settings.KRA_OUTBOX_MAX_ATTEMPTS or 12), 1),
    )
    return (
        True,
        "KRA stock update queued (runs on server—open DevTools will not show KRA calls). Retry invoice after worker processes.",
        row,
    )


def maybe_enqueue_kra_stock_ledger_align_for_ledger(db: Any, ledger: InventoryLedger | None, *, source: str) -> None:
    """
    Queue ``inventory.stock_ledger_align`` (``saveStockMaster`` from PharmaSight ledger, no IO).

    Skips when ``should_enqueue_kra_stock_in`` applies (those rows use ``insertStockIO`` path).
    """
    if ledger is None:
        return
    if not getattr(settings, "KRA_STOCK_LEDGER_SYNC_ENABLED", True):
        return
    if should_enqueue_kra_stock_in(ledger):
        return
    if not company_kra_execution_enabled(db, ledger.company_id):
        return
    auto_heal_branch_etims_connection_verified(db, company_id=ledger.company_id, branch_id=ledger.branch_id)
    if not branch_kra_submission_ready(db, company_id=ledger.company_id, branch_id=ledger.branch_id):
        return
    item = db.query(Item).filter(Item.id == ledger.item_id, Item.company_id == ledger.company_id).first()
    if not item or not str(getattr(item, "kra_item_code", None) or "").strip():
        return
    KraOutboxService.enqueue_inventory_stock_ledger_align(
        db,
        company_id=ledger.company_id,
        branch_id=ledger.branch_id,
        item_id=ledger.item_id,
        source=source,
        max_attempts=max(int(settings.KRA_OUTBOX_MAX_ATTEMPTS or 12), 1),
    )


def register_inventory_kra_ledger_sync_listener() -> None:
    """Register SQLAlchemy listeners (idempotent). Call from FastAPI startup."""
    global _ledger_listener_registered
    if _ledger_listener_registered:
        return
    _ledger_listener_registered = True

    @event.listens_for(OrmSession, "after_flush", propagate=True)
    def _kra_collect_ledgers_for_align(session: OrmSession, flush_context: Any) -> None:
        if not getattr(settings, "KRA_STOCK_LEDGER_SYNC_ENABLED", True):
            return
        if session.info.get("skip_kra_stock_ledger_sync"):
            return
        buf: list[InventoryLedger] = session.info.setdefault("_kra_stock_ledger_align_buffer", [])
        for obj in session.new:
            if isinstance(obj, InventoryLedger):
                buf.append(obj)

    @event.listens_for(OrmSession, "after_flush_postexec", propagate=True)
    def _kra_enqueue_ledgers_after_flush(session: OrmSession, flush_context: Any) -> None:
        if not getattr(settings, "KRA_STOCK_LEDGER_SYNC_ENABLED", True):
            return
        if session.info.get("skip_kra_stock_ledger_sync"):
            return
        buf = session.info.pop("_kra_stock_ledger_align_buffer", None)
        if not buf:
            return
        by_id: dict[UUID, InventoryLedger] = {}
        for led in buf:
            if getattr(led, "id", None):
                by_id[led.id] = led
        for led in by_id.values():
            tt = (led.transaction_type or "unknown").strip()
            try:
                maybe_enqueue_kra_stock_ledger_align_for_ledger(session, led, source=f"ledger.{tt}")
            except Exception:
                logger.exception(
                    "KRA stock ledger align enqueue failed ledger_id=%s item_id=%s branch_id=%s",
                    led.id,
                    led.item_id,
                    led.branch_id,
                )
