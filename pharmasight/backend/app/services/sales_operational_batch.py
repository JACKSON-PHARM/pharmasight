"""
POS operational sales batch: short transaction — snapshot stock decrement + invoice finalization.

FEFO allocation and inventory_ledger SALE rows run asynchronously (sales_batch_reconciliation).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import SalesInvoice, SalesInvoiceItem
from app.services.inventory_service import InventoryService
from app.services.pricing_config_service import is_line_price_at_promo, validate_line_price
from app.services.pricing_service import PricingService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.snapshot_service import SnapshotService
from app.services.item_units_helper import get_unit_multiplier_from_item
from app.services.sales_batch_common import user_has_sell_below_min_margin
from app.services.sales_reconciliation_queue_service import enqueue_operational_posted

logger = logging.getLogger(__name__)


def commit_operational_sales_batch(
    db: Session,
    invoice: SalesInvoice,
    batched_by: UUID,
    *,
    timings: Optional[Dict[str, float]] = None,
) -> None:
    """
    Finalize invoice and decrement inventory_balances. Does not write SALE ledger rows.
    Caller must hold invoice FOR UPDATE and have already applied draft line overrides.
    """
    t0 = time.perf_counter()

    balance_rows: List[Tuple[UUID, UUID, UUID, Decimal]] = []
    for invoice_item in invoice.items:
        item = invoice_item.item
        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {invoice_item.item_id} not found. Cannot batch.",
            )

        ref_base = getattr(invoice_item, "margin_reference_unit_cost_base", None)
        if ref_base is None:
            ref_base = PricingService.get_margin_reference_cost_per_base(
                db, invoice_item.item_id, invoice.branch_id, invoice.company_id
            )
            invoice_item.margin_reference_unit_cost_base = ref_base
        mult = get_unit_multiplier_from_item(item, invoice_item.unit_name)
        if ref_base is not None and mult is not None and mult > 0:
            unit_price_val = invoice_item.unit_price_exclusive or Decimal("0")
            cost_per_sale_unit_ref = ref_base * mult
            user_has_override = user_has_sell_below_min_margin(
                db, batched_by, invoice.branch_id
            )
            is_promo = is_line_price_at_promo(
                db,
                invoice_item.item_id,
                invoice_item.unit_name or "",
                unit_price_val,
            )
            validation = validate_line_price(
                db,
                invoice.company_id,
                invoice_item.item_id,
                unit_price_val,
                cost_per_sale_unit_ref,
                user_has_override,
                branch_id=invoice.branch_id,
                is_promo_price=is_promo,
            )
            if not validation.get("allowed"):
                raise HTTPException(
                    status_code=400,
                    detail=validation.get("message", "Price validation failed."),
                )

        is_available, available, required = InventoryService.check_stock_availability(
            db,
            invoice_item.item_id,
            invoice.branch_id,
            float(invoice_item.quantity),
            invoice_item.unit_name,
            company_id=invoice.company_id,
        )
        if not is_available:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient stock for {invoice_item.item_name or item.name}. "
                    f"Available: {available}, Required: {required}"
                ),
            )
        quantity_base = InventoryService.convert_to_base_units(
            db,
            invoice_item.item_id,
            float(invoice_item.quantity),
            invoice_item.unit_name,
        )
        balance_rows.append(
            (
                invoice.company_id,
                invoice.branch_id,
                invoice_item.item_id,
                Decimal(str(-quantity_base)),
            )
        )

    if timings is not None:
        timings["StockCheckMs"] = round((time.perf_counter() - t0) * 1000, 1)

    t1 = time.perf_counter()
    try:
        SnapshotService.apply_inventory_balance_deltas_locked(
            db,
            balance_rows,
            document_number=str(invoice.invoice_no or invoice.id),
        )
        item_ids = {row[2] for row in balance_rows}
        for item_id in item_ids:
            SnapshotService.upsert_search_snapshot_last_sale(
                db,
                invoice.company_id,
                invoice.branch_id,
                item_id,
                invoice.invoice_date,
            )
            SnapshotRefreshService.refresh_item_sync(
                db,
                invoice.company_id,
                invoice.branch_id,
                item_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if timings is not None:
        timings["SnapshotDecrementMs"] = round((time.perf_counter() - t1) * 1000, 1)

    t2 = time.perf_counter()
    invoice.batched = True
    invoice.batched_by = batched_by
    invoice.batched_at = datetime.utcnow()

    if getattr(invoice, "payment_mode", "").lower() == "cash":
        invoice.payment_status = "PAID"
        invoice.status = "PAID"
        invoice.cashier_approved = True
        invoice.approved_by = batched_by
        invoice.approved_at = datetime.now(timezone.utc)
        # InvoicePayment + cashbook inflow run post-commit (see sales_batch_post_commit) so a
        # cashbook failure cannot roll back stock decrement / PAID status.
    else:
        invoice.status = "BATCHED"

    if invoice.customer_id:
        from app.models import Customer
        from app.services.customer_invoice_payment_service import sync_customer_invoice_paid_from_settlements
        from app.services.customer_sales_service import (
            assert_customer_credit_for_batch,
            post_customer_ledger_on_batch,
            set_due_date_from_customer,
        )

        customer = (
            db.query(Customer)
            .filter(Customer.id == invoice.customer_id, Customer.company_id == invoice.company_id)
            .first()
        )
        if customer:
            assert_customer_credit_for_batch(
                db, invoice, customer, invoice.company_id, invoice.branch_id
            )
            set_due_date_from_customer(invoice, customer)
            pm = (getattr(invoice, "payment_mode", None) or "").strip().lower()
            is_cash_paid = pm == "cash" and (invoice.status or "").strip().upper() == "PAID"
            if is_cash_paid:
                # Retail cash collected at batch: no AR debit; balance stays zero.
                invoice.balance = Decimal("0")
            else:
                sync_customer_invoice_paid_from_settlements(db, invoice)
                post_customer_ledger_on_batch(db, invoice, customer, invoice.company_id)

    if timings is not None:
        timings["FinalizeMs"] = round((time.perf_counter() - t2) * 1000, 1)

    try:
        enqueue_operational_posted(db, invoice)
    except Exception:
        logger.exception(
            "enqueue_operational_posted failed invoice=%s (batch still committed if caller commits)",
            invoice.id,
        )
