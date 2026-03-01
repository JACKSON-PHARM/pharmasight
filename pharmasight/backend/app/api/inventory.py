"""
Inventory API routes
"""
from datetime import date, timedelta, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from uuid import UUID
from decimal import Decimal

from app.dependencies import get_tenant_db, get_current_user
from app.models import Item, Branch, InventoryLedger
from app.schemas.inventory import StockBalance, StockAvailability, BatchStock
from app.services.inventory_service import InventoryService, _unit_for_display
from app.services.item_units_helper import get_stock_display_unit
from app.services.canonical_pricing import CanonicalPricingService
from app.services.pricing_service import PricingService

router = APIRouter()


@router.get("/stock/{item_id}/{branch_id}", response_model=dict)
def get_current_stock(
    item_id: UUID,
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get current stock balance for an item.
    Numeric stock is ALWAYS retail/base quantity.
    retail_unit is the correct label for the numeric value.
    """
    stock = InventoryService.get_current_stock(db, item_id, branch_id)
    item = db.query(Item).filter(Item.id == item_id).first()
    retail_unit = _unit_for_display(get_stock_display_unit(item), "piece") if item else "piece"
    stock_display = InventoryService.format_quantity_display(float(stock), item) if item else str(int(stock))
    return {
        "item_id": item_id,
        "branch_id": branch_id,
        "stock": stock,
        "base_quantity": float(stock),
        "retail_unit": retail_unit,
        "stock_display": stock_display,
        "unit": "base_units"
    }


@router.get("/availability/{item_id}/{branch_id}", response_model=StockAvailability)
def get_stock_availability(
    item_id: UUID,
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get stock availability with unit breakdown and batch breakdown"""
    availability = InventoryService.get_stock_availability(db, item_id, branch_id)
    if not availability:
        raise HTTPException(status_code=404, detail="Item not found")
    return availability


@router.get("/batches/{item_id}/{branch_id}", response_model=List[dict])
def get_stock_by_batch(
    item_id: UUID,
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get stock breakdown by batch (FEFO order)"""
    batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
    return batches


@router.post("/allocate-fefo", response_model=List[dict])
def allocate_stock_fefo(
    item_id: UUID,
    branch_id: UUID,
    quantity: float,
    unit_name: str,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Allocate stock using FEFO"""
    try:
        # Convert to base units
        quantity_base = InventoryService.convert_to_base_units(
            db, item_id, quantity, unit_name
        )
        
        # Allocate
        allocations = InventoryService.allocate_stock_fefo(
            db, item_id, branch_id, quantity_base, unit_name
        )
        return allocations
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/check-availability", response_model=dict)
def check_stock_availability(
    item_id: UUID,
    branch_id: UUID,
    quantity: float,
    unit_name: str,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Check if stock is available"""
    try:
        is_available, available, required = InventoryService.check_stock_availability(
            db, item_id, branch_id, quantity, unit_name
        )
        return {
            "is_available": is_available,
            "available_stock": available,
            "required": required,
            "shortage": max(0, required - available) if not is_available else 0
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/branch/{branch_id}/all", response_model=List[dict])
def get_all_stock(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get stock for all items in a branch. OPTIMIZED: only loads items that have stock > 0 (no 10k item load)."""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # 1) Get item_ids with stock > 0 in ONE query (avoids loading all company items)
    stock_aggregates = (
        db.query(
            InventoryLedger.item_id,
            func.sum(InventoryLedger.quantity_delta).label("total_stock"),
        )
        .filter(
            InventoryLedger.branch_id == branch_id,
        )
        .group_by(InventoryLedger.item_id)
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
        .all()
    )
    if not stock_aggregates:
        return []

    stock_map = {row.item_id: int(row.total_stock or 0) for row in stock_aggregates}
    item_ids = list(stock_map.keys())

    # 2) Load only items that have stock. Numeric stock is ALWAYS retail/base. Use retail_unit for labeling.
    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    stock_list = []
    for item in items:
        stock_val = stock_map.get(item.id, 0)
        stock_list.append({
            "item_id": item.id,
            "item_name": item.name,
            "base_unit": item.base_unit or "piece",
            "retail_unit": _unit_for_display(get_stock_display_unit(item), "piece"),
            "stock": stock_val,
            "base_quantity": stock_val,
            "stock_display": InventoryService.format_quantity_display(float(stock_val), item),
        })
    return stock_list


@router.get("/branch/{branch_id}/expiring-count", response_model=dict)
def get_expiring_count(
    branch_id: UUID,
    days: int = Query(365, ge=1, le=3650, description="Number of days ahead to look for expiring items"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get count of distinct batches expiring within the given number of days.
    Uses inventory_ledger; counts (item_id, batch_number, expiry_date) with remaining stock > 0.
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    cutoff = date.today() + timedelta(days=days)

    # Subquery: batches with positive remaining quantity and expiry in range
    batch_agg = (
        db.query(
            InventoryLedger.item_id,
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            func.sum(InventoryLedger.quantity_delta).label("remaining")
        )
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.expiry_date.isnot(None),
            InventoryLedger.expiry_date <= cutoff,
            InventoryLedger.expiry_date >= date.today()
        )
        .group_by(
            InventoryLedger.item_id,
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date
        )
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
        .subquery()
    )
    count = db.query(func.count()).select_from(batch_agg).scalar() or 0
    return {"count": count}


@router.get("/branch/{branch_id}/expiring", response_model=List[dict])
def get_expiring_list(
    branch_id: UUID,
    days: int = Query(365, ge=1, le=3650, description="Number of days ahead to look for expiring items"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get list of batches expiring within the given number of days.
    Returns item_name, batch_number, expiry_date, quantity, base_unit for each batch.
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    cutoff = date.today() + timedelta(days=days)

    batch_agg = (
        db.query(
            InventoryLedger.item_id,
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
            func.sum(InventoryLedger.quantity_delta).label("quantity"),
        )
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.expiry_date.isnot(None),
            InventoryLedger.expiry_date <= cutoff,
            InventoryLedger.expiry_date >= date.today(),
        )
        .group_by(
            InventoryLedger.item_id,
            InventoryLedger.batch_number,
            InventoryLedger.expiry_date,
        )
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
        .order_by(InventoryLedger.expiry_date.asc())
        .all()
    )

    if not batch_agg:
        return []

    item_ids = list({r.item_id for r in batch_agg})
    items = {item.id: item for item in db.query(Item).filter(Item.id.in_(item_ids)).all()}

    result = []
    for r in batch_agg:
        item = items.get(r.item_id)
        qty_retail = float(r.quantity or 0)
        # quantity is in retail/base units (tablets, pieces); display with proper breakdown
        display_str = (
            InventoryService.format_quantity_display(qty_retail, item)
            if item
            else f"{qty_retail}"
        )
        result.append({
            "item_id": str(r.item_id),
            "item_name": item.name if item else "—",
            "quantity_display": display_str,
            "quantity": qty_retail,
            "batch_number": r.batch_number or "",
            "expiry_date": r.expiry_date.isoformat() if r.expiry_date else None,
        })
    return result


@router.get("/branch/{branch_id}/total-value", response_model=dict)
def get_total_stock_value(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get total stock value (KES) for the branch.

    Formula: SUM(available_units * last_unit_cost) per item.
    - available_units = current stock in base/retail units (tablets, pieces, etc.)
    - last_unit_cost = unit_cost from most recent PURCHASE (cost per base unit)
    - Both must use the same unit (ledger stores quantity and cost per base/retail unit).
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    from app.services.canonical_pricing import CanonicalPricingService

    company_item_ids = db.query(Item.id).filter(Item.company_id == branch.company_id)

    # 1) Current stock per item: SUM(quantity_delta) — use subquery to avoid 10k+ bind params
    stock_aggregates = (
        db.query(
            InventoryLedger.item_id,
            func.sum(InventoryLedger.quantity_delta).label("stock"),
        )
        .filter(
            InventoryLedger.item_id.in_(company_item_ids),
            InventoryLedger.branch_id == branch_id,
        )
        .group_by(InventoryLedger.item_id)
        .all()
    )
    stock_map = {row.item_id: float(row.stock or 0) for row in stock_aggregates}
    items_with_stock = [iid for iid, qty in stock_map.items() if qty > 0]
    if not items_with_stock:
        return {"total_value": 0, "currency": "KES"}

    # 2) Cost per RETAIL unit (three-tier: purchase=per retail, opening/default=per wholesale → /pack_size)
    cost_per_retail = CanonicalPricingService.get_cost_per_retail_for_valuation_batch(
        db, items_with_stock, branch_id, branch.company_id
    )

    # 3) Value = quantity_retail * cost_per_retail (e.g. 98 tablets * 0.54 = 52.92)
    total_value = sum(
        stock_map[iid] * float(cost_per_retail.get(iid, 0) or 0)
        for iid in items_with_stock
    )
    return {"total_value": round(total_value, 2), "currency": "KES"}


@router.get("/branch/{branch_id}/items-in-stock-count", response_model=dict)
def get_items_in_stock_count(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get count of distinct items that have stock > 0 at this branch (for dashboard)."""
    from sqlalchemy import func
    from app.models import InventoryLedger

    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    company_item_ids = db.query(Item.id).filter(Item.company_id == branch.company_id)
    subq = (
        db.query(InventoryLedger.item_id)
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.item_id.in_(company_item_ids),
        )
        .group_by(InventoryLedger.item_id)
        .having(func.sum(InventoryLedger.quantity_delta) > 0)
    ).subquery()
    count = db.query(func.count()).select_from(subq).scalar() or 0
    return {"count": count}


@router.get("/branch/{branch_id}/overview", response_model=List[dict])
def get_all_stock_overview(
    branch_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get stock overview for all items with availability details (OPTIMIZED - single query)
    Returns stock with unit breakdown for efficient display
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    items = db.query(Item).filter(Item.company_id == branch.company_id).all()
    
    if not items:
        return []
    
    # Use subquery so we don't pass 10k+ item_ids as bind params
    from sqlalchemy import func
    from app.models import InventoryLedger
    company_item_ids = db.query(Item.id).filter(Item.company_id == branch.company_id)

    stock_aggregates = db.query(
        InventoryLedger.item_id,
        func.sum(InventoryLedger.quantity_delta).label('total_stock')
    ).filter(
        InventoryLedger.item_id.in_(company_item_ids),
        InventoryLedger.branch_id == branch_id
    ).group_by(InventoryLedger.item_id).all()
    
    stock_map = {row.item_id: int(row.total_stock or 0) for row in stock_aggregates}
    
    # Use InventoryService.format_quantity_display — single source of truth for stock breakdown.
    # Numeric stock is ALWAYS retail/base quantity. stock_display shows multi-tier breakdown.
    # Do NOT use item.base_unit as label for numeric stock — use retail_unit.
    result = []
    for item in items:
        stock = stock_map.get(item.id, 0)
        if stock > 0:
            stock_display = InventoryService.format_quantity_display(float(stock), item)
            retail_unit = _unit_for_display(get_stock_display_unit(item), "piece")
            result.append({
                "item_id": item.id,
                "item_name": item.name,
                "base_unit": item.base_unit,
                "retail_unit": retail_unit,
                "stock": stock,
                "base_quantity": stock,
                "stock_display": stock_display
            })
    
    return result


@router.get("/valuation", response_model=dict)
def get_stock_valuation(
    branch_id: UUID = Query(..., description="Branch ID (session branch or selected branch)"),
    as_of_date: Optional[str] = Query(None, description="Date for snapshot (YYYY-MM-DD). Default = today (now)."),
    valuation: str = Query("last_cost", description="Valuation method: last_cost or selling_price"),
    stock_only: bool = Query(True, description="If true, return only items with stock > 0; if false, all company items"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Stock valuation report (PharmaCore-style). Apply filters then fetch.
    - branch_id: which branch (default session branch in UI).
    - as_of_date: snapshot date (default today).
    - valuation: last_cost (unit cost from ledger) or selling_price (cost × markup).
    - stock_only: items with stock only (faster) or all items.
    """
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Parse as_of_date; default to today (use end of day for ledger filter)
    if as_of_date and as_of_date.strip():
        try:
            snap_date = date.fromisoformat(as_of_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid as_of_date; use YYYY-MM-DD.")
    else:
        snap_date = date.today()
    # Ledger filter: include all movements up to end of snap_date
    end_of_day = datetime(snap_date.year, snap_date.month, snap_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    company_id = branch.company_id
    if valuation not in ("last_cost", "selling_price"):
        valuation = "last_cost"

    # 1) Stock aggregates up to as_of_date (single query)
    q = (
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
    )
    if stock_only:
        q = q.having(func.sum(InventoryLedger.quantity_delta) > 0)
    rows = q.all()
    stock_map = {r.item_id: float(r.total_stock or 0) for r in rows}
    item_ids_with_stock = [r.item_id for r in rows if (r.total_stock or 0) > 0]

    if stock_only and not item_ids_with_stock:
        return {
            "branch_id": str(branch_id),
            "branch_name": branch.name or "",
            "as_of_date": snap_date.isoformat(),
            "valuation": valuation,
            "stock_only": stock_only,
            "rows": [],
            "total_value": 0.0,
            "total_items": 0,
        }

    if stock_only:
        item_ids = item_ids_with_stock
    else:
        # All company items: get item_ids from Item table
        item_ids = [r[0] for r in db.query(Item.id).filter(Item.company_id == company_id).all()]
        # Ensure stock_map has 0 for items not in ledger
        for iid in item_ids:
            if iid not in stock_map:
                stock_map[iid] = 0.0

    if not item_ids:
        return {
            "branch_id": str(branch_id),
            "branch_name": branch.name or "",
            "as_of_date": snap_date.isoformat(),
            "valuation": valuation,
            "stock_only": stock_only,
            "rows": [],
            "total_value": 0.0,
            "total_items": 0,
        }

    # 2) Load items (only those we need)
    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    items_by_id = {item.id: item for item in items}

    # 3) Cost per RETAIL unit (same as dashboard total-value) so totals match
    cost_per_retail = CanonicalPricingService.get_cost_per_retail_for_valuation_batch(
        db, item_ids, branch_id, company_id
    )
    if not cost_per_retail:
        cost_per_retail = {}

    # 4) Build rows with value (stock_qty is in retail/base units)
    total_value = 0.0
    result_rows = []
    for item in items:
        stock_qty = stock_map.get(item.id, 0.0)
        if stock_only and stock_qty <= 0:
            continue
        cost = float(cost_per_retail.get(item.id) or 0)
        if valuation == "selling_price":
            markup = PricingService.get_markup_percent(db, item.id, company_id)
            price = cost * (1.0 + float(markup or 0) / 100.0)
        else:
            price = cost
        value = stock_qty * price
        total_value += value
        # Build stock_display from item + qty (avoid N+1 get_stock_display)
        if stock_qty > 0:
            wu = _unit_for_display(getattr(item, "wholesale_unit", None) or item.base_unit, "piece")
            ru = _unit_for_display(getattr(item, "retail_unit", None), "piece")
            su = _unit_for_display(getattr(item, "supplier_unit", None), "piece")
            pack = max(1, int(getattr(item, "pack_size", None) or 1))
            wups = max(0.0001, float(getattr(item, "wholesale_units_per_supplier", None) or 1))
            u_per_supp = pack * wups
            supp_whole = int(stock_qty // u_per_supp) if u_per_supp >= 1 else 0
            rem = stock_qty - (supp_whole * u_per_supp)
            wholesale_whole = int(rem // pack) if pack >= 1 else 0
            retail_rem = int(rem % pack) if pack >= 1 else int(stock_qty)
            parts = []
            if supp_whole > 0:
                parts.append(f"{supp_whole} {su}")
            if wholesale_whole > 0:
                parts.append(f"{wholesale_whole} {wu}")
            if retail_rem > 0 or not parts:
                parts.append(f"{retail_rem} {ru}")
            stock_display = " + ".join(parts) if parts else "0"
        else:
            stock_display = "0"
        result_rows.append({
            "item_id": str(item.id),
            "item_name": item.name or "—",
            "base_unit": (item.base_unit or "piece").strip() or "piece",
            "stock": round(stock_qty, 4),
            "stock_display": stock_display,
            "unit_cost": round(cost, 4),
            "unit_price": round(price, 4),
            "value": round(value, 2),
        })

    return {
        "branch_id": str(branch_id),
        "branch_name": branch.name or "",
        "as_of_date": snap_date.isoformat(),
        "valuation": valuation,
        "stock_only": stock_only,
        "rows": result_rows,
        "total_value": round(total_value, 2),
        "total_items": len(result_rows),
    }

