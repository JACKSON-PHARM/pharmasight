"""
Item schemas for request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class ItemUnitBase(BaseModel):
    """Item unit base schema"""
    unit_name: str = Field(..., description="Unit name (box, carton, tablet, etc.)")
    multiplier_to_base: float = Field(..., gt=0, description="Multiplier to base unit")
    is_default: bool = Field(default=False, description="Is this the default unit?")


class ItemUnitCreate(ItemUnitBase):
    """Create item unit"""
    pass


class ItemUnitResponse(ItemUnitBase):
    """Item unit response"""
    id: UUID
    item_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ItemBase(BaseModel):
    """Item base schema"""
    name: str = Field(..., min_length=1, max_length=255)
    generic_name: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    base_unit: str = Field(..., description="Base unit (tablet, ml, gram, etc.)")
    default_cost: float = Field(default=0, ge=0)


class ItemCreate(ItemBase):
    """Create item request"""
    company_id: UUID
    units: List[ItemUnitCreate] = Field(default_factory=list, description="Unit conversions")


class ItemUpdate(BaseModel):
    """Update item request"""
    name: Optional[str] = None
    generic_name: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    base_unit: Optional[str] = None
    default_cost: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ItemResponse(ItemBase):
    """Item response"""
    id: UUID
    company_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    units: List[ItemUnitResponse] = []

    class Config:
        from_attributes = True


class ItemPricingBase(BaseModel):
    """Item pricing base schema"""
    markup_percent: Optional[float] = Field(None, ge=0, description="Markup percentage")
    min_margin_percent: Optional[float] = Field(None, ge=0, description="Minimum margin percentage")
    rounding_rule: Optional[str] = Field(None, description="Rounding rule (nearest_1, nearest_5, nearest_10)")


class ItemPricingCreate(ItemPricingBase):
    """Create item pricing"""
    item_id: UUID


class ItemPricingResponse(ItemPricingBase):
    """Item pricing response"""
    id: UUID
    item_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompanyPricingDefaultBase(BaseModel):
    """Company pricing defaults base schema"""
    default_markup_percent: float = Field(default=30.00, ge=0)
    rounding_rule: str = Field(default="nearest_1")
    min_margin_percent: float = Field(default=0, ge=0)


class CompanyPricingDefaultCreate(CompanyPricingDefaultBase):
    """Create company pricing defaults"""
    company_id: UUID


class CompanyPricingDefaultResponse(CompanyPricingDefaultBase):
    """Company pricing defaults response"""
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

