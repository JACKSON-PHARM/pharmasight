"""
Post-commit pipeline: cash payment/cashbook, inventory reconciliation (FEFO/ledger), GL/KRA/lifecycle.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.models import SalesInvoice
from app.services.cashbook_service import ensure_implicit_invoice_payment_for_paid_invoice_if_missing
from app.services.sales_batch_reconciliation import run_sales_inventory_reconciliation
from app.services.sales_batch_side_effects import run_sales_batch_side_effects
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.snapshot_service import SnapshotService

logger = logging.getLogger(__name__)


def _ensure_cash_payment_and_cashbook(invoice_id: UUID, batched_by: UUID) -> None:
    """Best-effort: InvoicePayment + cashbook for batched cash sales (separate txn)."""
    db: Session = SessionLocal()
    try:
        invoice = db.query(SalesInvoice).filter(SalesInvoice.id == invoice_id).first()
        if not invoice:
            return
        if (invoice.status or "").upper() != "PAID":
            return
        ensure_implicit_invoice_payment_for_paid_invoice_if_missing(
            db, invoice=invoice, created_by=batched_by
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "cash payment/cashbook post-commit failed for invoice %s (sale still batched)",
            invoice_id,
        )
    finally:
        db.close()


def _touch_search_snapshots_after_batch(invoice_id: UUID) -> None:
    db: Session = SessionLocal()
    try:
        invoice = (
            db.query(SalesInvoice)
            .options(selectinload(SalesInvoice.items))
            .filter(SalesInvoice.id == invoice_id)
            .first()
        )
        if not invoice:
            return
        for line in invoice.items:
            try:
                SnapshotService.upsert_search_snapshot_last_sale(
                    db,
                    invoice.company_id,
                    invoice.branch_id,
                    line.item_id,
                    invoice.invoice_date,
                )
            except Exception as e:
                logger.warning(
                    "last_sale snapshot touch skipped invoice=%s item=%s: %s",
                    invoice_id,
                    line.item_id,
                    e,
                )
        item_ids = list({line.item_id for line in invoice.items})
        if item_ids:
            SnapshotRefreshService.enqueue_item_refreshes(
                db, invoice.company_id, invoice.branch_id, item_ids
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("search snapshot touch failed for invoice %s", invoice_id)
    finally:
        db.close()


def run_sales_batch_post_commit_pipeline(
    invoice_id: UUID,
    batched_by: UUID,
) -> None:
    _ensure_cash_payment_and_cashbook(invoice_id, batched_by)
    _touch_search_snapshots_after_batch(invoice_id)
    below_margin = run_sales_inventory_reconciliation(invoice_id, batched_by)
    run_sales_batch_side_effects(
        invoice_id,
        batched_by,
        below_margin_rows=below_margin,
    )
