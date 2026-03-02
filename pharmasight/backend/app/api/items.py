"""
Items API routes.

All item endpoints use get_tenant_db: session is the logged-in context (tenant DB when
X-Tenant-Subdomain is set, else default DB). Same company/DB as rest of app.
"""
import logging
import time
from datetime import datetime, timezone, timedelta, date
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, or_, and_, desc, text
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from app.dependencies import get_tenant_db, get_current_user, _user_has_permission
from decimal import Decimal
from app.models import (
    Item, ItemPricing, CompanyPricingDefault,
    InventoryLedger, InventoryBalance, ItemBranchPurchaseSnapshot, ItemBranchSearchSnapshot,
    ItemBranchSnapshot,
    SupplierInvoice, SupplierInvoiceItem, Supplier,
    PurchaseOrder, PurchaseOrderItem, Branch,
    UserRole, UserBranchRole, ItemMovement,
)
from app.models.settings import CompanySetting
from app.models.permission import Permission, RolePermission
from app.models.sale import SalesInvoice, SalesInvoiceItem
from app.schemas.item import (
    ItemCreate, ItemResponse, ItemUpdate,
    ItemUnitCreate, ItemUnitResponse,
    ItemPricingCreate, ItemPricingResponse,
    CompanyPricingDefaultCreate, CompanyPricingDefaultResponse,
    ItemsBulkCreate, ItemOverviewResponse,
    AdjustStockRequest, AdjustStockResponse,
    CostAdjustmentRequest, BatchQuantityCorrectionRequest, BatchMetadataCorrectionRequest,
    CorrectionResponse, LedgerBatchEntry, LedgerBatchesResponse,
)
from app.services.pricing_service import PricingService
from app.services.items_service import create_item as svc_create_item, DuplicateItemNameError
from app.services.canonical_pricing import CanonicalPricingService
from app.services.inventory_service import InventoryService, _unit_for_display
from app.services.item_units_helper import get_stock_display_unit
from app.services.excel_import_service import ExcelImportService
from app.services.snapshot_service import SnapshotService
from app.services.order_book_service import OrderBookService
from app.services.snapshot_refresh_service import SnapshotRefreshService
from app.services.item_search_service import ItemSearchService
from app.utils.vat import vat_rate_to_percent
from app.schemas.reports import ItemBatchesResponse
from app.services.item_movement_report_service import get_item_batches
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

# Roles allowed to perform manual stock adjustment (add/reduce)
ADJUST_STOCK_ALLOWED_ROLES = {"admin", "pharmacist", "auditor", "super admin"}

# Company setting key for POS snapshot search (default False = use heavy search)
POS_SNAPSHOT_SETTING_KEY = "pos_snapshot_enabled"


def _is_pos_snapshot_enabled(db: Session, company_id: UUID) -> bool:
    """True if company has pos_snapshot_enabled = true. Default False."""
    row = db.query(CompanySetting).filter(
        CompanySetting.company_id == company_id,
        CompanySetting.setting_key == POS_SNAPSHOT_SETTING_KEY,
    ).first()
    if not row or not row.setting_value:
        return False
    return str(row.setting_value).strip().lower() in ("true", "1", "yes")


def _log_snapshot_validation(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    snapshot_results: List[Dict],
    limit: int,
    include_pricing: bool,
    context: Optional[str],
) -> None:
    """
    Validation mode: compare snapshot result values vs heavy-path computed values.
    Log mismatches only; do not return both to client.
    """
    if not snapshot_results:
        return
    item_ids = [UUID(r["id"]) for r in snapshot_results]
    # Get heavy-path values: stock from inventory_balances, cost from snapshot + fallback, sale from pricing
    stock_rows = (
        db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
        .filter(
            InventoryBalance.item_id.in_(item_ids),
            InventoryBalance.company_id == company_id,
            InventoryBalance.branch_id == branch_id,
        )
        .all()
    )
    heavy_stock = {r.item_id: int(float(r.current_stock or 0)) for r in stock_rows}
    cost_rows = (
        db.query(ItemBranchPurchaseSnapshot.item_id, ItemBranchPurchaseSnapshot.last_purchase_price)
        .filter(
            ItemBranchPurchaseSnapshot.item_id.in_(item_ids),
            ItemBranchPurchaseSnapshot.company_id == company_id,
            ItemBranchPurchaseSnapshot.branch_id == branch_id,
        )
        .all()
    )
    heavy_cost = {r.item_id: float(r.last_purchase_price or 0) for r in cost_rows}
    default_cost_rows = (
        db.query(Item.id, Item.default_cost_per_base)
        .filter(Item.id.in_(item_ids), Item.company_id == company_id)
        .all()
    )
    for r in default_cost_rows:
        if r.id not in heavy_cost or heavy_cost[r.id] == 0:
            heavy_cost[r.id] = float(r.default_cost_per_base or 0)
    for r in snapshot_results:
        iid = UUID(r["id"])
        snap_stock = r.get("current_stock")
        heavy_s = heavy_stock.get(iid, 0)
        if snap_stock != heavy_s:
            logger.info(
                "[search] validate_snapshot mismatch item_id=%s current_stock snapshot=%s heavy=%s",
                iid, snap_stock, heavy_s,
            )
        snap_price = r.get("price") or r.get("purchase_price")
        heavy_c = heavy_cost.get(iid, 0)
        if snap_price is not None and heavy_c is not None and abs(float(snap_price) - heavy_c) > 0.001:
            logger.info(
                "[search] validate_snapshot mismatch item_id=%s cost snapshot=%s heavy=%s",
                iid, snap_price, heavy_c,
            )


def _get_user_role(user_id: UUID, branch_id: UUID, db: Session) -> Optional[str]:
    """Get user's role name for a branch (lowercase)."""
    role = db.query(UserRole.role_name).join(
        UserBranchRole, UserRole.id == UserBranchRole.role_id
    ).filter(
        and_(
            UserBranchRole.user_id == user_id,
            UserBranchRole.branch_id == branch_id
        )
    ).first()
    return (role[0].lower() if role and role[0] else None)


def _user_has_correction_permission(db: Session, user_id: UUID, branch_id: UUID, permission_name: str) -> bool:
    """True if user has the given permission for this branch (via role)."""
    perm = db.query(Permission).filter(Permission.name == permission_name).first()
    if not perm:
        return False
    ubr = (
        db.query(UserBranchRole)
        .join(UserRole, UserBranchRole.role_id == UserRole.id)
        .filter(UserBranchRole.user_id == user_id, UserBranchRole.branch_id == branch_id)
        .first()
    )
    if not ubr:
        return False
    rp = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == ubr.role_id,
            RolePermission.permission_id == perm.id,
            RolePermission.branch_id.is_(None),
        )
        .first()
    )
    return rp is not None


def _display_units_from_item(item: Item) -> List[ItemUnitResponse]:
    """
    Build 3-tier unit list from items table columns only (no item_units dependency).
    Fetches names from: wholesale_unit, retail_unit, supplier_unit. Uses pack_size for
    wholesale→retail (1 retail = 1/pack_size wholesale) and wholesale_units_per_supplier
    for wholesale→supplier. Always reveals all available tiers when column values are set.
    """
    wholesale_name = (item.wholesale_unit or item.base_unit or "piece").strip() or "piece"
    retail_name = (item.retail_unit or "").strip()
    supplier_name = (item.supplier_unit or "").strip()
    pack = max(1, int(item.pack_size or 1))
    wups = max(0.0001, float(item.wholesale_units_per_supplier or 1))
    now = datetime.now(timezone.utc)
    units: List[ItemUnitResponse] = []

    # 1) Wholesale (base) — always first, multiplier 1; name from wholesale_unit column
    units.append(
        ItemUnitResponse(
            id=uuid4(),
            item_id=item.id,
            unit_name=wholesale_name,
            multiplier_to_base=1.0,
            is_default=True,
            created_at=now,
        )
    )

    # 2) Retail — whenever retail_unit column is set; conversion 1 retail = 1/pack_size wholesale
    # Skip only if same name as wholesale and pack_size==1 to avoid duplicate option
    if retail_name:
        is_same_as_wholesale = retail_name.lower() == wholesale_name.lower()
        if not (is_same_as_wholesale and pack == 1):
            units.append(
                ItemUnitResponse(
                    id=uuid4(),
                    item_id=item.id,
                    unit_name=item.retail_unit.strip(),
                    multiplier_to_base=1.0 / pack,
                    is_default=False,
                    created_at=now,
                )
            )

    # 3) Supplier — whenever supplier_unit column is set and different from wholesale
    if supplier_name and supplier_name.lower() != wholesale_name.lower():
        units.append(
            ItemUnitResponse(
                id=uuid4(),
                item_id=item.id,
                unit_name=item.supplier_unit.strip(),
                multiplier_to_base=wups,
                is_default=False,
                created_at=now,
            )
        )
    return units


def generate_sku(company_id: UUID, db: Session) -> str:
    """Generate unique SKU for a company (format: A00001, A00002, etc.)"""
    import re
    last_sku = db.query(Item.sku).filter(
        Item.company_id == company_id,
        Item.sku.isnot(None),
        Item.sku != ''
    ).order_by(Item.sku.desc()).limit(100).all()
    max_number = 0
    for sku_row in last_sku:
        if sku_row[0]:
            match = re.match(r'^([A-Z]{1,3})(\d+)$', sku_row[0].upper())
            if match:
                try:
                    max_number = max(max_number, int(match.group(2)))
                except ValueError:
                    pass
    return f"A{(max_number + 1):05d}"


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
def create_item(
    item: ItemCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Create a new item with 3-tier units. SKU auto-generated if not provided. Rejects duplicate names (same company)."""
    try:
        db_item = svc_create_item(db, item)
    except DuplicateItemNameError as e:
        # Return similar items so the user can see existing items with same/similar names
        name_pattern = f"%{(e.name or '').strip()}%"
        similar = (
            db.query(Item.id, Item.name, Item.sku)
            .filter(
                Item.company_id == e.company_id,
                Item.name.ilike(name_pattern),
            )
            .order_by(func.lower(Item.name))
            .limit(10)
            .all()
        )
        similar_items = [
            {"id": str(r.id), "name": r.name, "sku": r.sku or ""}
            for r in similar
        ]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(e),
                "similar_items": similar_items,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(db_item)
    return db_item


class StockBatchRequest(BaseModel):
    """Request body for stock-batch endpoint."""
    item_ids: List[UUID] = Field(..., min_length=1, max_length=500, description="Item IDs to fetch stock for")
    branch_id: UUID = Field(..., description="Branch ID for stock context")
    company_id: UUID = Field(..., description="Company ID")


@router.post("/stock-batch")
def stock_batch(
    body: StockBatchRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Batch fetch stock for multiple items. Uses inventory_balances (snapshot) for fast lookup.
    Returns stocks[item_id] = {base_quantity, retail_unit, stock_display} for each item.
    Numeric stock is ALWAYS retail/base quantity. stock_display shows multi-tier breakdown for UX.
    Do NOT use item.base_unit as label for numeric stock.
    """
    if not body.item_ids:
        return {"stocks": {}}
    # Fetch stock from inventory_balances (snapshot)
    stock_rows = (
        db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
        .filter(
            InventoryBalance.item_id.in_(body.item_ids),
            InventoryBalance.company_id == body.company_id,
            InventoryBalance.branch_id == body.branch_id
        )
        .all()
    )
    stock_map = {row.item_id: int(float(row.current_stock) or 0) for row in stock_rows}
    # Fetch items for stock_display (3-tier unit formatting)
    items_full = db.query(Item).filter(
        Item.id.in_(body.item_ids),
        Item.company_id == body.company_id
    ).all()
    items_map = {item.id: item for item in items_full}
    result = {}
    for iid in body.item_ids:
        qty = float(stock_map.get(iid, 0) or 0)
        item_obj = items_map.get(iid)
        stock_display = InventoryService.format_quantity_display(qty, item_obj) if item_obj else str(int(qty))
        retail_unit = _unit_for_display(get_stock_display_unit(item_obj), "piece") if item_obj else "piece"
        result[str(iid)] = {
            "base_quantity": qty,
            "current_stock": qty,  # backward compat
            "retail_unit": retail_unit,
            "stock_display": stock_display,
        }
    return {"stocks": result}


@router.get("/search")
def search_items(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID for pricing and stock (optional)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    include_pricing: bool = Query(False, description="Include pricing info (slower)"),
    fast: bool = Query(False, description="Deprecated; ignored. Response shape is always canonical."),
    context: Optional[str] = Query(None, description="Context: 'purchase_order' for PO-specific fields"),
    validate_snapshot: bool = Query(False, description="Log snapshot vs heavy search values (debug); no client change"),
    current_user_and_db: tuple = Depends(get_current_user),
):
    """
    Item search: single service path. Snapshot (item_branch_snapshot) is primary when branch_id is set;
    heavy path is fallback only on exception or missing branch_id. Same response shape for both.
    Returns: id, name, base_unit, prices, sku, stock, VAT, margin_percent, next_expiry_date.
    Uses db from get_current_user to avoid a second tenant DB connection (get_tenant_db).
    """
    _user, db = current_user_and_db
    result, path, server_timing = ItemSearchService.search(
        db, q, company_id, branch_id, limit, include_pricing, context
    )
    if validate_snapshot and path == "item_branch_snapshot" and result and branch_id:
        _log_snapshot_validation(db, company_id, branch_id, result, limit, include_pricing, context)
    # Full request time (from middleware, includes auth + get_tenant_db + search) for Network tab
    t_start = getattr(request.state, "_req_start_time", None)
    if t_start is not None:
        t_total_ms = round((time.perf_counter() - t_start) * 1000, 2)
        timing_header = f"total;dur={t_total_ms}, {server_timing}"
    else:
        timing_header = server_timing
    return JSONResponse(
        content=result,
        headers={"Server-Timing": timing_header, "X-Search-Path": path},
    )


def _item_to_response_dict(item: Item, default_cost: float = 0.0) -> dict:
    """
    Build a dict suitable for ItemResponse from an Item using only scalar columns.
    Never accesses item.units (avoids querying item_units table which may not exist).
    """
    return {
        "id": item.id,
        "company_id": item.company_id,
        "name": item.name,
        "description": item.description,
        "sku": item.sku,
        "barcode": item.barcode,
        "category": item.category,
        "product_category": getattr(item, "product_category", None),
        "pricing_tier": getattr(item, "pricing_tier", None),
        "base_unit": _unit_for_display(item.base_unit, "piece"),
        "vat_category": getattr(item, "vat_category", None) or "ZERO_RATED",
        "vat_rate": vat_rate_to_percent(item.vat_rate),
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "supplier_unit": _unit_for_display(item.supplier_unit, "piece"),
        "wholesale_unit": _unit_for_display(item.wholesale_unit or item.base_unit, "piece"),
        "retail_unit": _unit_for_display(get_stock_display_unit(item), "piece"),
        "pack_size": int(item.pack_size) if item.pack_size is not None else 1,
        "wholesale_units_per_supplier": float(item.wholesale_units_per_supplier) if item.wholesale_units_per_supplier is not None else 1.0,
        "can_break_bulk": item.can_break_bulk,
        "track_expiry": getattr(item, "track_expiry", False),
        "is_controlled": getattr(item, "is_controlled", False),
        "is_cold_chain": getattr(item, "is_cold_chain", False),
        "default_cost_per_base": float(item.default_cost_per_base) if item.default_cost_per_base is not None else None,
        "default_supplier_id": item.default_supplier_id,
        "default_cost": default_cost,
        "units": [],  # Set below from _display_units_from_item
    }


@router.get("/{item_id}/batches", response_model=ItemBatchesResponse)
def get_item_batches_endpoint(
    item_id: UUID,
    branch_id: UUID = Query(..., description="Branch ID (session branch for report dropdown)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    List distinct batches for an item at a branch (tenant- and branch-scoped).
    Used to populate the batch dropdown in Batch Movement Report.
    Requires reports.view and branch access.
    """
    user, _ = current_user_and_db
    if not _user_has_permission(db, user.id, "reports.view"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission reports.view required.",
        )
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch or branch.company_id != item.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found or does not belong to item company.")
    has_branch_access = db.query(UserBranchRole).filter(
        UserBranchRole.user_id == user.id,
        UserBranchRole.branch_id == branch_id,
    ).first() is not None
    if not has_branch_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this branch.",
        )
    batches = get_item_batches(db, company_id=item.company_id, branch_id=branch_id, item_id=item_id)
    return ItemBatchesResponse(batches=batches)


@router.get("/{item_id}", response_model=ItemResponse)
def get_item(
    item_id: UUID,
    branch_id: Optional[UUID] = Query(None, description="Branch ID for cost from ledger (optional)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get item by ID. Uses same DB/session as request (tenant when X-Tenant-Subdomain set).
    Cost from inventory_ledger; fallback item.default_cost_per_base. Units list is built from
    the item row (3-tier: base, retail, supplier) so the unit dropdown always shows all tiers.
    Does not use the item_units table (works when that table is missing).
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    default_cost = float(
        CanonicalPricingService.get_best_available_cost(db, item.id, branch_id, item.company_id)
    ) if branch_id else 0.0
    data = _item_to_response_dict(item, default_cost=default_cost)
    data["units"] = _display_units_from_item(item)
    data["has_transactions"] = item_id in ExcelImportService._get_items_with_real_transactions(db, item.company_id, [item_id])
    if branch_id:
        qty = float(InventoryService.get_current_stock(db, item.id, branch_id))
        data["stock_display"] = InventoryService.get_stock_display(db, item.id, branch_id)
        data["base_quantity"] = qty
        data["current_stock"] = qty
        data["retail_unit"] = _unit_for_display(get_stock_display_unit(item), "piece")
    resp = ItemResponse.model_validate(data)
    return resp


@router.get("/{item_id}/activity", response_model=dict)
def get_item_activity(
    item_id: UUID,
    branch_id: UUID = Query(..., description="Session branch ID (for stock and cost context)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Read-only item activity for transaction documents (sales, purchases, quotations).
    Returns: order & supply details, stock (session + other branches), expiry & batch.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    company_id = item.company_id

    # ---- Order & supply ----
    # Last purchase order date (any branch for this company)
    last_po = (
        db.query(func.max(PurchaseOrder.order_date).label("dt"))
        .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .filter(PurchaseOrderItem.item_id == item_id, PurchaseOrder.company_id == company_id)
        .scalar()
    )
    last_order_date = last_po.isoformat() if last_po else None

    # Last received: max created_at from ledger PURCHASE (positive)
    last_rec = (
        db.query(func.max(InventoryLedger.created_at).label("dt"))
        .filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.company_id == company_id,
            InventoryLedger.transaction_type == "PURCHASE",
            InventoryLedger.quantity_delta > 0,
        )
        .scalar()
    )
    last_received = last_rec.isoformat()[:10] if last_rec else None

    # Last sold: max created_at from ledger SALE
    last_sale = (
        db.query(func.max(InventoryLedger.created_at).label("dt"))
        .filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.company_id == company_id,
            InventoryLedger.transaction_type == "SALE",
        )
        .scalar()
    )
    last_sold = last_sale.isoformat()[:10] if last_sale else None

    # Last supplier and last unit cost (from last supplier invoice containing this item)
    last_inv = (
        db.query(
            Supplier.name.label("supplier_name"),
            SupplierInvoiceItem.unit_cost_exclusive,
        )
        .join(SupplierInvoice, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id)
        .join(Supplier, Supplier.id == SupplierInvoice.supplier_id)
        .filter(SupplierInvoiceItem.item_id == item_id, SupplierInvoice.company_id == company_id)
        .order_by(desc(SupplierInvoice.created_at))
        .first()
    )
    last_supplier_name = last_inv.supplier_name if last_inv else None
    last_unit_cost_from_inv = float(last_inv.unit_cost_exclusive) if last_inv and last_inv.unit_cost_exclusive is not None else None
    # Prefer cost per base from ledger for display consistency
    last_cost_per_base = CanonicalPricingService.get_last_purchase_cost(db, item_id, branch_id, company_id)
    last_unit_cost = float(last_cost_per_base) if last_cost_per_base is not None else last_unit_cost_from_inv

    # ---- Stock: session branch + other branches ----
    session_stock = InventoryService.get_current_stock(db, item_id, branch_id)
    branches = db.query(Branch).filter(Branch.company_id == company_id, Branch.is_active == True).all()
    session_branch = next((b for b in branches if b.id == branch_id), None)
    other_branches = []
    for b in branches:
        if b.id == branch_id:
            continue
        st = InventoryService.get_current_stock(db, item_id, b.id)
        other_branches.append({
            "branch_id": str(b.id),
            "branch_name": b.name,
            "code": b.code or "",
            "stock": st,
        })
    stock_session = {
        "branch_id": str(branch_id),
        "branch_name": session_branch.name if session_branch else "",
        "code": session_branch.code if session_branch else "",
        "stock": session_stock,
    }

    # ---- Expiry & batch (session branch only) ----
    batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
    expiry_batch = {
        "batches": [
            {
                "batch_number": b.get("batch_number"),
                "expiry_date": b["expiry_date"].isoformat() if b.get("expiry_date") else None,
                "quantity": b["quantity"],
                "unit_cost": b["unit_cost"],
            }
            for b in batches
        ],
    }

    # Item basics (minimal for header)
    units = _display_units_from_item(item)
    default_cost = float(
        CanonicalPricingService.get_best_available_cost(db, item.id, branch_id, company_id)
    ) if branch_id else 0.0
    item_data = _item_to_response_dict(item, default_cost=default_cost)
    item_data["units"] = [{"unit_name": u.unit_name, "multiplier_to_base": u.multiplier_to_base} for u in units]

    return {
        "item": {
            "id": str(item.id),
            "name": item.name,
            "sku": item.sku or "",
            "barcode": item.barcode or "",
            "base_unit": item.base_unit or "piece",
            "units": item_data["units"],
        },
        "order_supply": {
            "last_order_date": last_order_date,
            "last_received": last_received,
            "last_sold": last_sold,
            "last_supplier_name": last_supplier_name,
            "last_unit_cost": last_unit_cost,
        },
        "stock": {
            "session_branch": stock_session,
            "other_branches": other_branches,
        },
        "expiry_batch": expiry_batch,
    }


@router.get("/{item_id}/pricing/3tier", response_model=dict)
def get_item_3tier_pricing(item_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get 3-tier pricing for an item"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    tier_pricing = PricingService.get_3tier_pricing(db, item_id)
    if not tier_pricing:
        return {"message": "No 3-tier pricing configured for this item"}
    
    return tier_pricing


@router.get("/{item_id}/pricing/tier/{tier}", response_model=dict)
def get_item_tier_price(
    item_id: UUID,
    tier: str,
    unit_name: Optional[str] = Query(None, description="Optional unit name to convert price to"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get price for a specific tier (supplier, wholesale, or retail)"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if tier.lower() not in ['supplier', 'wholesale', 'retail']:
        raise HTTPException(status_code=400, detail="Tier must be 'supplier', 'wholesale', or 'retail'")
    
    price_data = PricingService.get_price_for_tier(db, item_id, tier, unit_name)
    if not price_data:
        raise HTTPException(status_code=404, detail=f"No {tier} price configured for this item")
    
    return price_data


@router.get("/company/{company_id}/count", response_model=dict)
def get_items_count(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get count of items for a company (fast, no data loading)"""
    count = db.query(Item).filter(Item.company_id == company_id).count()
    return {"count": count}


# Safe cap to prevent runaway payloads (performance protection; pagination is structural phase 2)
MAX_ITEMS_OVERVIEW = 2000


@router.get("/company/{company_id}/overview")
def get_items_overview(
    company_id: UUID,
    branch_id: Optional[UUID] = Query(None, description="Branch ID for stock calculation (optional)"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get items with overview data (stock, supplier, cost) - OPTIMIZED
    
    Single query endpoint to avoid N+1 problems.
    Computes stock from inventory_ledger aggregation.
    Gets last supplier and cost from purchase transactions.
    Returns at most MAX_ITEMS_OVERVIEW items; response header X-Items-Truncated is set when capped.
    """
    # Base query for items (units are from item columns; no item_units table)
    items_query = db.query(Item).filter(Item.company_id == company_id)
    total_count = items_query.count()
    items = items_query.limit(MAX_ITEMS_OVERVIEW).all()
    truncated = total_count > MAX_ITEMS_OVERVIEW

    if not items:
        return JSONResponse(content=[], headers={"X-Items-Truncated": "false"})

    item_ids = [item.id for item in items]
    # Subquery limited to the items we are returning (capped set)
    company_item_ids_subq = db.query(Item.id).filter(Item.id.in_(item_ids))
    
    # Aggregate stock from inventory_ledger (single query; use subquery, not IN(list))
    stock_query = db.query(
        InventoryLedger.item_id,
        func.sum(InventoryLedger.quantity_delta).label('total_stock')
    ).filter(
        InventoryLedger.item_id.in_(company_item_ids_subq),
        InventoryLedger.company_id == company_id
    )
    
    if branch_id:
        stock_query = stock_query.filter(InventoryLedger.branch_id == branch_id)
    
    stock_data = {row.item_id: float(row.total_stock or 0) for row in stock_query.group_by(InventoryLedger.item_id).all()}
    
    # Check which items have real transactions (sales, purchases, or ledger other than OPENING_BALANCE).
    # Items with only OPENING_BALANCE (e.g. from Excel import) remain editable.
    items_with_transactions = ExcelImportService._get_items_with_real_transactions(db, company_id, list(item_ids))
    
    # Get last supplier and cost from purchase invoices (optimized subquery)
    # When branch_id is set: last supplier/cost for this branch only (branch-specific)
    from sqlalchemy import desc
    overview_purchase_filters = [
        SupplierInvoiceItem.item_id.in_(company_item_ids_subq),
        SupplierInvoice.company_id == company_id
    ]
    if branch_id:
        overview_purchase_filters.append(SupplierInvoice.branch_id == branch_id)
    last_purchase_subq = (
        db.query(
            SupplierInvoiceItem.item_id,
            SupplierInvoice.supplier_id,
            SupplierInvoiceItem.unit_cost_exclusive,
            SupplierInvoice.created_at,
            func.row_number().over(
                partition_by=SupplierInvoiceItem.item_id,
                order_by=desc(SupplierInvoice.created_at)
            ).label('rn')
        )
        .join(SupplierInvoice, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id)
        .filter(*overview_purchase_filters)
        .subquery()
    )
    
    last_purchases = (
        db.query(
            last_purchase_subq.c.item_id,
            last_purchase_subq.c.supplier_id,
            last_purchase_subq.c.unit_cost_exclusive
        )
        .filter(last_purchase_subq.c.rn == 1)
        .all()
    )
    
    # Get supplier names
    supplier_ids = {row.supplier_id for row in last_purchases if row.supplier_id}
    suppliers = {s.id: s.name for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()} if supplier_ids else {}
    
    # Build lookup dictionaries (cost from purchase invoices / ledger only)
    last_supplier_map = {}
    last_cost_map = {}
    for row in last_purchases:
        last_supplier_map[row.item_id] = suppliers.get(row.supplier_id)
        last_cost_map[row.item_id] = float(row.unit_cost_exclusive) if row.unit_cost_exclusive else None
    
    # Fallback: default_supplier_id when no purchase history
    ids_without_supplier = [i for i in item_ids if i not in last_supplier_map]
    if ids_without_supplier:
        default_rows = db.query(Item.id, Item.default_supplier_id).filter(
            Item.id.in_(ids_without_supplier),
            Item.default_supplier_id.isnot(None)
        ).all()
        if default_rows:
            default_supplier_ids = {r.default_supplier_id for r in default_rows if r.default_supplier_id}
            default_suppliers = {s.id: s.name for s in db.query(Supplier).filter(Supplier.id.in_(default_supplier_ids)).all()} if default_supplier_ids else {}
            for r in default_rows:
                if r.default_supplier_id:
                    last_supplier_map[r.id] = default_suppliers.get(r.default_supplier_id)
    
    # 3-tier pricing deprecated — cost from ledger only; no tier_pricing from items
    tier_pricing_map = {}
    
    # Build response — default_cost from ledger (last_cost_map), never from items table
    result = []
    for item in items:
        cost_from_ledger = last_cost_map.get(item.id)
        if cost_from_ledger is None and branch_id:
            cost_from_ledger = float(CanonicalPricingService.get_best_available_cost(db, item.id, branch_id, item.company_id))
        default_cost_val = float(cost_from_ledger) if cost_from_ledger is not None else 0.0
        
        # Calculate stock_display using 3-tier units when branch_id is provided
        stock_qty = stock_data.get(item.id, 0.0)
        stock_display_val = None
        if branch_id and stock_qty is not None:
            stock_display_val = InventoryService.format_quantity_display(float(stock_qty), item)
        
        item_dict = {
            'id': item.id,
            'company_id': item.company_id,
            'name': item.name,
            'description': getattr(item, 'description', None),
            'sku': item.sku,
            'barcode': item.barcode,
            'category': item.category,
            'base_unit': item.base_unit,
            'default_cost': default_cost_val,
            'vat_category': getattr(item, 'vat_category', None) or 'ZERO_RATED',
            'vat_rate': vat_rate_to_percent(item.vat_rate),
            'is_active': item.is_active,
            'created_at': item.created_at,
            'updated_at': item.updated_at,
            'units': _display_units_from_item(item),
            'supplier_unit': item.supplier_unit,
            'wholesale_unit': item.wholesale_unit,
            'retail_unit': item.retail_unit,
            'pack_size': item.pack_size,
            'wholesale_units_per_supplier': float(item.wholesale_units_per_supplier) if item.wholesale_units_per_supplier else 1,
            'can_break_bulk': item.can_break_bulk,
            'track_expiry': getattr(item, 'track_expiry', False),
            'is_controlled': getattr(item, 'is_controlled', False),
            'is_cold_chain': getattr(item, 'is_cold_chain', False),
            'base_quantity': stock_qty,
            'current_stock': stock_qty,
            'retail_unit': _unit_for_display(get_stock_display_unit(item), "piece"),
            'stock_display': stock_display_val,
            'last_supplier': last_supplier_map.get(item.id),
            'last_unit_cost': last_cost_map.get(item.id),
            'has_transactions': item.id in items_with_transactions,
            'minimum_stock': None
        }
        # Add 3-tier pricing as additional field (not in schema, but useful)
        overview_item = ItemOverviewResponse(**item_dict)
        # Add 3-tier pricing to response (we'll need to extend the response model or return as dict)
        result.append(overview_item)
    
    # Convert to dict to add 3-tier pricing
    result_dicts = []
    for i, item in enumerate(result):
        item_dict = item.model_dump() if hasattr(item, 'model_dump') else item.dict()
        if items[i].id in tier_pricing_map:
            item_dict['pricing_3tier'] = tier_pricing_map[items[i].id]
        result_dicts.append(item_dict)

    return JSONResponse(
        content=result_dicts,
        headers={"X-Items-Truncated": "true" if truncated else "false"},
    )


@router.get("/company/{company_id}", response_model=List[ItemResponse])
def get_items_by_company(
    company_id: UUID, 
    db: Session = Depends(get_tenant_db),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of items to return"),
    offset: Optional[int] = Query(0, ge=0, description="Number of items to skip"),
    include_units: bool = Query(True, description="Include item units in response")
):
    """
    Get all items for a company
    
    Optimized with eager loading to avoid N+1 queries.
    For large datasets, use pagination with limit/offset.
    Set include_units=false for faster loading when units aren't needed.
    """
    query = db.query(Item).filter(Item.company_id == company_id)
    
    # Apply pagination if limit is provided
    if limit:
        query = query.limit(limit).offset(offset)
    
    items = query.all()
    # Build response from scalar columns only (units from 3-tier columns; no item_units table)
    result = []
    for item in items:
        data = _item_to_response_dict(item, default_cost=0.0)
        data["units"] = _display_units_from_item(item)
        result.append(ItemResponse.model_validate(data))
    return result


@router.post("/{item_id}/adjust-stock", response_model=AdjustStockResponse)
def adjust_stock(
    item_id: UUID,
    body: AdjustStockRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Add or reduce stock for an item (manual adjustment).
    Only users with role ADMIN, Pharmacist, or Auditor can adjust stock.
    Quantity is in the selected unit (one of the item's 3-tier units: e.g. box, tablet, piece).
    Unit cost defaults to last purchase cost if not provided.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    user_role = _get_user_role(body.user_id, body.branch_id, db)
    if not user_role or user_role not in ADJUST_STOCK_ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ADMIN, Pharmacist, or Auditor can adjust stock quantities.",
        )

    # Convert quantity in selected unit to base units
    try:
        base_quantity = InventoryService.convert_to_base_units(
            db, item_id, float(body.quantity), body.unit_name.strip()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if base_quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity in selected unit must result in at least 1 base unit.",
        )

    quantity_delta = base_quantity if body.direction.lower() == "add" else -base_quantity

    # Previous balance (so response can show: previous + delta = new; never overwrite)
    previous_stock = InventoryService.get_current_stock(db, item_id, body.branch_id)

    # For reduce, check current stock
    if quantity_delta < 0:
        if previous_stock + quantity_delta < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reduce by {abs(quantity_delta)} base units: current stock is {previous_stock}.",
            )

    # Unit cost: use provided or last purchase/default
    if body.unit_cost is not None:
        unit_cost = Decimal(str(body.unit_cost))
    else:
        unit_cost = CanonicalPricingService.get_best_available_cost(
            db, item_id, body.branch_id, item.company_id
        )
        if unit_cost is None or unit_cost <= 0:
            unit_cost = Decimal("0")
    # quantity_delta is float from convert_to_base_units; Decimal * float is invalid
    total_cost = unit_cost * Decimal(str(abs(quantity_delta)))

    expiry_date_parsed = None
    if body.expiry_date and body.expiry_date.strip():
        try:
            from datetime import date as date_type
            expiry_date_parsed = date_type.fromisoformat(body.expiry_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expiry_date; use YYYY-MM-DD.")

    # Reject duplicate POST within same request window (e.g. double submit)
    window = datetime.now(timezone.utc) - timedelta(seconds=2)
    recent_same = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == body.branch_id,
            InventoryLedger.reference_type == "MANUAL_ADJUSTMENT",
            InventoryLedger.quantity_delta == quantity_delta,
            InventoryLedger.created_by == body.user_id,
            InventoryLedger.created_at >= window,
        )
        .first()
    )
    if recent_same:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical stock adjustment was just recorded. If this was a duplicate request, ignore.",
        )
    ledger_entry = InventoryLedger(
        company_id=item.company_id,
        branch_id=body.branch_id,
        item_id=item_id,
        transaction_type="ADJUSTMENT",
        reference_type="MANUAL_ADJUSTMENT",
        reference_id=None,
        quantity_delta=quantity_delta,
        unit_cost=unit_cost,
        total_cost=total_cost,
        created_by=body.user_id,
        batch_number=body.batch_number.strip() if body.batch_number and body.batch_number.strip() else None,
        expiry_date=expiry_date_parsed,
        notes=body.notes.strip() if body.notes and body.notes.strip() else None,
    )
    db.add(ledger_entry)
    db.flush()
    SnapshotService.upsert_inventory_balance(db, item.company_id, body.branch_id, item_id, quantity_delta)
    SnapshotRefreshService.schedule_snapshot_refresh(db, item.company_id, body.branch_id, item_id=item_id)
    db.commit()

    new_stock = InventoryService.get_current_stock(db, item_id, body.branch_id)
    new_stock_display = InventoryService.get_stock_display(db, item_id, body.branch_id)
    direction_label = "added" if quantity_delta > 0 else "reduced"
    retail_unit = _unit_for_display(get_stock_display_unit(item), "piece")
    return AdjustStockResponse(
        success=True,
        message=f"Stock {direction_label}: {abs(quantity_delta):.0f} base units. Previous: {previous_stock:.0f} → New: {new_stock:.0f} ({new_stock_display}).",
        item_id=item_id,
        branch_id=body.branch_id,
        quantity_delta=float(quantity_delta),
        previous_stock=previous_stock,
        new_stock=new_stock,
        new_stock_display=new_stock_display,
        base_quantity=new_stock,
        retail_unit=retail_unit,
    )


@router.put("/{item_id}", response_model=ItemResponse)
def update_item(
    item_id: UUID,
    item_update: ItemUpdate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Update item with strict business rules:
    - SKU is immutable (never editable)
    - Base unit and unit conversions are editable ONLY if item has no inventory_ledger records
    - Name, category, pricing, barcode are always editable
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Lock structural fields only when item has real transactions (sales, purchases, or non–opening-balance ledger).
    # Items with only OPENING_BALANCE (e.g. from Excel import) can still be edited.
    has_transactions = item_id in ExcelImportService._get_items_with_real_transactions(db, item.company_id, [item_id])
    
    update_data = item_update.model_dump(exclude_unset=True, exclude={'units'}) if hasattr(item_update, 'model_dump') else item_update.dict(exclude_unset=True, exclude={'units'})
    # Do not persist deprecated price fields — cost from inventory_ledger only
    for key in ("default_cost", "purchase_price_per_supplier_unit", "wholesale_price_per_wholesale_unit", "retail_price_per_retail_unit"):
        update_data.pop(key, None)
    
    # Business Rule 1: SKU is immutable
    if 'sku' in update_data:
        raise HTTPException(
            status_code=400,
            detail="SKU cannot be modified once created. Item code is immutable."
        )
    
    # Business Rule 2: Only conversion rates and break-bulk are locked when item has real transactions.
    # Unit names (wholesale_unit, retail_unit, supplier_unit, base_unit) are for display/convenience and may be changed.
    if has_transactions:
        locked_fields = ['pack_size', 'wholesale_units_per_supplier', 'can_break_bulk']
        attempted_locked = [f for f in locked_fields if f in update_data]
        if attempted_locked:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot modify conversion rates ({', '.join(attempted_locked)}) after item has been used in sales, purchases, or stock movements. "
                       f"Unit names (e.g. packets, bottles, tins) can still be changed."
            )

    # 3-tier validation: breakable => pack_size > 1 (only when we're actually updating those fields)
    if 'can_break_bulk' in update_data or 'pack_size' in update_data:
        cb = update_data.get('can_break_bulk') if 'can_break_bulk' in update_data else getattr(item, 'can_break_bulk', False)
        ps = update_data.get('pack_size') if 'pack_size' in update_data else getattr(item, 'pack_size', 1) or 1
        if cb and (int(ps) if ps is not None else 1) < 2:
            raise HTTPException(status_code=400, detail="Breakable items must have pack_size > 1")
    
    # Apply allowed updates. Units are item characteristics (columns on items table); no separate unit list.
    for field, value in update_data.items():
        setattr(item, field, value)
    
    db.commit()
    db.refresh(item)
    SnapshotRefreshService.schedule_snapshot_refresh_for_item_all_branches(db, item.company_id, item_id)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Soft delete item (set is_active=False)"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.is_active = False
    db.commit()
    return None


@router.post("/bulk", response_model=dict, status_code=status.HTTP_201_CREATED)
def bulk_create_items(
    bulk_data: ItemsBulkCreate,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Bulk create items (for Excel import) - OPTIMIZED with duplicate detection
    
    Features:
    - Checks for duplicates by SKU (if provided) or name+company_id
    - Uses bulk insert for 100x faster performance
    - Skips existing items (resumable imports)
    - Processes up to 1000 items per batch
    """
    if not bulk_data.items:
        raise HTTPException(status_code=400, detail="No items provided")
    
    if len(bulk_data.items) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 items per batch")
    
    created_count = 0
    skipped_count = 0
    errors = []
    
    try:
        # Step 1: Check for duplicates in bulk
        # Build sets of existing SKUs and names for fast lookup
        existing_skus = set()
        existing_names = set()
        
        # Collect all SKUs and names from incoming items
        incoming_skus = []
        incoming_names = []
        for item_data in bulk_data.items:
            item_dict = item_data.model_dump(exclude={"units"}) if hasattr(item_data, 'model_dump') else item_data.dict(exclude={"units"})
            sku = item_dict.get('sku')
            name = item_dict.get('name', '').strip().lower()
            if sku and sku.strip():
                incoming_skus.append(sku.strip())
            if name:
                incoming_names.append(name)
        
        # Query existing items in bulk (much faster than individual queries)
        if incoming_skus:
            existing_items_by_sku = db.query(Item).filter(
                Item.company_id == bulk_data.company_id,
                Item.sku.in_(incoming_skus),
                Item.sku.isnot(None),
                Item.sku != ''
            ).all()
            existing_skus = {item.sku.strip().lower() for item in existing_items_by_sku if item.sku}
        
        if incoming_names:
            existing_items_by_name = db.query(Item).filter(
                Item.company_id == bulk_data.company_id,
                func.lower(Item.name).in_([n.lower() for n in incoming_names])
            ).all()
            existing_names = {item.name.strip().lower() for item in existing_items_by_name}
        
        # Step 2: Filter out duplicates and prepare new items
        new_items = []
        items_to_insert = []
        for idx, item_data in enumerate(bulk_data.items):
            try:
                # Use model_dump() for Pydantic v2, fallback to dict() for v1
                item_dict = item_data.model_dump(exclude={"units"}) if hasattr(item_data, 'model_dump') else item_data.dict(exclude={"units"})
                
                # Ensure company_id matches
                item_dict['company_id'] = bulk_data.company_id
                
                sku = item_dict.get('sku', '').strip() if item_dict.get('sku') else ''
                name = item_dict.get('name', '').strip().lower()
                
                # Check for duplicates
                is_duplicate = False
                if sku and sku.lower() in existing_skus:
                    is_duplicate = True
                elif name in existing_names:
                    is_duplicate = True
                
                if is_duplicate:
                    skipped_count += 1
                    continue
                
                # Track this item as processed to avoid duplicates within the same batch
                if sku:
                    existing_skus.add(sku.lower())
                if name:
                    existing_names.add(name)
                
                # Prepare item for bulk insert
                items_to_insert.append(item_dict)
                new_items.append({
                    'index': idx,
                    'item_data': item_data,
                    'item_dict': item_dict
                })
                
            except Exception as e:
                import traceback
                error_msg = str(e)
                logger.warning(f"Item {idx} validation error: {error_msg}")
                errors.append({
                    'index': idx,
                    'name': item_data.name if hasattr(item_data, 'name') else 'Unknown',
                    'error': f"Validation error: {error_msg}"
                })
        
        # Step 3: Bulk insert items (MUCH faster than individual inserts)
        if items_to_insert:
            # Use bulk_insert_mappings for optimal performance
            db.bulk_insert_mappings(Item, items_to_insert)
            db.flush()  # Get IDs assigned
            
            # Step 4: Get inserted items to create units
            # Query back the inserted items to get their IDs
            inserted_skus = [item.get('sku') for item in items_to_insert if item.get('sku')]
            inserted_names = [item.get('name') for item in items_to_insert]
            
            # Build filter conditions
            filter_conditions = []
            if inserted_skus:
                filter_conditions.append(Item.sku.in_(inserted_skus))
            if inserted_names:
                filter_conditions.append(Item.name.in_(inserted_names))
            
            if filter_conditions:
                inserted_items = db.query(Item).filter(
                    Item.company_id == bulk_data.company_id,
                    or_(*filter_conditions)
                ).order_by(Item.created_at.desc()).limit(len(items_to_insert)).all()
            else:
                inserted_items = []
            
            # Create a mapping: (sku or name) -> item_id
            item_id_map = {}
            for item in inserted_items:
                key = item.sku.strip().lower() if item.sku else item.name.strip().lower()
                item_id_map[key] = item.id
            
            # Step 5: Count created items (units are item columns; no item_units table)
            for new_item in new_items:
                idx = new_item['index']
                item_data = new_item['item_data']
                item_dict = new_item['item_dict']
                
                try:
                    sku = item_dict.get('sku', '').strip() if item_dict.get('sku') else ''
                    name = item_dict.get('name', '').strip().lower()
                    key = sku.lower() if sku else name
                    item_id = item_id_map.get(key)
                    
                    if not item_id:
                        errors.append({
                            'index': idx,
                            'name': item_dict.get('name', 'Unknown'),
                            'error': "Failed to get item ID after insert"
                        })
                        continue
                    
                    created_count += 1
                    
                except Exception as e:
                    errors.append({
                        'index': idx,
                        'name': item_dict.get('name', 'Unknown'),
                        'error': str(e)
                    })
            
            # Units are item characteristics (columns on items table only); no item_units table to insert.
        
        # Commit all at once
        db.commit()
        
        return {
            'created': created_count,
            'skipped': skipped_count,
            'errors': len(errors),
            'total': len(bulk_data.items),
            'error_details': errors[:20]  # Return first 20 errors
        }
        
    except Exception as e:
        db.rollback()
        import traceback
        raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}\n{traceback.format_exc()}")


@router.get("/{item_id}/recommended-price", response_model=dict)
def get_recommended_price(
    item_id: UUID,
    branch_id: UUID,
    company_id: UUID,
    unit_name: str,
    tier: Optional[str] = Query("retail", description="Pricing tier: retail, wholesale, or supplier"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Get recommended selling price for item (tier: retail / wholesale / supplier)."""
    try:
        tier_clean = (tier or "retail").lower()
        if tier_clean not in ("retail", "wholesale", "supplier"):
            tier_clean = "retail"
        price_info = PricingService.calculate_recommended_price(
            db, item_id, branch_id, company_id, unit_name, tier=tier_clean
        )
        if not price_info and tier_clean == "supplier":
            price_info = PricingService.calculate_recommended_price(
                db, item_id, branch_id, company_id, unit_name, tier="wholesale"
            )
        if not price_info:
            raise HTTPException(status_code=404, detail="Item cost not available")
        return price_info
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{item_id}/has-transactions")
def has_transactions(
    item_id: UUID,
    branch_id: UUID = Query(..., description="Branch ID to check transactions in"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Check if item has any transactions (sales or purchases) in the specified branch
    
    Returns True if item has transactions, False otherwise.
    Items with transactions cannot have pack size/breaking bulk edited during stock take.
    """
    from app.models.sale import SalesInvoiceItem
    from app.models.purchase import SupplierInvoiceItem
    
    # Check for sales transactions
    sales_count = db.query(func.count(SalesInvoiceItem.id)).join(
        SalesInvoice, SalesInvoiceItem.sales_invoice_id == SalesInvoice.id
    ).filter(
        and_(
            SalesInvoiceItem.item_id == item_id,
            SalesInvoice.branch_id == branch_id
        )
    ).scalar() or 0
    
    # Check for purchase transactions
    purchase_count = db.query(func.count(SupplierInvoiceItem.id)).join(
        SupplierInvoice, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id
    ).filter(
        and_(
            SupplierInvoiceItem.item_id == item_id,
            SupplierInvoice.branch_id == branch_id
        )
    ).scalar() or 0
    
    # Check for inventory movements (ledger entries excluding OPENING_BALANCE — opening balance does not lock editing)
    ledger_count = db.query(func.count(InventoryLedger.id)).filter(
        and_(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.transaction_type != 'OPENING_BALANCE'
        )
    ).scalar() or 0
    
    has_transactions = (sales_count > 0) or (purchase_count > 0) or (ledger_count > 0)
    
    return {
        "hasTransactions": has_transactions,
        "salesCount": sales_count,
        "purchaseCount": purchase_count,
        "ledgerCount": ledger_count
    }


# --- Inventory corrections (audit trail; do not modify sales, FEFO, or pricing) ---

@router.get("/{item_id}/ledger-batches", response_model=LedgerBatchesResponse)
def get_ledger_batches(
    item_id: UUID,
    branch_id: UUID = Query(..., description="Branch ID"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    List ledger rows with positive quantity for this item/branch (for cost-adjustment batch selection).
    Returns ledger_id, batch_number, expiry_date, unit_cost, quantity per row.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    rows = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.quantity_delta > 0,
        )
        .order_by(InventoryLedger.expiry_date.asc().nulls_last(), InventoryLedger.batch_number.asc())
        .all()
    )
    entries = [
        LedgerBatchEntry(
            ledger_id=r.id,
            batch_number=r.batch_number,
            expiry_date=r.expiry_date.isoformat() if r.expiry_date else None,
            unit_cost=float(r.unit_cost or 0),
            quantity=float(r.quantity_delta or 0),
        )
        for r in rows
    ]
    return LedgerBatchesResponse(entries=entries)


def _batch_current_quantity(db: Session, item_id: UUID, branch_id: UUID, batch_number: str, expiry_date: Optional[date]) -> float:
    """Current quantity (sum of quantity_delta) for batch (batch_number, expiry_date)."""
    q = db.query(func.coalesce(func.sum(InventoryLedger.quantity_delta), 0)).filter(
        and_(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.batch_number == batch_number,
        )
    )
    if expiry_date is not None:
        q = q.filter(InventoryLedger.expiry_date == expiry_date)
    else:
        q = q.filter(InventoryLedger.expiry_date.is_(None))
    result = q.scalar()
    return float(result) if result is not None else 0.0


@router.post("/{item_id}/corrections/cost-adjustment", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
def post_cost_adjustment(
    item_id: UUID,
    body: CostAdjustmentRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Adjust batch cost (valuation only). Quantity unchanged. No change to sales or COGS history.
    Requires permission inventory.adjust_cost. Recorded in item_movements.
    """
    user, _ = current_user_and_db
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not _user_has_correction_permission(db, user.id, body.branch_id, "inventory.adjust_cost"):
        raise HTTPException(status_code=403, detail="Permission inventory.adjust_cost required for this branch.")
    branch = db.query(Branch).filter(Branch.id == body.branch_id, Branch.company_id == item.company_id).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Branch not found or does not belong to company.")
    ledger_row = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.id == body.batch_id,
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == body.branch_id,
        )
        .with_for_update()
        .first()
    )
    if not ledger_row:
        raise HTTPException(status_code=404, detail="Batch not found or does not belong to this item/branch.")
    remaining = _batch_current_quantity(db, item_id, body.branch_id, ledger_row.batch_number or "", ledger_row.expiry_date)
    if remaining <= 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot adjust cost for a batch with no remaining stock (batch fully depleted).",
        )
    previous_cost = Decimal(str(ledger_row.unit_cost))
    new_cost = Decimal(str(body.new_unit_cost))
    if previous_cost == new_cost:
        raise HTTPException(status_code=400, detail="New cost is unchanged.")
    try:
        movement = ItemMovement(
            company_id=item.company_id,
            branch_id=body.branch_id,
            item_id=item_id,
            movement_type="COST_ADJUSTMENT",
            ledger_id=ledger_row.id,
            quantity=Decimal("0"),
            previous_unit_cost=previous_cost,
            new_unit_cost=new_cost,
            reason=body.reason.strip(),
            performed_by=user.id,
        )
        db.add(movement)
        ledger_row.unit_cost = new_cost
        ledger_row.total_cost = new_cost * ledger_row.quantity_delta
        db.flush()
        db.commit()
        db.refresh(movement)
        return CorrectionResponse(
            success=True,
            message=f"Batch cost updated from {previous_cost} to {new_cost}. Audited.",
            movement_id=movement.id,
            item_id=item_id,
            branch_id=body.branch_id,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{item_id}/corrections/batch-quantity-correction", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
def post_batch_quantity_correction(
    item_id: UUID,
    body: BatchQuantityCorrectionRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Correct batch quantity to match physical count. Forward correction only; no change to sales history.
    Requires permission inventory.adjust_batch_quantity. Appends ledger row; recorded in item_movements.
    """
    user, _ = current_user_and_db
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not _user_has_correction_permission(db, user.id, body.branch_id, "inventory.adjust_batch_quantity"):
        raise HTTPException(status_code=403, detail="Permission inventory.adjust_batch_quantity required for this branch.")
    branch = db.query(Branch).filter(Branch.id == body.branch_id, Branch.company_id == item.company_id).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Branch not found or does not belong to company.")
    expiry_date_parsed = None
    if body.expiry_date and body.expiry_date.strip():
        try:
            expiry_date_parsed = date.fromisoformat(body.expiry_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expiry_date; use YYYY-MM-DD.")
    current_qty = _batch_current_quantity(db, item_id, body.branch_id, body.batch_number.strip(), expiry_date_parsed)
    physical = float(body.physical_count)
    difference = physical - current_qty
    if difference == 0:
        raise HTTPException(status_code=400, detail="Physical count matches current quantity; no correction needed.")
    if current_qty + difference < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reduce batch by {abs(difference)}: current quantity is {current_qty}. Would go below zero.",
        )
    quantity_delta = Decimal(str(difference))
    batches = InventoryService.get_stock_by_batch(db, item_id, body.branch_id)
    unit_cost = Decimal("0")
    for b in batches or []:
        bn_ok = (b.get("batch_number") or "").strip() == body.batch_number.strip()
        ed = b.get("expiry_date")
        if ed is not None and hasattr(ed, "date"):
            ed = getattr(ed, "date", lambda: ed)()
        ed_ok = (expiry_date_parsed is None and ed is None) or (expiry_date_parsed is not None and ed == expiry_date_parsed)
        if bn_ok and ed_ok:
            unit_cost = Decimal(str(b.get("unit_cost", 0)))
            break
    if unit_cost <= 0:
        unit_cost = CanonicalPricingService.get_best_available_cost(db, item_id, body.branch_id, item.company_id)
    if unit_cost is None or unit_cost <= 0:
        unit_cost = Decimal("0")
    total_cost = unit_cost * abs(quantity_delta)
    try:
        ledger_entry = InventoryLedger(
            company_id=item.company_id,
            branch_id=body.branch_id,
            item_id=item_id,
            batch_number=body.batch_number.strip(),
            expiry_date=expiry_date_parsed,
            transaction_type="ADJUSTMENT",
            reference_type="BATCH_QUANTITY_CORRECTION",
            reference_id=None,
            quantity_delta=quantity_delta,
            unit_cost=unit_cost,
            total_cost=total_cost,
            created_by=user.id,
            notes=body.reason.strip()[:2000] if body.reason else None,
        )
        db.add(ledger_entry)
        db.flush()
        movement = ItemMovement(
            company_id=item.company_id,
            branch_id=body.branch_id,
            item_id=item_id,
            movement_type="BATCH_QUANTITY_CORRECTION",
            ledger_id=ledger_entry.id,
            quantity=quantity_delta,
            reason=body.reason.strip(),
            performed_by=user.id,
        )
        db.add(movement)
        SnapshotService.upsert_inventory_balance(db, item.company_id, body.branch_id, item_id, float(quantity_delta))
        SnapshotRefreshService.schedule_snapshot_refresh(db, item.company_id, body.branch_id, item_id=item_id)
        db.commit()
        db.refresh(movement)
        return CorrectionResponse(
            success=True,
            message=f"Batch quantity corrected by {difference} base units. Audited.",
            movement_id=movement.id,
            item_id=item_id,
            branch_id=body.branch_id,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{item_id}/corrections/batch-metadata-correction", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
def post_batch_metadata_correction(
    item_id: UUID,
    body: BatchMetadataCorrectionRequest,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Correct batch metadata (batch_number, expiry_date). No quantity or cost change.
    Requires permission inventory.adjust_batch_metadata. Recorded in item_movements.
    """
    user, _ = current_user_and_db
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not _user_has_correction_permission(db, user.id, body.branch_id, "inventory.adjust_batch_metadata"):
        raise HTTPException(status_code=403, detail="Permission inventory.adjust_batch_metadata required for this branch.")
    branch = db.query(Branch).filter(Branch.id == body.branch_id, Branch.company_id == item.company_id).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Branch not found or does not belong to company.")
    expiry_parsed = None
    if body.expiry_date and body.expiry_date.strip():
        try:
            expiry_parsed = date.fromisoformat(body.expiry_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expiry_date; use YYYY-MM-DD.")
    new_expiry_parsed = None
    if body.new_expiry_date and body.new_expiry_date.strip():
        try:
            new_expiry_parsed = date.fromisoformat(body.new_expiry_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid new_expiry_date; use YYYY-MM-DD.")
    new_batch_number = body.new_batch_number.strip() if body.new_batch_number and body.new_batch_number.strip() else None
    if not new_batch_number and new_expiry_parsed is None:
        raise HTTPException(status_code=400, detail="Provide at least one of new_batch_number or new_expiry_date.")
    rows = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == body.branch_id,
            InventoryLedger.batch_number == body.batch_number.strip(),
        )
        .with_for_update()
    )
    if expiry_parsed is not None:
        rows = rows.filter(InventoryLedger.expiry_date == expiry_parsed)
    else:
        rows = rows.filter(InventoryLedger.expiry_date.is_(None))
    rows = rows.all()
    if not rows:
        raise HTTPException(status_code=404, detail="No ledger rows found for this batch.")
    metadata_before = {
        "batch_number": body.batch_number.strip(),
        "expiry_date": body.expiry_date if body.expiry_date else None,
    }
    metadata_after = {
        "batch_number": new_batch_number if new_batch_number else body.batch_number.strip(),
        "expiry_date": body.new_expiry_date if body.new_expiry_date else body.expiry_date,
    }
    if new_expiry_parsed is not None:
        metadata_after["expiry_date"] = new_expiry_parsed.isoformat()
    try:
        movement = ItemMovement(
            company_id=item.company_id,
            branch_id=body.branch_id,
            item_id=item_id,
            movement_type="BATCH_METADATA_CORRECTION",
            ledger_id=rows[0].id,
            quantity=Decimal("0"),
            metadata_before=metadata_before,
            metadata_after=metadata_after,
            reason=body.reason.strip(),
            performed_by=user.id,
        )
        db.add(movement)
        for row in rows:
            if new_batch_number:
                row.batch_number = new_batch_number
            if new_expiry_parsed is not None:
                row.expiry_date = new_expiry_parsed
        db.flush()
        SnapshotRefreshService.schedule_snapshot_refresh(
            db, item.company_id, body.branch_id, item_id=item_id
        )
        db.commit()
        db.refresh(movement)
        return CorrectionResponse(
            success=True,
            message="Batch metadata updated. Audited.",
            movement_id=movement.id,
            item_id=item_id,
            branch_id=body.branch_id,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

