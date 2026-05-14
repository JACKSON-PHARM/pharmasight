"""Lightweight DB polling worker for KRA outbox events."""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.company import Branch, BranchEtimsCredentials, Company
from app.models.kra_event_outbox import KraEventOutbox
from app.models.sale import SalesInvoice
from app.services.etims.etims_invoice_submitter import EtimsSubmissionSkipped, submit_sales_invoice
from app.services.etims.item_sync_service import sync_item_to_kra
from datetime import datetime, timezone
from uuid import UUID

from app.services.etims.kra_stock_push_service import (
    process_inventory_stock_in_event,
    reconcile_kra_stock_master_read_through,
)
from app.services.etims.kra_outbox_service import KraOutboxService
from app.services.etims.kra_readiness_resolver import BranchKraReadinessResolver

logger = logging.getLogger(__name__)

_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()
_ITEM_UPDATED_ALLOWED_SOURCES = frozenset({"items.sync_now", "items.create"})


def _process_sale_completed_event(db, row) -> None:
    branch = db.query(Branch).filter(Branch.id == row.branch_id).first()
    if not branch:
        KraOutboxService.mark_retry(db, row, error="branch_not_found")
        return
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    if not company or not bool(getattr(company, "kra_enabled", False)):
        KraOutboxService.mark_processed(db, row, skip_reason="company_kra_disabled")
        return
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch.id).first()
    # Auto-heal stale connection flags: older failures marked connection_status failed even when
    # credentials are valid and validation has passed.
    if creds and bool(getattr(creds, "enabled", False)):
        if (
            (str(getattr(creds, "validation_status", "") or "").strip().lower() == "passed")
            and (str(getattr(creds, "connection_status", "") or "").strip().lower() != "verified")
        ):
            creds.connection_status = "verified"
            db.flush()
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


def process_inventory_stock_in_outbox_row(db: Session, row: KraEventOutbox) -> Dict[str, Any]:
    """
    Run insertStockIO + saveStockMaster for one ``inventory.stock_in`` outbox row and
    transition outbox status (same logic as the background worker). Safe to call from
    HTTP after enqueue; uses ``SELECT … FOR UPDATE`` so it coordinates with the worker.
    """
    locked = db.query(KraEventOutbox).filter(KraEventOutbox.id == row.id).with_for_update().first()
    if not locked:
        return {
            "ok": False,
            "skipped": None,
            "error": "outbox_row_missing",
            "outbox_status": None,
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }
    st = (locked.processing_status or "").strip()
    if st == "processed":
        return {
            "ok": True,
            "skipped": "already_processed",
            "error": None,
            "outbox_status": "processed",
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }

    branch = db.query(Branch).filter(Branch.id == locked.branch_id).first()
    if not branch:
        KraOutboxService.mark_retry(db, locked, error="branch_not_found")
        return {
            "ok": False,
            "skipped": None,
            "error": "branch_not_found",
            "outbox_status": locked.processing_status,
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    if not company or not bool(getattr(company, "kra_enabled", False)):
        KraOutboxService.mark_processed(db, locked, skip_reason="company_kra_disabled")
        return {
            "ok": True,
            "skipped": "company_kra_disabled",
            "error": None,
            "outbox_status": "processed",
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch.id).first()
    if creds and bool(getattr(creds, "enabled", False)):
        if (
            (str(getattr(creds, "validation_status", "") or "").strip().lower() == "passed")
            and (str(getattr(creds, "connection_status", "") or "").strip().lower() != "verified")
        ):
            creds.connection_status = "verified"
            db.flush()
    readiness = BranchKraReadinessResolver.resolve(db, branch=branch, creds=creds)
    if not bool(readiness.get("can_process")):
        blockers = ",".join(readiness.get("blockers") or []) or "readiness_blocked"
        KraOutboxService.mark_retry(
            db,
            locked,
            error=f"readiness:{readiness.get('readiness_state')}:{blockers}",
        )
        return {
            "ok": False,
            "skipped": None,
            "error": f"readiness:{readiness.get('readiness_state')}:{blockers}",
            "outbox_status": locked.processing_status,
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }
    if settings.KRA_OUTBOX_SHADOW_MODE:
        KraOutboxService.mark_processed(db, locked)
        return {
            "ok": True,
            "skipped": "shadow_mode",
            "error": None,
            "outbox_status": "processed",
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }
    try:
        res = process_inventory_stock_in_event(db, locked)
    except Exception as e:
        KraOutboxService.mark_retry(db, locked, error=f"unexpected:{e}")
        return {
            "ok": False,
            "skipped": None,
            "error": f"unexpected:{e}",
            "outbox_status": locked.processing_status,
            "kra_stock_rsd_qty": None,
            "item_cd": None,
            "user_delta": None,
            "previous_kra_qty": None,
            "target_local_qty": None,
            "reconciliation_delta": None,
            "reconciliation_delta_used": None,
            "resulting_kra_qty": None,
        }
    if bool(res.get("ok")):
        KraOutboxService.mark_processed(db, locked)
        return {
            "ok": True,
            "skipped": None,
            "error": None,
            "outbox_status": "processed",
            "kra_stock_rsd_qty": res.get("kra_stock_rsd_qty"),
            "item_cd": res.get("item_cd"),
            "kra_ledger_align_failed": res.get("kra_ledger_align_failed"),
            "user_delta": res.get("user_delta"),
            "previous_kra_qty": res.get("previous_kra_qty"),
            "target_local_qty": res.get("target_local_qty"),
            "reconciliation_delta": res.get("reconciliation_delta"),
            "reconciliation_delta_used": res.get("reconciliation_delta_used"),
            "resulting_kra_qty": res.get("resulting_kra_qty"),
            "insert_stock_sar_ty_cd": res.get("insert_stock_sar_ty_cd"),
            "insert_stock_io_ty_cd": res.get("insert_stock_io_ty_cd"),
            "insert_stock_tax_ty_cd": res.get("insert_stock_tax_ty_cd"),
        }
    KraOutboxService.mark_retry(db, locked, error=str(res.get("error") or "stock_in_failed"))
    return {
        "ok": False,
        "skipped": None,
        "error": str(res.get("error") or "stock_in_failed"),
        "outbox_status": locked.processing_status,
        "kra_stock_rsd_qty": None,
        "item_cd": res.get("item_cd"),
        "user_delta": None,
        "previous_kra_qty": None,
        "target_local_qty": None,
        "reconciliation_delta": None,
        "reconciliation_delta_used": None,
        "resulting_kra_qty": None,
    }


def _process_inventory_stock_ledger_align_event(db: Session, row: KraEventOutbox) -> None:
    locked = db.query(KraEventOutbox).filter(KraEventOutbox.id == row.id).with_for_update().first()
    if not locked:
        return
    if (locked.processing_status or "").strip() == "processed":
        return
    if settings.KRA_OUTBOX_SHADOW_MODE:
        KraOutboxService.mark_processed(db, locked, skip_reason="shadow_mode")
        return

    branch = db.query(Branch).filter(Branch.id == locked.branch_id).first()
    if not branch:
        KraOutboxService.mark_retry(db, locked, error="branch_not_found")
        return
    company = db.query(Company).filter(Company.id == branch.company_id).first()
    if not company or not bool(getattr(company, "kra_enabled", False)):
        KraOutboxService.mark_processed(db, locked, skip_reason="company_kra_disabled")
        return
    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch.id).first()
    if creds and bool(getattr(creds, "enabled", False)):
        if (
            (str(getattr(creds, "validation_status", "") or "").strip().lower() == "passed")
            and (str(getattr(creds, "connection_status", "") or "").strip().lower() != "verified")
        ):
            creds.connection_status = "verified"
            db.flush()
    readiness = BranchKraReadinessResolver.resolve(db, branch=branch, creds=creds)
    if not bool(readiness.get("can_process")):
        blockers = ",".join(readiness.get("blockers") or []) or "readiness_blocked"
        KraOutboxService.mark_retry(
            db,
            locked,
            error=f"readiness:{readiness.get('readiness_state')}:{blockers}",
        )
        return

    payload = locked.payload_json if isinstance(locked.payload_json, dict) else {}
    raw_id = payload.get("item_id")
    if not raw_id:
        KraOutboxService.mark_processed(db, locked, skip_reason="payload_missing_item_id")
        return
    try:
        item_id = UUID(str(raw_id))
    except Exception:
        KraOutboxService.mark_processed(db, locked, skip_reason="payload_invalid_item_id")
        return

    try:
        res = reconcile_kra_stock_master_read_through(
            db,
            company_id=locked.company_id,
            branch_id=locked.branch_id,
            item_id=item_id,
            timeout=120,
            align_with_ledger=True,
        )
    except Exception as e:
        KraOutboxService.mark_retry(db, locked, error=f"unexpected:{e}")
        return

    if bool(res.get("ok")):
        KraOutboxService.mark_processed(db, locked)
        return

    err = str(res.get("error") or "reconcile_failed")
    if "item_missing_kra_item_code" in err or "item_not_found" in err:
        KraOutboxService.mark_processed(db, locked, skip_reason=err[:4000])
        return
    if "KRA_OUTBOX_SHADOW_MODE" in err:
        KraOutboxService.mark_processed(db, locked, skip_reason=err[:4000])
        return
    KraOutboxService.mark_retry(db, locked, error=err[:4000])


def _process_inventory_stock_in_event(db, row) -> None:
    process_inventory_stock_in_outbox_row(db, row)


def process_item_updated_outbox_row(db: Session, row: KraEventOutbox) -> Dict[str, Any]:
    """
    Run ``sync_item_to_kra`` for one ``item.updated`` outbox row (same logic as the background worker).
    Safe to call from HTTP after enqueue; uses ``SELECT … FOR UPDATE`` so it coordinates with the worker.
    """
    _empty = {
        "ok": False,
        "skipped": None,
        "error": None,
        "outbox_status": None,
        "result_cd": None,
        "result_msg": None,
        "http_status": None,
    }
    locked = db.query(KraEventOutbox).filter(KraEventOutbox.id == row.id).with_for_update().first()
    if not locked:
        return {**_empty, "error": "outbox_row_missing"}

    st = (locked.processing_status or "").strip()
    if st == "processed":
        return {
            "ok": True,
            "skipped": "already_processed",
            "error": None,
            "outbox_status": "processed",
            "result_cd": None,
            "result_msg": None,
            "http_status": None,
        }

    payload = locked.payload_json if isinstance(locked.payload_json, dict) else {}
    source = str(payload.get("source") or "").strip()
    if source not in _ITEM_UPDATED_ALLOWED_SOURCES:
        msg = f"item_updated_source_not_allowed:{source or 'unknown'}"
        logger.warning("Skipping item.updated outbox id=%s reason=%s", locked.id, msg)
        KraOutboxService.mark_processed(db, locked, skip_reason=msg)
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="skipped",
            retry_count=int(locked.attempt_count or 0),
            last_error=msg,
        )
        return {
            "ok": True,
            "skipped": msg,
            "error": None,
            "outbox_status": "processed",
            "result_cd": None,
            "result_msg": None,
            "http_status": None,
        }

    branch = db.query(Branch).filter(Branch.id == locked.branch_id).first()
    if not branch:
        KraOutboxService.mark_retry(db, locked, error="branch_not_found")
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="retrying",
            retry_count=int(locked.attempt_count or 0),
            last_error="branch_not_found",
        )
        return {
            **_empty,
            "error": "branch_not_found",
            "outbox_status": locked.processing_status,
        }

    company = db.query(Company).filter(Company.id == branch.company_id).first()
    if not company or not bool(getattr(company, "kra_enabled", False)):
        KraOutboxService.mark_processed(db, locked, skip_reason="company_kra_disabled")
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="skipped",
            retry_count=int(locked.attempt_count or 0),
            last_error="company_kra_disabled",
        )
        return {
            "ok": True,
            "skipped": "company_kra_disabled",
            "error": None,
            "outbox_status": "processed",
            "result_cd": None,
            "result_msg": None,
            "http_status": None,
        }

    creds = db.query(BranchEtimsCredentials).filter(BranchEtimsCredentials.branch_id == branch.id).first()
    readiness = BranchKraReadinessResolver.resolve(db, branch=branch, creds=creds)
    if not bool(readiness.get("activation_allowed")):
        blockers = ",".join(readiness.get("blockers") or []) or "readiness_blocked"
        KraOutboxService.mark_retry(
            db,
            locked,
            error=f"item_sync_blocked:{readiness.get('readiness_state')}:{blockers}",
        )
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="retrying",
            retry_count=int(locked.attempt_count or 0),
            last_error=f"item_sync_blocked:{readiness.get('readiness_state')}:{blockers}",
        )
        return {
            **_empty,
            "error": f"item_sync_blocked:{readiness.get('readiness_state')}:{blockers}",
            "outbox_status": locked.processing_status,
        }

    if settings.KRA_OUTBOX_SHADOW_MODE:
        KraOutboxService.mark_processed(db, locked)
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="synced",
            retry_count=0,
            last_error=None,
            kra_result_msg="shadow_mode_processed",
        )
        return {
            "ok": True,
            "skipped": "shadow_mode",
            "error": None,
            "outbox_status": "processed",
            "result_cd": None,
            "result_msg": "shadow_mode_processed",
            "http_status": None,
        }

    res = sync_item_to_kra(
        db,
        item_id=locked.aggregate_id,
        company_id=locked.company_id,
        branch_id=locked.branch_id,
    )
    sync_ts = datetime.now(timezone.utc)
    if bool(res.get("ok")):
        KraOutboxService.mark_processed(db, locked)
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="synced",
            retry_count=0,
            last_error=None,
            http_status=res.get("http_status"),
            kra_result_cd=res.get("result_cd"),
            kra_result_msg=res.get("result_msg"),
            response_payload_json=res.get("response_payload_json"),
            synced_at=sync_ts,
        )
        return {
            "ok": True,
            "skipped": None,
            "error": None,
            "outbox_status": "processed",
            "result_cd": res.get("result_cd"),
            "result_msg": res.get("result_msg"),
            "http_status": res.get("http_status"),
        }

    err = str(res.get("error") or "item_sync_failed")
    if bool(res.get("non_retryable")):
        KraOutboxService.mark_processed(db, locked, skip_reason=err[:4000])
        KraOutboxService.upsert_item_branch_sync_status(
            db,
            company_id=locked.company_id,
            item_id=locked.aggregate_id,
            branch_id=locked.branch_id,
            status="failed",
            retry_count=int(locked.attempt_count or 0),
            last_error=err,
            http_status=res.get("http_status"),
            kra_result_cd=res.get("result_cd"),
            kra_result_msg=res.get("result_msg"),
            response_payload_json=res.get("response_payload_json"),
        )
        return {
            "ok": False,
            "skipped": None,
            "error": err,
            "outbox_status": locked.processing_status,
            "result_cd": res.get("result_cd"),
            "result_msg": res.get("result_msg"),
            "http_status": res.get("http_status"),
            "non_retryable": True,
        }

    KraOutboxService.mark_retry(db, locked, error=err)
    db.refresh(locked)
    KraOutboxService.upsert_item_branch_sync_status(
        db,
        company_id=locked.company_id,
        item_id=locked.aggregate_id,
        branch_id=locked.branch_id,
        status="failed" if (locked.processing_status or "").strip() == "dead_letter" else "retrying",
        retry_count=int(locked.attempt_count or 0),
        last_error=err,
        http_status=res.get("http_status"),
        kra_result_cd=res.get("result_cd"),
        kra_result_msg=res.get("result_msg"),
        response_payload_json=res.get("response_payload_json"),
    )
    return {
        "ok": False,
        "skipped": None,
        "error": err,
        "outbox_status": locked.processing_status,
        "result_cd": res.get("result_cd"),
        "result_msg": res.get("result_msg"),
        "http_status": res.get("http_status"),
    }


def _process_item_updated_event(db, row) -> None:
    process_item_updated_outbox_row(db, row)


def process_outbox_once() -> int:
    processed = 0
    claimed_ids = []
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
        claimed_ids = [row.id for row in rows]
        db.commit()

    for event_id in claimed_ids:
        with SessionLocal() as db:
            live = db.query(KraEventOutbox).filter(KraEventOutbox.id == event_id).first()
            if not live:
                continue
            try:
                if live.event_type == "sale.completed":
                    _process_sale_completed_event(db, live)
                elif live.event_type == "item.updated":
                    _process_item_updated_event(db, live)
                elif live.event_type == "inventory.stock_in":
                    _process_inventory_stock_in_event(db, live)
                elif live.event_type == "inventory.stock_ledger_align":
                    _process_inventory_stock_ledger_align_event(db, live)
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
