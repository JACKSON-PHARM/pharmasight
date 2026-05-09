"""Lightweight DB polling worker for KRA outbox events."""
from __future__ import annotations

import logging
import threading

from app.config import settings
from app.database import SessionLocal
from app.models.company import Branch, BranchEtimsCredentials
from app.models.kra_event_outbox import KraEventOutbox
from app.models.sale import SalesInvoice
from app.services.etims.etims_invoice_submitter import EtimsSubmissionSkipped, submit_sales_invoice
from app.services.etims.item_sync_service import sync_item_to_kra
from app.services.etims.kra_outbox_service import KraOutboxService
from app.services.etims.kra_readiness_resolver import BranchKraReadinessResolver

logger = logging.getLogger(__name__)

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _process_sale_completed_event(db, row) -> None:
    branch = db.query(Branch).filter(Branch.id == row.branch_id).first()
    if not branch:
        KraOutboxService.mark_retry(db, row, error="branch_not_found")
        return
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch.id).first()
    readiness = BranchKraReadinessResolver.resolve(db, branch=branch, creds=creds)
    if not bool(readiness.get("can_process")):
        blockers = ",".join(readiness.get("blockers") or []) or "readiness_blocked"
        KraOutboxService.mark_retry(db, row, error=f"readiness:{readiness.get('readiness_state')}:{blockers}")
        return

    invoice = db.query(SalesInvoice).filter(SalesInvoice.id == row.aggregate_id).first()
    if not invoice:
        KraOutboxService.mark_retry(db, row, error="invoice_not_found")
        return
    if (invoice.submission_status or "").strip() == "submitted":
        KraOutboxService.mark_processed(db, row)
        return
    if (invoice.submission_status or "").strip() == "failed":
        invoice.submission_status = "pending"
        invoice.kra_last_error = None
        db.flush()

    if settings.KRA_OUTBOX_SHADOW_MODE:
        KraOutboxService.mark_processed(db, row)
        return

    try:
        res = submit_sales_invoice(db, invoice.id)
        if bool(res.get("ok")):
            KraOutboxService.mark_processed(db, row)
        else:
            KraOutboxService.mark_retry(db, row, error=(res.get("error") or "submit_failed"))
    except EtimsSubmissionSkipped as e:
        db.refresh(invoice)
        if (invoice.submission_status or "").strip() == "submitted":
            KraOutboxService.mark_processed(db, row)
        else:
            KraOutboxService.mark_retry(db, row, error=f"skipped:{str(e)}")
    except Exception as e:
        KraOutboxService.mark_retry(db, row, error=f"unexpected:{e}")


def _process_item_updated_event(db, row) -> None:
    branch = db.query(Branch).filter(Branch.id == row.branch_id).first()
    if not branch:
        KraOutboxService.mark_retry(db, row, error="branch_not_found")
        return
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch.id).first()
    readiness = BranchKraReadinessResolver.resolve(db, branch=branch, creds=creds)
    if not bool(readiness.get("activation_allowed")):
        blockers = ",".join(readiness.get("blockers") or []) or "readiness_blocked"
        KraOutboxService.mark_retry(db, row, error=f"item_sync_blocked:{readiness.get('readiness_state')}:{blockers}")
        return
    if settings.KRA_OUTBOX_SHADOW_MODE:
        KraOutboxService.mark_processed(db, row)
        return
    res = sync_item_to_kra(
        db,
        item_id=row.aggregate_id,
        company_id=row.company_id,
        branch_id=row.branch_id,
    )
    if bool(res.get("ok")):
        KraOutboxService.mark_processed(db, row)
    else:
        KraOutboxService.mark_retry(db, row, error=(res.get("error") or "item_sync_failed"))


def process_outbox_once() -> int:
    processed = 0
    with SessionLocal() as db:
        worker_id = f"pid-{threading.get_native_id()}"
        rows = KraOutboxService.claim_events(
            db,
            worker_id=worker_id,
            limit=max(int(settings.KRA_OUTBOX_BATCH_SIZE or 10), 1),
            lease_seconds=max(int(settings.KRA_OUTBOX_LEASE_SECONDS or 60), 10),
        )
        if not rows:
            db.commit()
            return 0
        db.commit()

    for row in rows:
        with SessionLocal() as db:
            live = db.query(KraEventOutbox).filter(KraEventOutbox.id == row.id).first()
            if not live:
                continue
            try:
                if live.event_type == "sale.completed":
                    _process_sale_completed_event(db, live)
                elif live.event_type == "item.updated":
                    _process_item_updated_event(db, live)
                else:
                    KraOutboxService.mark_retry(db, live, error=f"unsupported_event_type:{live.event_type}")
                db.commit()
                processed += 1
            except Exception:
                db.rollback()
                logger.exception("KRA outbox processing failed for event_id=%s", str(live.id))
    return processed


def _worker_loop() -> None:
    logger.info("KRA outbox worker started")
    poll = max(int(settings.KRA_OUTBOX_POLL_SECONDS or 5), 1)
    while not _stop_event.is_set():
        try:
            process_outbox_once()
        except Exception:
            logger.exception("KRA outbox loop error")
        _stop_event.wait(poll)
    logger.info("KRA outbox worker stopped")


def start_kra_outbox_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="kra-outbox-worker", daemon=True)
    _worker_thread.start()


def stop_kra_outbox_worker() -> None:
    _stop_event.set()
