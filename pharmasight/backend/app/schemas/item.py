"""
Item schemas for request/response validation.
3-tier UNIT system: supplier_unit (what we buy), wholesale_unit (what pharmacies buy),
retail_unit (what customers buy), pack_size (retail units per packet).
"""
from pydantic import BaseModel, Field, model_validator
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


class ItemUnitUpdate(BaseModel):
    """Update item unit (for edits)"""
    id: Optional[UUID] = Field(None, description="Unit ID (required for existing units)")
    unit_name: str = Field(..., description="Unit name (box, carton, tablet, etc.)")
    multiplier_to_base: float = Field(..., gt=0, description="Multiplier to base unit")
    is_default: bool = Field(default=False, description="Is this the default unit?")


class ItemUnitResponse(ItemUnitBase):
    """Item unit response"""
    id: UUID
    item_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ItemBase(BaseModel):
    """Item base schema with 3-tier UNIT system"""
    name: str = Field(..., min_length=1, max_length=255)
    generic_name: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    base_unit: Optional[str] = Field(None, description="Legacy: base unit; default = retail_unit")
    default_cost: float = Field(default=0, ge=0)
    # 3-TIER UNIT SYSTEM
    supplier_unit: str = Field(default="packet", description="What we buy: packet, box, bottle")
    wholesale_unit: str = Field(default="packet", description="What pharmacies buy")
    retail_unit: str = Field(default="tablet", description="What customers buy: tablet, capsule, ml, gram")
    pack_size: int = Field(default=1, ge=1, description="Retail per 1 wholesale (1 wholesale = pack_size retail)")
    wholesale_units_per_supplier: float = Field(default=1, ge=0.0001, description="Wholesale per 1 supplier (1 supplier = N wholesale); default 1")
    can_break_bulk: bool = Field(default=False, description="Can we sell individual retail units? (requires pack_size > 1)")
    purchase_price_per_supplier_unit: float = Field(default=0, ge=0, description="Cost per supplier unit")
    wholesale_price_per_wholesale_unit: float = Field(default=0, ge=0, description="Sell price per wholesale unit")
    retail_price_per_retail_unit: float = Field(default=0, ge=0, description="Sell price per retail unit")
    # VAT
    vat_category: str = Field(default="ZERO_RATED", description="ZERO_RATED | STANDARD_RATED")
    vat_rate: float = Field(default=0, ge=0, le=100, description="0 or 16")
    price_includes_vat: bool = Field(default=False, description="Is price inclusive of VAT?")
    is_vatable: Optional[bool] = Field(default=True, description="Is this item VATable?")
    vat_code: Optional[str] = Field(default=None, description="ZERO_RATED | STANDARD | EXEMPT")


class ItemCreate(ItemBase):
    """Create item request with 3-tier units"""
    company_id: UUID
    units: List[ItemUnitCreate] = Field(default_factory=list, description="Unit conversions (optional; derived from 3-tier if empty)")

    @model_validator(mode="after")
    def validate_break_bulk_pack_size(self):
        if self.can_break_bulk and self.pack_size < 2:
            raise ValueError("Breakable items must have pack_size > 1 (e.g. 30 tablets per packet)")
        return self


class ItemsBulkCreate(BaseModel):
    """Bulk create items request"""
    company_id: UUID
    items: List[ItemCreate] = Field(..., min_items=1, max_items=1000, description="Items to create (max 1000 per batch)")


class ItemUpdate(BaseModel):
    """Update item request"""
    name: Optional[str] = None
    generic_name: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    base_unit: Optional[str] = None
    default_cost: Optional[float] = Field(None, ge=0)
    is_vatable: Optional[bool] = None
    vat_rate: Optional[float] = Field(None, ge=0, le=100)
    vat_code: Optional[str] = None
    price_includes_vat: Optional[bool] = None
    vat_category: Optional[str] = None
    is_active: Optional[bool] = None
    supplier_unit: Optional[str] = None
    wholesale_unit: Optional[str] = None
    retail_unit: Optional[str] = None
    pack_size: Optional[int] = Field(None, ge=1)
    wholesale_units_per_supplier: Optional[float] = Field(None, ge=0.0001)
    can_break_bulk: Optional[bool] = None
    purchase_price_per_supplier_unit: Optional[float] = Field(None, ge=0)
    wholesale_price_per_wholesale_unit: Optional[float] = Field(None, ge=0)
    retail_price_per_retail_unit: Optional[float] = Field(None, ge=0)
    units: Optional[List[ItemUnitUpdate]] = Field(None, description="Unit conversions (optional, only if modifying units)")


def _is_numeric_unit_value(value) -> bool:
    """True if value looks like a number (e.g. price mistaken for unit name)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return False
    try:
        float(str(value).strip())
        return True
    except (ValueError, TypeError):
        return False


class ItemResponse(ItemBase):
    """Item response with 3-tier unit fields"""
    id: UUID
    company_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    units: List[ItemUnitResponse] = []
    requires_batch_tracking: Optional[bool] = None
    requires_expiry_tracking: Optional[bool] = None

    @model_validator(mode="after")
    def coerce_numeric_base_unit_for_display(self):
        """Never expose a number as base_unit to the UI; use wholesale_unit (or piece) instead."""
        if self.base_unit and _is_numeric_unit_value(self.base_unit):
            self.base_unit = (self.wholesale_unit or "piece").lower()
        return self

    class Config:
        from_attributes = True


class ItemPricingBase(BaseModel):
    """Item pricing base schema with 3-tier pricing support"""
    markup_percent: Optional[float] = Field(None, ge=0, description="Markup percentage (legacy, for backward compatibility)")
    min_margin_percent: Optional[float] = Field(None, ge=0, description="Minimum margin percentage")
    rounding_rule: Optional[str] = Field(None, description="Rounding rule (nearest_1, nearest_5, nearest_10)")
    
    # 3-Tier Pricing System
    # Tier 1: Supplier/Wholesale Purchase Price
    supplier_unit: Optional[str] = Field(None, description="Unit for supplier price (e.g., piece, box, carton)")
    supplier_price_per_unit: Optional[float] = Field(None, ge=0, description="Purchase price per supplier_unit")
    
    # Tier 2: Wholesale Sale Price
    wholesale_unit: Optional[str] = Field(None, description="Unit for wholesale price (e.g., piece, box, carton)")
    wholesale_price_per_unit: Optional[float] = Field(None, ge=0, description="Wholesale sale price per wholesale_unit")
    
    # Tier 3: Retail Sale Price
    retail_unit: Optional[str] = Field(None, description="Unit for retail price (e.g., piece, box, carton)")
    retail_price_per_unit: Optional[float] = Field(None, ge=0, description="Retail sale price per retail_unit")
    online_store_price_per_unit: Optional[float] = Field(None, ge=0, description="Online store price per retail_unit (optional)")


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


class ItemOverviewResponse(ItemResponse):
    """Item with overview data (stock, supplier, cost)"""
    current_stock: Optional[float] = Field(default=None, description="Current stock in base units (aggregated from ledger)")
    last_supplier: Optional[str] = Field(default=None, description="Name of last supplier from purchase transactions")
    last_unit_cost: Optional[float] = Field(default=None, description="Last unit cost from purchase transactions")
    has_transactions: bool = Field(default=False, description="Whether item has any inventory_ledger records (locks structural fields)")
    minimum_stock: Optional[float] = Field(default=None, description="Minimum stock level (if configured)")

