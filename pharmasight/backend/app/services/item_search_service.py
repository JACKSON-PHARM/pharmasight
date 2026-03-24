"""
Item search: single entry point for GET /items/search.
One path only: item_branch_snapshot when branch_id is present. No fallback to heavy path.
On failure or missing branch_id we return []; fix snapshot/backfill instead of falling back.
"""
import logging
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ItemBranchSnapshot
from app.services.inventory_service import InventoryService, _unit_for_display
from app.utils.vat import vat_rate_to_percent

logger = logging.getLogger(__name__)


def _item_like_from_snapshot_row(r: Any) -> SimpleNamespace:
    """Build item-like object from snapshot row for format_quantity_display (no Item join)."""
    return SimpleNamespace(
        pack_size=getattr(r, "pack_size", 1) or 1,
        base_unit=getattr(r, "base_unit", None) or "piece",
        retail_unit=getattr(r, "retail_unit", None) or (getattr(r, "base_unit", None) or "piece"),
        supplier_unit=getattr(r, "supplier_unit", None) or "",
        wholesale_unit=getattr(r, "wholesale_unit", None) or (getattr(r, "base_unit", None) or "piece"),
        wholesale_units_per_supplier=getattr(r, "wholesale_units_per_supplier", 1) or 1,
        can_break_bulk=True,
    )


class ItemSearchService:
    """Single entry point for GET /items/search. Snapshot-only; no heavy fallback."""

    @staticmethod
    def search(
        db: Session,
        q: str,
        company_id: UUID,
        branch_id: Optional[UUID],
        limit: int,
        include_pricing: bool,
        context: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Snapshot-only item search. Returns (result_list, path, server_timing_str).
        path is always "item_branch_snapshot". Returns [] on failure or missing branch_id.
        """
        return _search_impl(db, q, company_id, branch_id, limit, include_pricing, context)


def _format_stock_display(quantity_retail: float, item_like: Optional[Any]) -> str:
    """Single shared place for stock_display. item_like is snapshot row or SimpleNamespace from snapshot."""
    if item_like is not None:
        return InventoryService.format_quantity_display(quantity_retail, item_like)
    return str(int(quantity_retail))


def _search_impl(
    db: Session,
    q: str,
    company_id: UUID,
    branch_id: Optional[UUID],
    limit: int,
    include_pricing: bool,
    context: Optional[str],
) -> Tuple[List[Dict[str, Any]], str, str]:
    t_start = time.perf_counter()
    search_term_pattern = f"%{q.lower()}%"

    # Single-table snapshot path (no Item join): keeps search <100ms at 1.5M rows.
    if branch_id is not None:
        try:
            rows = (
                db.query(ItemBranchSnapshot)
                .filter(
                    ItemBranchSnapshot.company_id == company_id,
                    ItemBranchSnapshot.branch_id == branch_id,
                    ItemBranchSnapshot.search_text.ilike(search_term_pattern),
                )
                .order_by(
                    (ItemBranchSnapshot.current_stock <= 0).asc(),
                    ItemBranchSnapshot.name.asc(),
                )
                .limit(limit)
                .all()
            )
        except Exception as e:
            t_done = time.perf_counter()
            snapshot_ms = (t_done - t_start) * 1000
            logger.warning(
                "[search] Snapshot query failed (no fallback): company_id=%s branch_id=%s error=%s",
                company_id, branch_id, e,
            )
            return [], "item_branch_snapshot", f"item_branch_snapshot;dur={snapshot_ms:.2f}"

        # Success (including 0 rows): use snapshot as sole cost/pricing authority
        item_ids = [r.item_id for r in rows]
        cost_map: Dict[UUID, Optional[float]] = {}
        sale_price_map: Dict[UUID, Optional[float]] = {}
        margin_map: Dict[UUID, Optional[float]] = {}
        if include_pricing and branch_id and item_ids:
            for r in rows:
                lp = getattr(r, "last_purchase_price", None)
                cost_map[r.item_id] = float(lp) if lp is not None else None
                # Use effective_selling_price (precomputed) when present; else selling_price
                sp = getattr(r, "effective_selling_price", None) or getattr(r, "selling_price", None)
                sale_price_map[r.item_id] = float(sp) if sp is not None else None
                mp = getattr(r, "margin_percent", None)
                margin_map[r.item_id] = float(mp) if mp is not None else None

        # Build response from snapshot only (item_like from snapshot row for stock_display; no Item join)
        from_snapshot_only = bool(include_pricing and branch_id and item_ids)
        result = []
        for r in rows:
            item_like = _item_like_from_snapshot_row(r)
            stock_float = float(r.current_stock or 0)
            stock_val = int(stock_float)
            purchase_price_override = cost_map.get(r.item_id) if from_snapshot_only else None
            sale_price_override = sale_price_map.get(r.item_id) if from_snapshot_only else None
            margin_percent_override = margin_map.get(r.item_id) if from_snapshot_only else None
            item_data = _canonical_item_from_snapshot_row(
                r,
                item_like,
                stock_float,
                stock_val,
                purchase_price_override=purchase_price_override,
                sale_price_override=sale_price_override,
                margin_percent_override=margin_map.get(r.item_id) if from_snapshot_only else None,
                price_source=getattr(r, "price_source", None),
                last_order_date=getattr(r, "last_order_date", None),
                from_snapshot_only=from_snapshot_only,
            )
            if context == "purchase_order":
                item_data["last_supply_date"] = getattr(r, "last_purchase_date", None)
                if item_data["last_supply_date"] and hasattr(item_data["last_supply_date"], "isoformat"):
                    item_data["last_supply_date"] = item_data["last_supply_date"].isoformat()
                item_data["last_unit_cost"] = item_data["purchase_price"]
                item_data["cheapest_supplier"] = ""
            result.append(item_data)
        t_done = time.perf_counter()
        snapshot_ms = (t_done - t_start) * 1000
        logger.info("[search] item_branch_snapshot: %.2f ms (results=%s)", snapshot_ms, len(result))
        server_timing = f"item_branch_snapshot;dur={snapshot_ms:.2f}"
        return result, "item_branch_snapshot", server_timing

    # No branch_id: snapshot path only; return empty (caller must pass branch_id for results)
    t_done = time.perf_counter()
    logger.info("[search] branch_id missing company_id=%s; returning [] (no fallback)", company_id)
    return [], "item_branch_snapshot", f"item_branch_snapshot;dur={(t_done - t_start) * 1000:.2f}"


def _canonical_item_from_snapshot_row(
    r: Any,
    item_like: Optional[Any],
    stock_float: float,
    stock_val: int,
    purchase_price_override: Optional[float] = None,
    sale_price_override: Optional[float] = None,
    margin_percent_override: Optional[float] = None,
    price_source: Optional[str] = None,
    last_order_date: Optional[Any] = None,
    from_snapshot_only: bool = False,
) -> Dict[str, Any]:
    """Build one canonical item dict from a snapshot row. item_like is from _item_like_from_snapshot_row (no Item join)."""
    if from_snapshot_only:
        purchase_val = float(purchase_price_override) if purchase_price_override is not None else None
        sale_val = float(sale_price_override) if sale_price_override is not None else None
        margin_val = margin_percent_override
        # Keep API `price` aligned with user-facing purchase cost in snapshot mode.
        # This avoids stale average_cost showing as item cost after manual cost corrections.
        price_val = float(purchase_val) if purchase_val is not None else float(r.average_cost or 0)
        # When sale price source is margin-based, derive sale from the current purchase cost
        # so cost/sale stay consistent even if a stale snapshot row is encountered.
        if (
            purchase_val is not None
            and margin_val is not None
            and price_source in ("company_margin", "default_margin")
        ):
            sale_val = float(Decimal(str(purchase_val)) * (Decimal("1") + (Decimal(str(margin_val)) / Decimal("100"))))
    else:
        price_val = float(r.average_cost or 0)
        purchase_val = float(r.last_purchase_price or r.average_cost or 0)
        sale_val = float(r.selling_price or 0)
        margin_val = float(r.margin_percent) if r.margin_percent is not None else None
    stock_display = _format_stock_display(stock_float, item_like)
    retail_unit = _unit_for_display(getattr(item_like, "retail_unit", None), "piece") if item_like else "piece"
    wholesale_unit = _unit_for_display(getattr(item_like, "wholesale_unit", None), _unit_for_display(r.base_unit, "piece")) if item_like else _unit_for_display(r.base_unit, "piece")
    supplier_unit = _unit_for_display(getattr(item_like, "supplier_unit", None), "") if item_like else ""
    pack_size = int(getattr(r, "pack_size", None) or getattr(item_like, "pack_size", None) or 1)
    wups = float(getattr(item_like, "wholesale_units_per_supplier", None) or getattr(r, "wholesale_units_per_supplier", None) or 1.0)
    out = {
        "id": str(r.item_id),
        "name": r.name or "",
        "base_unit": _unit_for_display(r.base_unit, "piece"),
        "retail_unit": retail_unit,
        "wholesale_unit": wholesale_unit,
        "supplier_unit": supplier_unit,
        "pack_size": max(1, pack_size),
        "wholesale_units_per_supplier": max(0.0001, wups),
        "price": price_val,
        "sku": (r.sku or "").strip(),
        "category": "",
        "is_active": True,
        "base_quantity": stock_float,
        "current_stock": stock_val,
        "stock_display": stock_display,
        "vat_rate": vat_rate_to_percent(r.vat_rate) if r.vat_rate is not None else 0,
        "vat_category": (r.vat_category or "ZERO_RATED").strip(),
        "purchase_price": purchase_val,
        "sale_price": sale_val,
        "last_supplier": "",
        "last_order_date": last_order_date.isoformat() if last_order_date and hasattr(last_order_date, "isoformat") else (last_order_date if last_order_date is not None else None),
        "margin_percent": margin_val,
        "next_expiry_date": r.next_expiry_date.isoformat() if r.next_expiry_date else None,
    }
    if price_source is not None:
        out["price_source"] = price_source
    return out


def _search_heavy_fallback(
    db: Session,
    q: str,
    company_id: UUID,
    branch_id: Optional[UUID],
    limit: int,
    include_pricing: bool,
    context: Optional[str],
    t_start: float,
) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    Single SELECT on item_branch_snapshot (unified). No legacy table reads.
    When branch_id is missing, returns []. Used by scripts or if primary path delegates.
    """
    if branch_id is None:
        t_done = time.perf_counter()
        return [], "heavy", f"heavy;dur={(t_done - t_start) * 1000:.2f}"
    result, _, server_timing = _search_impl(db, q, company_id, branch_id, limit, include_pricing, context)
    return result, "heavy", server_timing
