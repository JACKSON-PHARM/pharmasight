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

from sqlalchemy import case, func, and_, text
from sqlalchemy.orm import Session

from app.models import (
    Item,
    ItemBranchSnapshot,
    ItemBranchPurchaseSnapshot,
    ItemBranchSearchSnapshot,
    InventoryBalance,
    Supplier,
)
from app.services.inventory_service import InventoryService, _unit_for_display
from app.services.pricing_service import PricingService
from app.services.order_book_service import OrderBookService
from app.utils.vat import vat_rate_to_percent

logger = logging.getLogger(__name__)


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


def _format_stock_display(quantity_retail: float, item: Optional[Item]) -> str:
    """Single shared place for stock_display. Used by both snapshot and heavy paths."""
    if item is not None:
        return InventoryService.format_quantity_display(quantity_retail, item)
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

    # Primary: snapshot path when branch_id is present (single query: snapshot + item columns for display)
    if branch_id is not None:
        try:
            rows = (
                db.query(
                    ItemBranchSnapshot.item_id,
                    ItemBranchSnapshot.name,
                    ItemBranchSnapshot.pack_size,
                    ItemBranchSnapshot.base_unit,
                    ItemBranchSnapshot.sku,
                    ItemBranchSnapshot.vat_rate,
                    ItemBranchSnapshot.vat_category,
                    ItemBranchSnapshot.current_stock,
                    ItemBranchSnapshot.average_cost,
                    ItemBranchSnapshot.last_purchase_price,
                    ItemBranchSnapshot.selling_price,
                    ItemBranchSnapshot.margin_percent,
                    ItemBranchSnapshot.next_expiry_date,
                    Item.retail_unit,
                    Item.supplier_unit,
                    Item.wholesale_unit,
                    Item.wholesale_units_per_supplier,
                )
                .join(Item, Item.id == ItemBranchSnapshot.item_id)
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

        # Success (including 0 rows): build canonical response from snapshot only
        result = []
        for r in rows:
            item_like = SimpleNamespace(
                retail_unit=getattr(r, "retail_unit", None),
                supplier_unit=getattr(r, "supplier_unit", None),
                pack_size=getattr(r, "pack_size", 1) or 1,
                base_unit=getattr(r, "base_unit", None),
                wholesale_unit=getattr(r, "wholesale_unit", None),
                wholesale_units_per_supplier=getattr(r, "wholesale_units_per_supplier", 1) or 1,
            )
            stock_float = float(r.current_stock or 0)
            stock_val = int(stock_float)
            item_data = _canonical_item_from_snapshot_row(r, item_like, stock_float, stock_val)
            if context == "purchase_order":
                item_data["last_supply_date"] = None
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
    item_obj: Optional[Item],
    stock_float: float,
    stock_val: int,
) -> Dict[str, Any]:
    """Build one canonical item dict from a snapshot row. Shared shape for snapshot path."""
    price_val = float(r.average_cost or 0)
    purchase_val = float(r.last_purchase_price or r.average_cost or 0)
    sale_val = float(r.selling_price or 0)
    stock_display = _format_stock_display(stock_float, item_obj)
    retail_unit = _unit_for_display(item_obj.retail_unit, "piece") if item_obj else "piece"
    return {
        "id": str(r.item_id),
        "name": r.name or "",
        "base_unit": _unit_for_display(r.base_unit, "piece"),
        "retail_unit": retail_unit,
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
        "last_order_date": None,
        "margin_percent": float(r.margin_percent) if r.margin_percent is not None else None,
        "next_expiry_date": r.next_expiry_date.isoformat() if r.next_expiry_date else None,
    }


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
    Legacy heavy path (items + inventory_balances + snapshots + pricing).
    Not used by GET /items/search; search is snapshot-only. Kept for reference or one-off scripts.
    """
    steps: List[tuple] = []
    search_term_lower = q.lower()
    search_term_pattern = f"%{search_term_lower}%"
    search_term_start = f"{search_term_lower}%"

    relevance_score = case(
        (func.lower(Item.name).like(search_term_start), 1000),
        (func.lower(Item.name).like(search_term_pattern), 500),
        (and_(Item.sku.isnot(None), func.lower(Item.sku).like(search_term_start)), 100),
        (and_(Item.sku.isnot(None), func.lower(Item.sku).like(search_term_pattern)), 50),
        (and_(Item.barcode.isnot(None), func.lower(Item.barcode).like(search_term_start)), 100),
        (and_(Item.barcode.isnot(None), func.lower(Item.barcode).like(search_term_pattern)), 50),
        else_=0,
    ).label("relevance_score")
    search_combined_expr = text(
        "items_search_combined_immutable(items.name, items.sku, items.barcode) ILIKE :pat"
    ).bindparams(pat=search_term_pattern)

    base_cols = [
        Item.id,
        Item.name,
        Item.base_unit,
        Item.sku,
        Item.category,
        Item.is_active,
        Item.vat_rate,
        Item.vat_category,
        relevance_score,
    ]
    base_query = db.query(*base_cols).filter(
        Item.company_id == company_id,
        Item.is_active == True,
        search_combined_expr,
    )
    items = base_query.order_by(relevance_score.desc(), func.lower(Item.name).asc()).limit(limit).all()
    t_base = time.perf_counter()
    steps.append(("1_base_query", round((t_base - t_start) * 1000, 2)))

    if not items:
        server_timing = ", ".join(f"{n};dur={d}" for n, d in steps)
        return [], "heavy", server_timing

    item_ids = [item.id for item in items]

    stock_map: Dict[UUID, int] = {}
    if branch_id:
        stock_data = (
            db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
            .filter(
                InventoryBalance.item_id.in_(item_ids),
                InventoryBalance.company_id == company_id,
                InventoryBalance.branch_id == branch_id,
            )
            .all()
        )
        stock_map = {row.item_id: int(float(row.current_stock) or 0) for row in stock_data}
        items = sorted(
            items,
            key=lambda r: (
                0 if stock_map.get(r.id, 0) > 0 else 1,
                -(getattr(r, "relevance_score", 0) or 0),
                (r.name or "").lower(),
            ),
        )
    t_stock = time.perf_counter()
    steps.append(("2_stock", round((t_stock - t_base) * 1000, 2)))

    purchase_price_map: Dict[UUID, float] = {}
    last_supplier_map: Dict[UUID, str] = {}
    last_order_date_map: Dict[UUID, Optional[str]] = {}
    sale_price_map: Dict[UUID, float] = {}
    last_supply_date_map: Dict[UUID, Optional[str]] = {}
    last_unit_cost_ledger_map: Dict[UUID, float] = {}
    cheapest_supplier_map: Dict[UUID, str] = {}

    t_pricing = time.perf_counter()
    last_purchases: List[Any] = []
    if include_pricing and branch_id:
        try:
            rows = db.execute(
                text("""
                SELECT ids.item_id,
                       p.last_purchase_price, p.last_supplier_id, p.last_purchase_date,
                       s.last_order_date
                FROM unnest(CAST(:item_ids AS uuid[])) AS ids(item_id)
                LEFT JOIN item_branch_purchase_snapshot p
                  ON p.item_id = ids.item_id AND p.branch_id = :branch_id AND p.company_id = :company_id
                LEFT JOIN item_branch_search_snapshot s
                  ON s.item_id = ids.item_id AND s.branch_id = :branch_id AND s.company_id = :company_id
                """),
                {"item_ids": item_ids, "branch_id": branch_id, "company_id": company_id},
            ).fetchall()
            for row in rows:
                iid = row[0]
                if row[1] is not None or row[2] is not None or row[3] is not None:
                    last_purchases.append(SimpleNamespace(
                        item_id=iid,
                        last_purchase_price=row[1],
                        last_supplier_id=row[2],
                        last_purchase_date=row[3],
                    ))
                last_order_date_map[iid] = row[4].isoformat() if row[4] else None
        except Exception as e:
            logger.warning("[search] heavy combined snapshot query failed, two queries: %s", e)
            last_purchases = (
                db.query(
                    ItemBranchPurchaseSnapshot.item_id,
                    ItemBranchPurchaseSnapshot.last_purchase_price,
                    ItemBranchPurchaseSnapshot.last_supplier_id,
                    ItemBranchPurchaseSnapshot.last_purchase_date,
                )
                .filter(
                    ItemBranchPurchaseSnapshot.item_id.in_(item_ids),
                    ItemBranchPurchaseSnapshot.company_id == company_id,
                    ItemBranchPurchaseSnapshot.branch_id == branch_id,
                )
                .all()
            )
            last_order_rows = (
                db.query(ItemBranchSearchSnapshot.item_id, ItemBranchSearchSnapshot.last_order_date)
                .filter(
                    ItemBranchSearchSnapshot.item_id.in_(item_ids),
                    ItemBranchSearchSnapshot.company_id == company_id,
                    ItemBranchSearchSnapshot.branch_id == branch_id,
                )
                .all()
            )
            last_order_date_map = {
                row.item_id: row.last_order_date.isoformat() if row.last_order_date else None
                for row in last_order_rows
            }

        purchase_price_map = {
            row.item_id: float(row.last_purchase_price) if row.last_purchase_price else 0.0
            for row in last_purchases
        }
        supplier_ids = {row.last_supplier_id for row in last_purchases if row.last_supplier_id}
        ids_without_supplier = [i for i in item_ids if i not in {row.item_id for row in last_purchases if row.last_supplier_id}]
        default_rows = []
        if ids_without_supplier:
            default_rows = db.query(Item.id, Item.default_supplier_id).filter(
                Item.id.in_(ids_without_supplier),
                Item.default_supplier_id.isnot(None),
            ).all()
        default_supplier_ids = {r.default_supplier_id for r in default_rows if r.default_supplier_id}
        cheapest_supplier_ids: Dict[UUID, Optional[UUID]] = {}
        if context == "purchase_order":
            cheapest_supplier_ids = OrderBookService.get_cheapest_supplier_ids_batch(db, item_ids, company_id)
            supplier_ids |= {sid for sid in cheapest_supplier_ids.values() if sid is not None}
        supplier_ids |= default_supplier_ids
        if supplier_ids:
            suppliers = {s.id: s.name for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()}
            last_supplier_map = {row.item_id: suppliers.get(row.last_supplier_id, "") for row in last_purchases if row.last_supplier_id}
            for r in default_rows:
                if r.default_supplier_id:
                    last_supplier_map[r.id] = suppliers.get(r.default_supplier_id, "")
            if context == "purchase_order":
                cheapest_supplier_map.update({
                    iid: suppliers.get(sid, "")
                    for iid, sid in cheapest_supplier_ids.items()
                    if sid is not None
                })

        if context == "purchase_order":
            for row in last_purchases:
                last_supply_date_map[row.item_id] = row.last_purchase_date.isoformat() if row.last_purchase_date else None
                last_unit_cost_ledger_map[row.item_id] = float(row.last_purchase_price) if row.last_purchase_price else 0.0

        for _ in items:
            sale_price_map[_.id] = 0.0
    t_after_pricing = time.perf_counter()
    steps.append(("3_pricing", round((t_after_pricing - t_pricing) * 1000, 2)))

    cost_from_ledger_map: Dict[UUID, float] = {}
    if branch_id:
        snapshot_costs = (
            db.query(ItemBranchPurchaseSnapshot.item_id, ItemBranchPurchaseSnapshot.last_purchase_price)
            .filter(
                ItemBranchPurchaseSnapshot.item_id.in_(item_ids),
                ItemBranchPurchaseSnapshot.company_id == company_id,
                ItemBranchPurchaseSnapshot.branch_id == branch_id,
                ItemBranchPurchaseSnapshot.last_purchase_price.isnot(None),
            )
            .all()
        )
        cost_from_ledger_map = {row.item_id: float(row.last_purchase_price) for row in snapshot_costs}
        missing_cost_ids = [iid for iid in item_ids if iid not in cost_from_ledger_map]
        if missing_cost_ids:
            default_cost_rows = (
                db.query(Item.id, Item.default_cost_per_base)
                .filter(Item.id.in_(missing_cost_ids), Item.company_id == company_id)
                .all()
            )
            for row in default_cost_rows:
                cost_from_ledger_map[row.id] = float(row.default_cost_per_base) if row.default_cost_per_base is not None else 0.0
        for iid in item_ids:
            if iid not in cost_from_ledger_map:
                cost_from_ledger_map[iid] = 0.0

    items_full_map: Dict[UUID, Item] = {}
    if branch_id:
        items_full = db.query(Item).filter(Item.id.in_(item_ids)).all()
        items_full_map = {item.id: item for item in items_full}

    if include_pricing and branch_id and item_ids:
        markup_batch = PricingService.get_markup_percent_batch(
            db, item_ids, company_id, item_map=items_full_map or None
        )
        for iid in item_ids:
            cost = cost_from_ledger_map.get(iid, 0.0) or 0.0
            margin = markup_batch.get(iid, Decimal("30"))
            sale_price_map[iid] = round(float(Decimal(str(cost)) * (Decimal("1") + margin / Decimal("100"))), 4)

    result = []
    for item in items:
        price_from_ledger = float(cost_from_ledger_map.get(item.id, 0)) if branch_id else 0.0
        purchase_price_val = purchase_price_map.get(item.id, price_from_ledger) if include_pricing else price_from_ledger
        last_unit_cost_val = (
            last_unit_cost_ledger_map.get(item.id, purchase_price_map.get(item.id, price_from_ledger))
            if context == "purchase_order"
            else None
        )
        stock_qty = float(stock_map.get(item.id, 0) or 0) if branch_id else 0
        item_obj = items_full_map.get(item.id) if branch_id else None
        stock_display = _format_stock_display(stock_qty, item_obj)
        retail_unit_val = _unit_for_display(item_obj.retail_unit, "piece") if item_obj else "piece"

        item_data: Dict[str, Any] = {
            "id": str(item.id),
            "name": item.name,
            "base_unit": _unit_for_display(item.base_unit, "piece"),
            "retail_unit": retail_unit_val,
            "price": price_from_ledger,
            "sku": item.sku or "",
            "category": getattr(item, "category", None) or "",
            "is_active": getattr(item, "is_active", True),
            "base_quantity": stock_qty if branch_id else None,
            "current_stock": stock_map.get(item.id, 0) if branch_id else None,
            "stock_display": stock_display,
            "vat_rate": vat_rate_to_percent(item.vat_rate),
            "vat_category": getattr(item, "vat_category", None) or "ZERO_RATED",
            "purchase_price": purchase_price_val,
            "sale_price": sale_price_map.get(item.id, 0.0) if include_pricing else 0.0,
            "last_supplier": last_supplier_map.get(item.id, "") if include_pricing else "",
            "last_order_date": last_order_date_map.get(item.id, None) if include_pricing else None,
            "margin_percent": None,
            "next_expiry_date": None,
        }
        if context == "purchase_order":
            item_data["last_supply_date"] = last_supply_date_map.get(item.id, None)
            item_data["last_unit_cost"] = last_unit_cost_val if last_unit_cost_val is not None else purchase_price_val
            item_data["cheapest_supplier"] = cheapest_supplier_map.get(item.id, "")
        result.append(item_data)

    t_done = time.perf_counter()
    steps.append(("4_result_loop", round((t_done - t_after_pricing) * 1000, 2)))
    server_timing = ", ".join(f"{n};dur={d}" for n, d in steps)
    logger.info("[search] heavy fallback total: %.2f ms (results=%s)", (t_done - t_start) * 1000, len(result))
    return result, "heavy", server_timing
