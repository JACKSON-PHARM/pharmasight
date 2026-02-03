"""
Inventory API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.dependencies import get_tenant_db
from app.models import Item, Branch
from app.schemas.inventory import StockBalance, StockAvailability, BatchStock
from app.services.inventory_service import InventoryService

router = APIRouter()


@router.get("/stock/{item_id}/{branch_id}", response_model=dict)
def get_current_stock(item_id: UUID, branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get current stock balance for an item"""
    stock = InventoryService.get_current_stock(db, item_id, branch_id)
    return {
        "item_id": item_id,
        "branch_id": branch_id,
        "stock": stock,
        "unit": "base_units"
    }


@router.get("/availability/{item_id}/{branch_id}", response_model=StockAvailability)
def get_stock_availability(item_id: UUID, branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get stock availability with unit breakdown and batch breakdown"""
    availability = InventoryService.get_stock_availability(db, item_id, branch_id)
    if not availability:
        raise HTTPException(status_code=404, detail="Item not found")
    return availability


@router.get("/batches/{item_id}/{branch_id}", response_model=List[dict])
def get_stock_by_batch(item_id: UUID, branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get stock breakdown by batch (FEFO order)"""
    batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
    return batches


@router.post("/allocate-fefo", response_model=List[dict])
def allocate_stock_fefo(
    item_id: UUID,
    branch_id: UUID,
    quantity: float,
    unit_name: str,
    db: Session = Depends(get_tenant_db)
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
    db: Session = Depends(get_tenant_db)
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
def get_all_stock(branch_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get stock for all items in a branch (OPTIMIZED - no N+1 queries)"""
    # Get all items for the branch's company
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    items = db.query(Item).filter(Item.company_id == branch.company_id).all()
    
    if not items:
        return []
    
    item_ids = [item.id for item in items]
    
    # Aggregate stock for all items in ONE query (no N+1!)
    from sqlalchemy import func
    from app.models import InventoryLedger
    
    stock_aggregates = db.query(
        InventoryLedger.item_id,
        func.sum(InventoryLedger.quantity_delta).label('total_stock')
    ).filter(
        InventoryLedger.item_id.in_(item_ids),
        InventoryLedger.branch_id == branch_id
    ).group_by(InventoryLedger.item_id).all()
    
    # Build stock map
    stock_map = {row.item_id: int(row.total_stock or 0) for row in stock_aggregates}
    
    # Build response (only items with stock > 0)
    stock_list = []
    for item in items:
        stock = stock_map.get(item.id, 0)
        if stock > 0:
            stock_list.append({
                "item_id": item.id,
                "item_name": item.name,
                "base_unit": item.base_unit,
                "stock": stock
            })
    
    return stock_list


@router.get("/branch/{branch_id}/items-in-stock-count", response_model=dict)
def get_items_in_stock_count(branch_id: UUID, db: Session = Depends(get_tenant_db)):
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
def get_all_stock_overview(branch_id: UUID, db: Session = Depends(get_tenant_db)):
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
    
    item_ids = [item.id for item in items]
    
    # Aggregate stock for all items in ONE query
    from sqlalchemy import func
    from app.models import InventoryLedger
    
    stock_aggregates = db.query(
        InventoryLedger.item_id,
        func.sum(InventoryLedger.quantity_delta).label('total_stock')
    ).filter(
        InventoryLedger.item_id.in_(item_ids),
        InventoryLedger.branch_id == branch_id
    ).group_by(InventoryLedger.item_id).all()
    
    stock_map = {row.item_id: int(row.total_stock or 0) for row in stock_aggregates}
    
    # Build response with unit breakdown from item columns (items table is source of truth)
    result = []
    for item in items:
        stock = stock_map.get(item.id, 0)
        if stock > 0:
            wholesale_name = (item.wholesale_unit or item.base_unit or "piece").strip() or "piece"
            retail_name = (item.retail_unit or "").strip()
            supplier_name = (item.supplier_unit or "").strip()
            pack = max(1, int(item.pack_size or 1))
            wups = max(0.0001, float(item.wholesale_units_per_supplier or 1))
            units_list = [(wholesale_name, 1.0)]
            if retail_name and (retail_name.lower() != wholesale_name.lower() or pack > 1):
                units_list.append((item.retail_unit.strip(), 1.0 / pack))
            if supplier_name and supplier_name.lower() != wholesale_name.lower():
                units_list.append((item.supplier_unit.strip(), wups))
            units_list.sort(key=lambda x: x[1], reverse=True)
            unit_breakdown = []
            remaining = stock
            for unit_name, mult in units_list:
                if mult > 0 and remaining >= mult:
                    count = int(remaining / mult)
                    remaining = remaining % int(mult) if mult >= 1 else remaining % mult
                    if count > 0:
                        unit_breakdown.append(f"{count} {unit_name}")
            if remaining > 0:
                unit_breakdown.append(f"{remaining} {item.base_unit}")
            
            result.append({
                "item_id": item.id,
                "item_name": item.name,
                "base_unit": item.base_unit,
                "stock": stock,
                "stock_display": ", ".join(unit_breakdown) if unit_breakdown else f"{stock} {item.base_unit}"
            })
    
    return result

