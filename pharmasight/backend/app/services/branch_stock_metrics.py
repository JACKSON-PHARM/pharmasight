"""
Branch stock KPIs for dashboard and reports.

Operational POS batching updates inventory_balances synchronously; SALE ledger rows
may lag or diverge when batch pools are out of sync. Dashboard stock position uses
inventory_balances as the authoritative on-hand quantity (same as POS stock checks).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.snapshot import InventoryBalance
from app.services.canonical_pricing import CanonicalPricingService


def count_items_in_stock_from_balances(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
) -> int:
    """Distinct SKUs with current_stock > 0 at branch (inventory_balances)."""
    q = (
        db.query(func.count(func.distinct(InventoryBalance.item_id)))
        .filter(
            InventoryBalance.company_id == company_id,
            InventoryBalance.branch_id == branch_id,
            InventoryBalance.current_stock > 0,
        )
    )
    return int(q.scalar() or 0)


def total_stock_value_from_balances(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
) -> Decimal:
    """
    Stock value = sum(current_stock × cost per retail unit).
    Cost source matches inventory valuation / POS snapshot (CanonicalPricingService).
    """
    rows = (
        db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
        .filter(
            InventoryBalance.company_id == company_id,
            InventoryBalance.branch_id == branch_id,
            InventoryBalance.current_stock > 0,
        )
        .all()
    )
    if not rows:
        return Decimal("0")

    item_ids = [r.item_id for r in rows]
    stock_map = {r.item_id: Decimal(str(r.current_stock or 0)) for r in rows}
    cost_per_retail = (
        CanonicalPricingService.get_cost_per_retail_for_valuation_batch(
            db, item_ids, branch_id, company_id
        )
        or {}
    )

    total = Decimal("0")
    for iid in item_ids:
        qty = stock_map.get(iid, Decimal("0"))
        if qty <= 0:
            continue
        total += qty * Decimal(str(cost_per_retail.get(iid) or 0))
    return total


def count_items_in_stock_from_ledger(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
) -> int:
    """Legacy: distinct items with positive ledger net qty (batch-layer sum)."""
    from app.models import InventoryLedger, Item

    company_item_ids = db.query(Item.id).filter(Item.company_id == company_id)
    subq = (
        db.query(InventoryLedger.item_id)
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.company_id == company_id,
            InventoryLedger.item_id.in_(company_item_ids),
        )
        .group_by(InventoryLedger.item_id)
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
    ).subquery()
    return int(db.query(func.count()).select_from(subq).scalar() or 0)
