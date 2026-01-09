"""
Items API routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.models import Item, ItemUnit, ItemPricing, CompanyPricingDefault
from app.schemas.item import (
    ItemCreate, ItemResponse, ItemUpdate,
    ItemUnitCreate, ItemUnitResponse,
    ItemPricingCreate, ItemPricingResponse,
    CompanyPricingDefaultCreate, CompanyPricingDefaultResponse
)
from app.services.pricing_service import PricingService

router = APIRouter()


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
def create_item(item: ItemCreate, db: Session = Depends(get_db)):
    """Create a new item with units"""
    # Create item
    db_item = Item(**item.dict(exclude={"units"}))
    db.add(db_item)
    db.flush()  # Get ID
    
    # Create units
    for unit_data in item.units:
        db_unit = ItemUnit(item_id=db_item.id, **unit_data.dict())
        db.add(db_unit)
    
    # Create default base unit if not provided
    has_base_unit = any(u.unit_name == item.base_unit for u in item.units)
    if not has_base_unit:
        base_unit = ItemUnit(
            item_id=db_item.id,
            unit_name=item.base_unit,
            multiplier_to_base=1.0,
            is_default=True
        )
        db.add(base_unit)
    
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: UUID, db: Session = Depends(get_db)):
    """Get item by ID"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/company/{company_id}", response_model=List[ItemResponse])
def get_items_by_company(company_id: UUID, db: Session = Depends(get_db)):
    """Get all items for a company"""
    items = db.query(Item).filter(Item.company_id == company_id).all()
    return items


@router.put("/{item_id}", response_model=ItemResponse)
def update_item(item_id: UUID, item_update: ItemUpdate, db: Session = Depends(get_db)):
    """Update item"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    update_data = item_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: UUID, db: Session = Depends(get_db)):
    """Soft delete item (set is_active=False)"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.is_active = False
    db.commit()
    return None


@router.get("/{item_id}/recommended-price", response_model=dict)
def get_recommended_price(
    item_id: UUID,
    branch_id: UUID,
    company_id: UUID,
    unit_name: str,
    db: Session = Depends(get_db)
):
    """Get recommended selling price for item"""
    try:
        price_info = PricingService.calculate_recommended_price(
            db, item_id, branch_id, company_id, unit_name
        )
        if not price_info:
            raise HTTPException(status_code=404, detail="Item cost not available")
        return price_info
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

