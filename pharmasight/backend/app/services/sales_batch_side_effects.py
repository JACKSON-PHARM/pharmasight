"""
Post-commit side effects for sales invoice batch (GL, KRA outbox, commercial lifecycle, order book).

Runs outside the stock batch transaction so POS batch TTFB is dominated by inventory writes only.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.models import InventoryLedger, SalesInvoice, SalesInvoiceItem
from app.services.sales_reconciliation_queue_service import (
    mark_financially_posted,
    mark_fully_reconciled,
)

logger = logging.getLogger(__name__)


def run_sales_batch_side_effects(
    invoice_id: UUID,
    batched_by: UUID,
    *,
    below_margin_rows: Optional[list] = None,
) -> None:
    """Best-effort hooks after batch commit; uses its own DB session."""
    db = SessionLocal()
    try:
        invoice = (
            db.query(SalesInvoice)
            .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
            .filter(SalesInvoice.id == invoice_id)
            .first()
        )
        if not invoice:
            logger.warning("batch_side_effects: invoice %s not found", invoice_id)
            return

        ledger_entries: List[InventoryLedger] = (
            db.query(InventoryLedger)
            .filter(
                InventoryLedger.reference_type == "sales_invoice",
                InventoryLedger.reference_id == invoice_id,
                InventoryLedger.transaction_type == "SALE",
            )
            .all()
        )

        if below_margin_rows:
            try:
                from sqlalchemy import text

                db.execute(
                    text(
                        """
                        INSERT INTO below_margin_sales_lines (
                            company_id, branch_id, sales_invoice_id, sales_invoice_item_id,
                            invoice_no, invoice_date, payment_mode, customer_name,
                            item_id, item_name, unit_name, quantity_sale_unit, quantity_base_unit,
                            unit_price_exclusive, reference_unit_cost_base,
                            sustainable_min_margin_pct, computed_margin_pct, created_by
                        )
                        VALUES (
                            :company_id, :branch_id, :sales_invoice_id, :sales_invoice_item_id,
                            :invoice_no, :invoice_date, :payment_mode, :customer_name,
                            :item_id, :item_name, :unit_name, :quantity_sale_unit, :quantity_base_unit,
                            :unit_price_exclusive, :reference_unit_cost_base,
                            :sustainable_min_margin_pct, :computed_margin_pct, :created_by
                        )
                        """
                    ),
                    below_margin_rows,
                )
            except Exception as e:
                logger.warning("Below-margin log insert failed (ignored): %s", e)

        try:
            from app.accounting.posting.sales import post_gl_for_sales_invoice_batch

            post_gl_for_sales_invoice_batch(
                db, invoice, ledger_entries, posted_by=batched_by
            )
            mark_financially_posted(db, invoice_id)
        except Exception:
            logger.exception(
                "accounting: GL sales batch hook failed for invoice %s (non-fatal)",
                invoice_id,
            )

        try:
            from app.config import settings
            from app.services.etims.kra_company_activation import company_kra_execution_enabled
            from app.services.etims.kra_outbox_service import KraOutboxService
            from app.services.etims.invoice_etims_snapshot import apply_etims_snapshots_on_batch
            from app.models.company import BranchEtimsCredentials

            if company_kra_execution_enabled(db, invoice.company_id):
                creds = (
                    db.query(BranchEtimsCredentials)
                    .filter(BranchEtimsCredentials.branch_id == invoice.branch_id)
                    .first()
                )
                if creds and bool(getattr(creds, "enabled", False)):
                    apply_etims_snapshots_on_batch(invoice)
                    KraOutboxService.enqueue_sale_completed(
                        db,
                        invoice=invoice,
                        source="sales.batch",
                        max_attempts=max(int(settings.KRA_OUTBOX_MAX_ATTEMPTS or 12), 1),
                    )
        except Exception:
            logger.exception("KRA batch side effects failed for invoice %s (non-fatal)", invoice_id)

        try:
            from app.services.commercial_transaction_lifecycle import on_sales_invoice_batched

            on_sales_invoice_batched(db, invoice, batched_by=batched_by)
        except Exception:
            logger.exception(
                "commercial_transaction_lifecycle: batch hook failed for invoice %s (non-fatal)",
                invoice_id,
            )

        db.commit()

        try:
            from app.finance.events.hooks import on_sales_invoice_batched_financial_event

            on_sales_invoice_batched_financial_event(db, invoice)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "financial_events: sales invoice batch hook failed (non-fatal) invoice=%s",
                invoice_id,
            )

        try:
            from app.services.order_book_service import OrderBookService

            entries = OrderBookService.process_sale_for_order_book(
                db=db,
                company_id=invoice.company_id,
                branch_id=invoice.branch_id,
                invoice_id=invoice.id,
                user_id=batched_by,
            )
            if entries:
                db.commit()
                logger.info(
                    "Auto-added %s items to order book from invoice %s",
                    len(entries),
                    invoice_id,
                )
        except Exception as e:
            db.rollback()
            logger.warning("Order book auto-add failed for invoice %s: %s", invoice_id, e)

        try:
            mark_fully_reconciled(db, invoice_id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "mark_fully_reconciled failed for invoice %s", invoice_id
            )
    except Exception:
        logger.exception("batch_side_effects failed for invoice %s", invoice_id)
    finally:
        db.close()
