"""
Inventory API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.models import Item, Branch
from app.schemas.inventory import StockBalance, StockAvailability, BatchStock
from app.services.inventory_service import InventoryService

router = APIRouter()


@router.get("/stock/{item_id}/{branch_id}", response_model=dict)
def get_current_stock(item_id: UUID, branch_id: UUID, db: Session = Depends(get_db)):
    """Get current stock balance for an item"""
    stock = InventoryService.get_current_stock(db, item_id, branch_id)
    return {
        "item_id": item_id,
        "branch_id": branch_id,
        "stock": stock,
        "unit": "base_units"
    }


@router.get("/availability/{item_id}/{branch_id}", response_model=StockAvailability)
def get_stock_availability(item_id: UUID, branch_id: UUID, db: Session = Depends(get_db)):
    """Get stock availability with unit breakdown and batch breakdown"""
    availability = InventoryService.get_stock_availability(db, item_id, branch_id)
    if not availability:
        raise HTTPException(status_code=404, detail="Item not found")
    return availability


@router.get("/batches/{item_id}/{branch_id}", response_model=List[dict])
def get_stock_by_batch(item_id: UUID, branch_id: UUID, db: Session = Depends(get_db)):
    """Get stock breakdown by batch (FEFO order)"""
    batches = InventoryService.get_stock_by_batch(db, item_id, branch_id)
    return batches


@router.post("/allocate-fefo", response_model=List[dict])
def allocate_stock_fefo(
    item_id: UUID,
    branch_id: UUID,
    quantity: float,
    unit_name: str,
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
def get_all_stock(branch_id: UUID, db: Session = Depends(get_db)):
    """Get stock for all items in a branch"""
    # Get all items for the branch's company
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    items = db.query(Item).filter(Item.company_id == branch.company_id).all()
    
    stock_list = []
    for item in items:
        stock = InventoryService.get_current_stock(db, item.id, branch_id)
        if stock > 0:  # Only show items with stock
            stock_list.append({
                "item_id": item.id,
                "item_name": item.name,
                "base_unit": item.base_unit,
                "stock": stock
            })
    
    return stock_list

