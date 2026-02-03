"""
Items API routes.

All item endpoints use get_tenant_db: session is the logged-in context (tenant DB when
X-Tenant-Subdomain is set, else default DB). Same company/DB as rest of app.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, or_, and_, desc
from typing import List, Optional
from uuid import UUID, uuid4
from app.dependencies import get_tenant_db
from app.models import (
    Item, ItemUnit, ItemPricing, CompanyPricingDefault,
    InventoryLedger, SupplierInvoice, SupplierInvoiceItem, Supplier,
    PurchaseOrder, PurchaseOrderItem
)
from app.models.sale import SalesInvoice, SalesInvoiceItem
from app.schemas.item import (
    ItemCreate, ItemResponse, ItemUpdate,
    ItemUnitCreate, ItemUnitResponse,
    ItemPricingCreate, ItemPricingResponse,
    CompanyPricingDefaultCreate, CompanyPricingDefaultResponse,
    ItemsBulkCreate, ItemOverviewResponse
)
from app.services.pricing_service import PricingService
from app.services.items_service import create_item as svc_create_item, ensure_item_units_from_3tier
from app.services.canonical_pricing import CanonicalPricingService

logger = logging.getLogger(__name__)
router = APIRouter()


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
def create_item(item: ItemCreate, db: Session = Depends(get_tenant_db)):
    """Create a new item with 3-tier units. SKU auto-generated if not provided."""
    try:
        db_item = svc_create_item(db, item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/search")
def search_items(
    q: str = Query(..., min_length=2, description="Search query"),
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID for pricing and stock (optional)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    include_pricing: bool = Query(False, description="Include pricing info (slower)"),
    context: Optional[str] = Query(None, description="Context: 'purchase_order' for PO-specific fields"),
    db: Session = Depends(get_tenant_db)
):
    """
    Item search: reads only from DB (items table). Joins with inventory_ledger for
    stock and cost; if no ledger data, falls back to item default_cost_per_base.
    Excel import only seeds the DB; this endpoint never uses Excel.
    Returns: id, name, base_unit, prices, sku, stock, VAT info. Ordered by
    best match then in-stock first when branch_id given.
    """
    search_term_lower = q.lower()
    search_term_pattern = f"%{search_term_lower}%"
    search_term_start = f"{search_term_lower}%"
    
    # OPTIMIZED: Use database-level ORDER BY and LIMIT for much better performance
    # Calculate relevance score in SQL using CASE statements
    from sqlalchemy import case
    
    # Build relevance score: name matches get highest priority, then SKU, then barcode (label so row.relevance_score works)
    relevance_score = case(
        (func.lower(Item.name).like(search_term_start), 1000),  # Name starts with (highest priority)
        (func.lower(Item.name).like(search_term_pattern), 500),  # Name contains
        (and_(Item.sku.isnot(None), func.lower(Item.sku).like(search_term_start)), 100),  # SKU starts with
        (and_(Item.sku.isnot(None), func.lower(Item.sku).like(search_term_pattern)), 50),  # SKU contains
        (and_(Item.barcode.isnot(None), func.lower(Item.barcode).like(search_term_start)), 100),  # Barcode starts with
        (and_(Item.barcode.isnot(None), func.lower(Item.barcode).like(search_term_pattern)), 50),  # Barcode contains
        else_=0
    ).label("relevance_score")

    # Build base query: items from DB only (no Excel). Join with ledger/costs later; fallback to item defaults.
    base_query = db.query(
        Item.id,
        Item.name,
        Item.base_unit,
        Item.sku,
        Item.category,
        Item.is_active,
        Item.vat_rate,
        Item.vat_category,
        relevance_score,
    ).filter(
        Item.company_id == company_id,
        Item.is_active == True,
        or_(
            Item.name.ilike(search_term_pattern),
            and_(Item.sku.isnot(None), Item.sku.ilike(search_term_pattern)),
            and_(Item.barcode.isnot(None), Item.barcode.ilike(search_term_pattern))
        )
    )
    
    # OPTIMIZED: Order and limit at database level for maximum performance
    # Order by relevance (best match first), then alphabetically
    items = base_query.order_by(
        relevance_score.desc(),
        func.lower(Item.name).asc()
    ).limit(limit).all()
    
    if not items:
        return []
    
    item_ids = [item.id for item in items]
    
    # Get stock for the limited items only (batch query - much faster)
    stock_map = {}
    if branch_id:
        stock_data = (
            db.query(
                InventoryLedger.item_id,
                func.coalesce(func.sum(InventoryLedger.quantity_delta), 0).label('total_stock')
            )
            .filter(
                InventoryLedger.item_id.in_(item_ids),
                InventoryLedger.company_id == company_id,
                InventoryLedger.branch_id == branch_id
            )
            .group_by(InventoryLedger.item_id)
            .all()
        )
        stock_map = {row.item_id: int(row.total_stock) if row.total_stock else 0 for row in stock_data}
        # Order: in-stock first, then best match (relevance), then name
        items = sorted(
            items,
            key=lambda r: (
                0 if stock_map.get(r.id, 0) > 0 else 1,
                -(getattr(r, "relevance_score", 0) or 0),
                (r.name or "").lower(),
            ),
        )
    
    # OPTIMIZED: Only fetch purchase/order info if pricing is requested
    purchase_price_map = {}
    last_supplier_map = {}
    last_order_date_map = {}
    sale_price_map = {}
    last_supply_date_map = {}
    last_unit_cost_ledger_map = {}
    
    if include_pricing:
        # Get last purchase info - OPTIMIZED: Use window function for reliable results
        from sqlalchemy import desc
        from sqlalchemy.sql import func as sql_func
        last_purchase_subq = (
            db.query(
                SupplierInvoiceItem.item_id,
                SupplierInvoiceItem.unit_cost_exclusive,
                SupplierInvoice.supplier_id,
                SupplierInvoice.created_at.label('last_purchase_date'),
                sql_func.row_number().over(
                    partition_by=SupplierInvoiceItem.item_id,
                    order_by=desc(SupplierInvoice.created_at)
                ).label('rn')
            )
            .join(SupplierInvoice, SupplierInvoiceItem.purchase_invoice_id == SupplierInvoice.id)
            .filter(
                SupplierInvoiceItem.item_id.in_(item_ids),
                SupplierInvoice.company_id == company_id
            )
            .subquery()
        )
        last_purchases = (
            db.query(
                last_purchase_subq.c.item_id,
                last_purchase_subq.c.unit_cost_exclusive,
                last_purchase_subq.c.supplier_id,
                last_purchase_subq.c.last_purchase_date
            )
            .filter(last_purchase_subq.c.rn == 1)
            .all()
        )
        
        purchase_price_map = {
            row.item_id: float(row.unit_cost_exclusive) if row.unit_cost_exclusive else 0.0 
            for row in last_purchases
        }
        
        # Get supplier names in batch (from purchase history)
        supplier_ids = {row.supplier_id for row in last_purchases if row.supplier_id}
        if supplier_ids:
            suppliers = {s.id: s.name for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()}
            last_supplier_map = {row.item_id: suppliers.get(row.supplier_id, '') for row in last_purchases if row.supplier_id}
        # Fallback: default_supplier_id when no purchase history
        ids_without_supplier = [i for i in item_ids if i not in last_supplier_map]
        if ids_without_supplier and include_pricing:
            default_rows = db.query(Item.id, Item.default_supplier_id).filter(
                Item.id.in_(ids_without_supplier),
                Item.default_supplier_id.isnot(None)
            ).all()
            if default_rows:
                default_supplier_ids = {r.default_supplier_id for r in default_rows if r.default_supplier_id}
                default_suppliers = {s.id: s.name for s in db.query(Supplier).filter(Supplier.id.in_(default_supplier_ids)).all()} if default_supplier_ids else {}
                for r in default_rows:
                    if r.default_supplier_id:
                        last_supplier_map[r.id] = default_suppliers.get(r.default_supplier_id, '')
        
        # Get last order dates - OPTIMIZED: Use window function
        last_order_subq = (
            db.query(
                PurchaseOrderItem.item_id,
                PurchaseOrder.order_date.label('last_order_date'),
                sql_func.row_number().over(
                    partition_by=PurchaseOrderItem.item_id,
                    order_by=desc(PurchaseOrder.order_date)
                ).label('rn')
            )
            .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
            .filter(
                PurchaseOrderItem.item_id.in_(item_ids),
                PurchaseOrder.company_id == company_id
            )
            .subquery()
        )
        last_orders = (
            db.query(
                last_order_subq.c.item_id,
                last_order_subq.c.last_order_date
            )
            .filter(last_order_subq.c.rn == 1)
            .all()
        )
        
        last_order_date_map = {
            row.item_id: row.last_order_date.isoformat() if row.last_order_date else None 
            for row in last_orders
        }
        
        # For Purchase Order context, get additional fields from inventory_ledger
        last_supply_date_map = {}
        last_unit_cost_ledger_map = {}
        if context == 'purchase_order' and branch_id:
            # Get last supply date and unit cost from inventory_ledger (PURCHASE transactions)
            last_supply_subq = (
                db.query(
                    InventoryLedger.item_id,
                    InventoryLedger.created_at.label('last_supply_date'),
                    InventoryLedger.unit_cost,
                    sql_func.row_number().over(
                        partition_by=InventoryLedger.item_id,
                        order_by=desc(InventoryLedger.created_at)
                    ).label('rn')
                )
                .filter(
                    InventoryLedger.item_id.in_(item_ids),
                    InventoryLedger.company_id == company_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.transaction_type == "PURCHASE",
                    InventoryLedger.quantity_delta > 0
                )
                .subquery()
            )
            last_supplies = (
                db.query(
                    last_supply_subq.c.item_id,
                    last_supply_subq.c.last_supply_date,
                    last_supply_subq.c.unit_cost
                )
                .filter(last_supply_subq.c.rn == 1)
                .all()
            )
            
            last_supply_date_map = {
                row.item_id: row.last_supply_date.isoformat() if row.last_supply_date else None
                for row in last_supplies
            }
            last_unit_cost_ledger_map = {
                row.item_id: float(row.unit_cost) if row.unit_cost else 0.0
                for row in last_supplies
            }
        
        # sale_price: no longer from items table; use 0.0 if no external config (pricing from ledger only)
        for item in items:
            sale_price_map[item.id] = 0.0
    
    # Best available cost: batch when branch_id set (avoids N+1); else 0
    cost_from_ledger_map = {}
    if branch_id:
        cost_from_ledger_map = CanonicalPricingService.get_best_available_cost_batch(db, item_ids, branch_id, company_id)
    
    result = []
    for item in items:
        price_from_ledger = float(cost_from_ledger_map.get(item.id, 0)) if branch_id else 0.0
        purchase_price_val = purchase_price_map.get(item.id, price_from_ledger) if include_pricing else price_from_ledger
        last_unit_cost_val = last_unit_cost_ledger_map.get(item.id, purchase_price_map.get(item.id, price_from_ledger)) if context == 'purchase_order' else None
        
        item_data = {
            "id": str(item.id),
            "name": item.name,
            "base_unit": item.base_unit,
            "price": price_from_ledger,
            "sku": item.sku or "",
            "category": getattr(item, 'category', None) or "",
            "is_active": getattr(item, 'is_active', True),
            "current_stock": stock_map.get(item.id, 0) if branch_id else None,
            "vat_rate": float(item.vat_rate) if item.vat_rate else 0.0,
            "vat_category": getattr(item, 'vat_category', None) or "ZERO_RATED",
            "purchase_price": purchase_price_val,
            "sale_price": sale_price_map.get(item.id, 0.0) if include_pricing else 0.0,
            "last_supplier": last_supplier_map.get(item.id, "") if include_pricing else "",
            "last_order_date": last_order_date_map.get(item.id, None) if include_pricing else None
        }
        
        if context == 'purchase_order':
            item_data["last_supply_date"] = last_supply_date_map.get(item.id, None)
            item_data["last_unit_cost"] = last_unit_cost_val if last_unit_cost_val is not None else purchase_price_val
        
        result.append(item_data)
    
    return result


@router.get("/{item_id}", response_model=ItemResponse)
def get_item(
    item_id: UUID,
    branch_id: Optional[UUID] = Query(None, description="Branch ID for cost from ledger (optional)"),
    db: Session = Depends(get_tenant_db),
):
    """
    Get item by ID. Uses same DB/session as request (tenant when X-Tenant-Subdomain set).
    Cost from inventory_ledger; fallback item.default_cost_per_base. Units list is built from
    the item row (3-tier: base, retail, supplier) so the unit dropdown always shows all tiers.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    resp = ItemResponse.model_validate(item)
    # Streamline: units from item 3-tier columns only (no item_units table dependency)
    resp.units = _display_units_from_item(item)
    resp.default_cost = float(
        CanonicalPricingService.get_best_available_cost(db, item.id, branch_id, item.company_id)
    ) if branch_id else 0.0
    # Keep item_units table in sync for other code paths (e.g. inventory conversion)
    ensure_item_units_from_3tier(db, item)
    return resp


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
    db: Session = Depends(get_tenant_db)
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
def get_items_count(company_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get count of items for a company (fast, no data loading)"""
    count = db.query(Item).filter(Item.company_id == company_id).count()
    return {"count": count}


@router.get("/company/{company_id}/overview", response_model=List[ItemOverviewResponse])
def get_items_overview(
    company_id: UUID,
    branch_id: Optional[UUID] = Query(None, description="Branch ID for stock calculation (optional)"),
    db: Session = Depends(get_tenant_db)
):
    """
    Get items with overview data (stock, supplier, cost) - OPTIMIZED
    
    Single query endpoint to avoid N+1 problems.
    Computes stock from inventory_ledger aggregation.
    Gets last supplier and cost from purchase transactions.
    """
    # Base query for items
    items_query = db.query(Item).filter(Item.company_id == company_id)
    items = items_query.options(selectinload(Item.units)).all()
    
    if not items:
        return []
    
    item_ids = [item.id for item in items]
    
    # Aggregate stock from inventory_ledger (single query)
    stock_query = db.query(
        InventoryLedger.item_id,
        func.sum(InventoryLedger.quantity_delta).label('total_stock')
    ).filter(
        InventoryLedger.item_id.in_(item_ids),
        InventoryLedger.company_id == company_id
    )
    
    if branch_id:
        stock_query = stock_query.filter(InventoryLedger.branch_id == branch_id)
    
    stock_data = {row.item_id: float(row.total_stock or 0) for row in stock_query.group_by(InventoryLedger.item_id).all()}
    
    # Check which items have transactions (for locking structural fields)
    items_with_transactions = set(
        db.query(InventoryLedger.item_id)
        .filter(InventoryLedger.item_id.in_(item_ids))
        .distinct()
        .all()
    )
    items_with_transactions = {row[0] for row in items_with_transactions}
    
    # Get last supplier and cost from purchase invoices (optimized subquery)
    # Use purchase_invoice_items joined with purchase_invoices to get supplier
    from sqlalchemy import desc
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
        .filter(
            SupplierInvoiceItem.item_id.in_(item_ids),
            SupplierInvoice.company_id == company_id
        )
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
            'vat_rate': float(item.vat_rate) if item.vat_rate else 0.0,
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
            'current_stock': stock_data.get(item.id, 0.0),
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
    
    return result_dicts


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
    
    # Eagerly load units to avoid N+1 queries (much faster!)
    # Use selectinload for better performance with many items
    if include_units:
        query = query.options(selectinload(Item.units))
    
    # Apply pagination if limit is provided
    if limit:
        query = query.limit(limit).offset(offset)
    
    items = query.all()
    # Do not expose items table price columns — overwrite with 0 (cost from ledger via search/overview only)
    result = []
    for item in items:
        resp = ItemResponse.model_validate(item)
        resp.default_cost = 0.0
        resp.units = _display_units_from_item(item)
        result.append(resp)
    return result


@router.put("/{item_id}", response_model=ItemResponse)
def update_item(item_id: UUID, item_update: ItemUpdate, db: Session = Depends(get_tenant_db)):
    """
    Update item with strict business rules:
    - SKU is immutable (never editable)
    - Base unit and unit conversions are editable ONLY if item has no inventory_ledger records
    - Name, category, pricing, barcode are always editable
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Check if item has any transactions
    has_transactions = db.query(InventoryLedger).filter(InventoryLedger.item_id == item_id).first() is not None
    
    # Get units to update before converting to dict
    units_to_update = item_update.units if hasattr(item_update, 'units') and item_update.units is not None else None
    
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
    
    # Business Rule 2: Base unit and 3-tier unit fields locked if item has transactions
    if has_transactions:
        locked_fields = ['base_unit', 'supplier_unit', 'wholesale_unit', 'retail_unit', 'pack_size', 'can_break_bulk']
        attempted_locked = [f for f in locked_fields if f in update_data]
        if attempted_locked:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot modify {', '.join(attempted_locked)} after item has inventory transactions. "
                       f"These fields are locked to maintain data integrity."
            )

    # 3-tier validation: breakable => pack_size > 1
    cb = update_data.get('can_break_bulk') if 'can_break_bulk' in update_data else getattr(item, 'can_break_bulk', False)
    ps = update_data.get('pack_size') if 'pack_size' in update_data else getattr(item, 'pack_size', 1) or 1
    if cb and (int(ps) if ps is not None else 1) < 2:
        raise HTTPException(status_code=400, detail="Breakable items must have pack_size > 1")
    
    # Apply allowed updates
    for field, value in update_data.items():
        setattr(item, field, value)
    
    # Handle unit updates if provided (only if no transactions)
    if units_to_update is not None:
        if has_transactions:
            raise HTTPException(
                status_code=400,
                detail="Cannot modify unit conversions after item has inventory transactions. "
                       "These fields are locked to maintain data integrity."
            )
        
        # Get existing units
        existing_units = {str(u.id): u for u in db.query(ItemUnit).filter(ItemUnit.item_id == item_id).all()}
        existing_unit_ids = set(existing_units.keys())
        
        # Get IDs from update request
        update_unit_ids = {str(u.id) for u in units_to_update if u.id}
        
        # Delete units that are no longer in the update list
        units_to_delete = existing_unit_ids - update_unit_ids
        for unit_id in units_to_delete:
            db.delete(existing_units[unit_id])
        
        # Update or create units
        for unit_data in units_to_update:
            if unit_data.id and str(unit_data.id) in existing_units:
                # Update existing unit
                unit = existing_units[str(unit_data.id)]
                unit.unit_name = unit_data.unit_name
                unit.multiplier_to_base = unit_data.multiplier_to_base
                unit.is_default = unit_data.is_default
            else:
                # Create new unit
                new_unit = ItemUnit(
                    item_id=item_id,
                    unit_name=unit_data.unit_name,
                    multiplier_to_base=unit_data.multiplier_to_base,
                    is_default=unit_data.is_default
                )
                db.add(new_unit)
    
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: UUID, db: Session = Depends(get_tenant_db)):
    """Soft delete item (set is_active=False)"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.is_active = False
    db.commit()
    return None


@router.post("/bulk", response_model=dict, status_code=status.HTTP_201_CREATED)
def bulk_create_items(bulk_data: ItemsBulkCreate, db: Session = Depends(get_tenant_db)):
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
        units_to_insert = []
        
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
            
            # Step 5: Prepare units for bulk insert (with deduplication)
            # Track units per item to avoid duplicates
            units_by_item = {}  # {item_id: {unit_name: unit_dict}}
            
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
                    
                    # Initialize units dict for this item if not exists
                    if item_id not in units_by_item:
                        units_by_item[item_id] = {}
                    
                    units_data = item_data.units if hasattr(item_data, 'units') else item_data.dict().get('units', [])
                    
                    # Add units (deduplicate by unit_name)
                    for unit_data in units_data:
                        unit_dict = unit_data.model_dump() if hasattr(unit_data, 'model_dump') else unit_data.dict()
                        unit_name = unit_dict.get('unit_name', '').upper().strip()
                        if unit_name:
                            # Only add if not already exists for this item
                            if unit_name not in units_by_item[item_id]:
                                units_by_item[item_id][unit_name] = {
                                    'item_id': item_id,
                                    **unit_dict
                                }
                    
                    # Add default base unit if not provided (check if already exists)
                    base_unit_name = item_data.base_unit.upper().strip() if item_data.base_unit else None
                    if base_unit_name and base_unit_name not in units_by_item[item_id]:
                        units_by_item[item_id][base_unit_name] = {
                            'item_id': item_id,
                            'unit_name': base_unit_name,
                            'multiplier_to_base': 1.0,
                            'is_default': True
                        }
                    
                    created_count += 1
                    
                except Exception as e:
                    errors.append({
                        'index': idx,
                        'name': item_dict.get('name', 'Unknown'),
                        'error': f"Unit creation error: {str(e)}"
                    })
            
            # Step 6: Flatten units dict and check for existing units in database
            if units_by_item:
                # Get all item_ids and unit_names to check for existing units
                all_item_ids = list(units_by_item.keys())
                all_unit_names = set()
                for item_units in units_by_item.values():
                    all_unit_names.update(unit['unit_name'] for unit in item_units.values())
                
                # Query existing units to avoid duplicates
                existing_units = db.query(ItemUnit).filter(
                    ItemUnit.item_id.in_(all_item_ids),
                    ItemUnit.unit_name.in_(list(all_unit_names))
                ).all()
                
                # Build set of existing (item_id, unit_name) pairs
                existing_unit_keys = {(str(unit.item_id), unit.unit_name.upper()) for unit in existing_units}
                
                # Only add units that don't already exist
                for item_id, item_units_dict in units_by_item.items():
                    for unit_name, unit_dict in item_units_dict.items():
                        unit_key = (str(item_id), unit_name.upper())
                        if unit_key not in existing_unit_keys:
                            units_to_insert.append(unit_dict)
            
            # Step 7: Bulk insert units (only new ones)
            if units_to_insert:
                try:
                    db.bulk_insert_mappings(ItemUnit, units_to_insert)
                except Exception as e:
                    # If still fails, try individual inserts with error handling
                    logger.warning(f"Bulk unit insert failed, trying individual: {str(e)}")
                    for unit_dict in units_to_insert:
                        try:
                            # Check if unit already exists before inserting
                            existing = db.query(ItemUnit).filter(
                                ItemUnit.item_id == unit_dict['item_id'],
                                ItemUnit.unit_name == unit_dict['unit_name']
                            ).first()
                            if not existing:
                                db.add(ItemUnit(**unit_dict))
                        except Exception as unit_error:
                            logger.warning(f"Failed to insert unit {unit_dict.get('unit_name')} for item {unit_dict.get('item_id')}: {str(unit_error)}")
                            continue
        
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
    db: Session = Depends(get_tenant_db)
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
    db: Session = Depends(get_tenant_db)
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
    
    # Check for inventory movements (ledger entries)
    ledger_count = db.query(func.count(InventoryLedger.id)).filter(
        and_(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == branch_id
        )
    ).scalar() or 0
    
    has_transactions = (sales_count > 0) or (purchase_count > 0) or (ledger_count > 0)
    
    return {
        "hasTransactions": has_transactions,
        "salesCount": sales_count,
        "purchaseCount": purchase_count,
        "ledgerCount": ledger_count
    }

