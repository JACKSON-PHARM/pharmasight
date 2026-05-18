"""Branch inventory valuation for GL reconciliation (operational, last_cost)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventory import InventoryLedger
from app.models.item import Item
from app.services.canonical_pricing import CanonicalPricingService


def branch_inventory_valuation(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    as_of_date: date | None = None,
) -> Decimal:
    """
    Operational inventory value = sum(stock_qty * cost_per_retail) using last_cost doctrine.
    Aligns with /api/inventory/valuation (last_cost, stock_only).
    """
    snap = as_of_date or date.today()
    end_of_day = datetime(snap.year, snap.month, snap.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    rows = (
        db.query(
            InventoryLedger.item_id,
            func.sum(InventoryLedger.quantity_delta).label("total_stock"),
        )
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.company_id == company_id,
            InventoryLedger.created_at <= end_of_day,
        )
        .group_by(InventoryLedger.item_id)
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
        .all()
    )
    if not rows:
        return Decimal("0")

    item_ids = [r.item_id for r in rows]
    stock_map = {r.item_id: Decimal(str(r.total_stock or 0)) for r in rows}
    cost_per_retail = CanonicalPricingService.get_cost_per_retail_for_valuation_batch(
        db, item_ids, branch_id, company_id
    ) or {}

    total = Decimal("0")
    for iid in item_ids:
        qty = stock_map.get(iid, Decimal("0"))
        if qty <= 0:
            continue
        cost = Decimal(str(cost_per_retail.get(iid) or 0))
        total += qty * cost
    return total.quantize(Decimal("0.01"))
