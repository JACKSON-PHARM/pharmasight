"""
Async inventory reconciliation for batched sales: FEFO allocation + SALE ledger rows + line COGS.

Runs after operational batch commit. Does not decrement inventory_balances (already done).
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.models import InventoryLedger, SalesInvoice, SalesInvoiceItem
from app.services.inventory_service import InventoryService
from app.services.item_units_helper import get_unit_multiplier_from_item
from app.services.pricing_config_service import is_line_price_at_promo, validate_line_price
from app.services.pricing_service import PricingService
from app.services.sales_batch_common import (
    SNAPSHOT_VS_LEDGER_WARN_THRESHOLD,
    sustainable_min_margin_pct,
    total_cost_from_allocations,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


from app.services.sales_batch_common import user_has_sell_below_min_margin


def reconcile_sales_invoice_inventory(
    db: Session,
    invoice: SalesInvoice,
    batched_by: UUID,
) -> Optional[list]:
    """
    Idempotent FEFO + SALE ledger for a batched invoice. Returns below_margin_rows for side effects.
    """
    existing = (
        db.query(InventoryLedger.id)
        .filter(
            InventoryLedger.reference_type == "sales_invoice",
            InventoryLedger.reference_id == invoice.id,
            InventoryLedger.transaction_type == "SALE",
        )
        .limit(1)
        .first()
    )
    if existing:
        logger.info("reconcile_sales_invoice_inventory: already reconciled invoice=%s", invoice.id)
        return None

    below_margin_rows: list = []
    sustainable_min_margin = sustainable_min_margin_pct(db, invoice.company_id)
    ledger_entries: List[InventoryLedger] = []

    for invoice_item in invoice.items:
        item = invoice_item.item
        if not item:
            logger.warning("reconcile: missing item %s on invoice %s", invoice_item.item_id, invoice.id)
            continue

        quantity_base = InventoryService.convert_to_base_units(
            db,
            invoice_item.item_id,
            float(invoice_item.quantity),
            invoice_item.unit_name,
        )
        allocations = InventoryService.allocate_stock_fefo(
            db,
            invoice_item.item_id,
            invoice.branch_id,
            quantity_base,
            invoice_item.unit_name,
            company_id=invoice.company_id,
        )

        qty_base_dec = Decimal(str(quantity_base))
        total_line_ledger_cost = total_cost_from_allocations(allocations)

        if allocations and qty_base_dec > 0:
            cost_per_base_unit = total_line_ledger_cost / qty_base_dec
            ref_base = getattr(invoice_item, "margin_reference_unit_cost_base", None)
            had_margin_ref_at_draft = ref_base is not None
            if ref_base is None:
                ref_base = PricingService.get_margin_reference_cost_per_base(
                    db, invoice_item.item_id, invoice.branch_id, invoice.company_id
                )
                invoice_item.margin_reference_unit_cost_base = ref_base

            mult = get_unit_multiplier_from_item(item, invoice_item.unit_name)
            if mult is not None and mult > 0 and ref_base is not None:
                unit_price_val = invoice_item.unit_price_exclusive or Decimal("0")
                cost_per_sale_unit_ref = ref_base * mult
                if not had_margin_ref_at_draft:
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
                        raise ValueError(validation.get("message", "Price validation failed."))

                if (
                    sustainable_min_margin is not None
                    and sustainable_min_margin > 0
                    and cost_per_sale_unit_ref > 0
                ):
                    computed_margin_pct = (
                        (unit_price_val - cost_per_sale_unit_ref)
                        / cost_per_sale_unit_ref
                        * Decimal("100")
                    )
                    if computed_margin_pct < sustainable_min_margin:
                        below_margin_rows.append(
                            {
                                "company_id": str(invoice.company_id),
                                "branch_id": str(invoice.branch_id),
                                "sales_invoice_id": str(invoice.id),
                                "sales_invoice_item_id": str(invoice_item.id),
                                "invoice_no": str(invoice.invoice_no),
                                "invoice_date": invoice.invoice_date,
                                "payment_mode": getattr(invoice, "payment_mode", None),
                                "customer_name": getattr(invoice, "customer_name", None),
                                "item_id": str(invoice_item.item_id),
                                "item_name": getattr(item, "name", None),
                                "unit_name": str(invoice_item.unit_name or ""),
                                "quantity_sale_unit": Decimal(str(invoice_item.quantity or 0)),
                                "quantity_base_unit": qty_base_dec,
                                "unit_price_exclusive": Decimal(
                                    str(invoice_item.unit_price_exclusive or 0)
                                ),
                                "reference_unit_cost_base": Decimal(str(ref_base))
                                if ref_base is not None
                                else None,
                                "sustainable_min_margin_pct": sustainable_min_margin,
                                "computed_margin_pct": computed_margin_pct,
                                "created_by": str(batched_by) if batched_by else None,
                            }
                        )

            old_uc = invoice_item.unit_cost_used
            if old_uc is not None and float(old_uc) > 0:
                snap_cogs = qty_base_dec * Decimal(str(old_uc))
                line_rev = invoice_item.line_total_exclusive or Decimal("0")
                diff = abs(snap_cogs - total_line_ledger_cost)
                if line_rev > 0 and diff > (SNAPSHOT_VS_LEDGER_WARN_THRESHOLD * line_rev):
                    logger.warning(
                        "Sales line snapshot COGS vs ledger (reconcile): invoice=%s item=%s "
                        "snap_cogs=%s ledger_cogs=%s line_total_excl=%s",
                        invoice.invoice_no,
                        invoice_item.item_id,
                        snap_cogs,
                        total_line_ledger_cost,
                        line_rev,
                    )
            invoice_item.unit_cost_used = cost_per_base_unit
            invoice_item.batch_id = allocations[0]["ledger_entry_id"]

        for allocation in allocations:
            qty = Decimal(str(allocation["quantity"]))
            uc = Decimal(str(allocation["unit_cost"]))
            ledger_entries.append(
                InventoryLedger(
                    company_id=invoice.company_id,
                    branch_id=invoice.branch_id,
                    item_id=invoice_item.item_id,
                    batch_number=allocation["batch_number"],
                    expiry_date=allocation["expiry_date"],
                    transaction_type="SALE",
                    reference_type="sales_invoice",
                    reference_id=invoice.id,
                    document_number=invoice.invoice_no,
                    quantity_delta=-qty,
                    unit_cost=uc,
                    total_cost=uc * qty,
                    created_by=batched_by,
                )
            )

    for entry in ledger_entries:
        db.add(entry)
    db.flush()
    return below_margin_rows or None


def run_sales_inventory_reconciliation(
    invoice_id: UUID, batched_by: UUID
) -> Optional[list]:
    """Background worker entry: FEFO + ledger with retries. Returns below_margin_rows if any."""
    last_err: Optional[Exception] = None
    below_margin: Optional[list] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        db = SessionLocal()
        try:
            invoice = (
                db.query(SalesInvoice)
                .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
                .filter(SalesInvoice.id == invoice_id)
                .first()
            )
            if not invoice:
                logger.warning("reconcile: invoice %s not found", invoice_id)
                return None
            if invoice.status not in ("BATCHED", "PAID"):
                logger.warning(
                    "reconcile: invoice %s status=%s — skip", invoice_id, invoice.status
                )
                return None
            t0 = time.perf_counter()
            below_margin = reconcile_sales_invoice_inventory(db, invoice, batched_by)
            db.commit()
            ms = round((time.perf_counter() - t0) * 1000, 1)
            logger.info(
                "reconcile_sales_invoice_inventory: invoice=%s attempt=%s duration_ms=%s",
                invoice_id,
                attempt,
                ms,
            )
            return below_margin
        except Exception as e:
            db.rollback()
            last_err = e
            logger.exception(
                "reconcile_sales_invoice_inventory failed invoice=%s attempt=%s/%s",
                invoice_id,
                attempt,
                _MAX_RETRIES,
            )
        finally:
            db.close()
    if last_err:
        logger.error(
            "reconcile_sales_invoice_inventory exhausted retries invoice=%s: %s",
            invoice_id,
            last_err,
        )
    return below_margin
