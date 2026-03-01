"""
Item schemas for request/response validation.
3-tier UNIT system: supplier_unit (what we buy), wholesale_unit (what pharmacies buy),
retail_unit (what customers buy), pack_size (retail units per packet).
"""
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID


class ItemSearchDTO(BaseModel):
    """
    Lightweight DTO for POS-level item search. No joins, no pricing/cost logic.
    selling_price and total_stock are precomputed or 0 when using fast path without cache table.
    """
    id: UUID
    name: str
    strength: Optional[str] = None
    pack_size: int = 1
    selling_price: float = 0.0
    total_stock: float = 0.0
    # Optional fields from same row for backward compatibility (no extra query)
    base_unit: Optional[str] = None
    sku: Optional[str] = None
    vat_rate: Optional[float] = None
    vat_category: Optional[str] = None
    current_stock: Optional[float] = None  # alias for total_stock when branch scoped
    stock_display: Optional[str] = None


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
    """Item base schema with 3-tier UNIT system. Cost/price from inventory_ledger only."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Item description")
    sku: Optional[str] = Field(None, description="Item code (SKU)")
    barcode: Optional[str] = None
    category: Optional[str] = None
    product_category: Optional[str] = Field(None, description="PHARMACEUTICAL | COSMETICS | EQUIPMENT | SERVICE")
    pricing_tier: Optional[str] = Field(None, description="Margin tier: CHRONIC_MEDICATION, STANDARD, BEAUTY_COSMETICS, etc.")
    base_unit: Optional[str] = Field(None, description="Legacy: base unit = wholesale_unit")
    # 3-tier units
    supplier_unit: str = Field(default="packet", description="Supplier unit name")
    wholesale_unit: str = Field(default="packet", description="Wholesale unit name (base)")
    retail_unit: str = Field(default="tablet", description="Retail unit name")
    pack_size: int = Field(default=1, ge=1, description="Wholesale-to-retail: 1 wholesale = pack_size retail")
    wholesale_units_per_supplier: float = Field(default=1, ge=1, description="Wholesale-to-supplier: 1 supplier = N wholesale (integer, e.g. 12)")
    can_break_bulk: bool = Field(default=False, description="Can sell individual retail units? (requires pack_size > 1)")
    # VAT
    vat_category: str = Field(default="ZERO_RATED", description="ZERO_RATED | STANDARD_RATED")
    vat_rate: float = Field(default=0, ge=0, le=100, description="0 or 16")
    # Tracking flags
    track_expiry: bool = Field(default=False, description="Whether item requires expiry date tracking")
    is_controlled: bool = Field(default=False, description="Whether item is a controlled substance")
    is_cold_chain: bool = Field(default=False, description="Whether item requires cold chain storage")


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
    description: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    product_category: Optional[str] = None
    pricing_tier: Optional[str] = None
    base_unit: Optional[str] = None
    vat_rate: Optional[float] = Field(None, ge=0, le=100)
    vat_category: Optional[str] = None
    is_active: Optional[bool] = None
    supplier_unit: Optional[str] = None
    wholesale_unit: Optional[str] = None
    retail_unit: Optional[str] = None
    pack_size: Optional[int] = Field(None, ge=1)
    wholesale_units_per_supplier: Optional[float] = Field(None, ge=1, description="Integer, e.g. 12 packs per carton")
    can_break_bulk: Optional[bool] = None
    track_expiry: Optional[bool] = None
    is_controlled: Optional[bool] = None
    is_cold_chain: Optional[bool] = None
    units: Optional[List[ItemUnitUpdate]] = Field(None, description="Unit conversions (optional, only if modifying units)")
    floor_price_retail: Optional[float] = Field(None, ge=0, description="Minimum allowed selling price (retail)")
    promo_price_retail: Optional[float] = Field(None, ge=0, description="Temporary promo price (retail)")
    promo_start_date: Optional[date] = Field(None, description="Promo start date (YYYY-MM-DD)")
    promo_end_date: Optional[date] = Field(None, description="Promo end date (YYYY-MM-DD)")


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
    """Item response with 3-tier unit fields. Cost from API (inventory_ledger) only."""
    id: UUID
    company_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    units: List[ItemUnitResponse] = []
    default_cost: Optional[float] = Field(None, description="Cost per wholesale unit from ledger (API only)")
    default_cost_per_base: Optional[float] = Field(None, description="Fallback cost per base unit when no ledger data")
    default_supplier_id: Optional[UUID] = Field(None, description="Fallback supplier ID when no purchase history")
    stock_display: Optional[str] = Field(None, description="3-tier stock string when branch_id provided (e.g. '2 packet (200 tablet)')")
    current_stock: Optional[float] = Field(None, description="Current stock in base units when branch_id provided (backward compat)")
    base_quantity: Optional[float] = Field(None, description="Numeric stock in retail/base units. Use retail_unit for labeling.")
    has_transactions: Optional[bool] = Field(False, description="True if item has sales, purchases, or non–opening-balance ledger (locks unit fields)")
    floor_price_retail: Optional[float] = Field(None, description="Minimum allowed selling price (retail)")
    promo_price_retail: Optional[float] = Field(None, description="Temporary promo price (retail)")
    promo_start_date: Optional[date] = Field(None, description="Promo start date")
    promo_end_date: Optional[date] = Field(None, description="Promo end date")

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
    """Company pricing defaults base schema (recommended markup 30%, minimum margin 15%)"""
    default_markup_percent: float = Field(default=30.00, ge=0)
    rounding_rule: str = Field(default="nearest_1")
    min_margin_percent: float = Field(default=15.00, ge=0)


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
    has_transactions: bool = Field(default=False, description="Whether item has sales, purchases, or non–opening-balance ledger (locks unit fields)")
    minimum_stock: Optional[float] = Field(default=None, description="Minimum stock level (if configured)")


class AdjustStockRequest(BaseModel):
    """Request body for manual stock adjustment (add or reduce). Always applies a delta; never overwrites."""
    branch_id: UUID = Field(..., description="Branch where stock is adjusted")
    user_id: UUID = Field(..., description="User performing the adjustment (must be ADMIN, Pharmacist, or Auditor)")
    unit_name: str = Field(..., min_length=1, description="Unit to use (e.g. box, tablet, piece - one of item's 3-tier units)")
    quantity: float = Field(..., gt=0, description="Quantity in the selected unit (always positive)")
    direction: str = Field(..., description="'add' or 'reduce'")
    unit_cost: Optional[float] = Field(None, ge=0, description="Cost per base unit; default = last purchase cost")
    batch_number: Optional[str] = Field(None, max_length=200, description="Batch/lot number (required when direction=add)")
    expiry_date: Optional[str] = Field(None, description="Expiry date YYYY-MM-DD (required when direction=add)")
    notes: Optional[str] = Field(None, max_length=2000, description="Comments or details (e.g. source, reason)")

    @model_validator(mode="after")
    def validate_direction_and_batch_expiry(self):
        if self.direction.lower() not in ("add", "reduce"):
            raise ValueError("direction must be 'add' or 'reduce'")
        if self.direction.lower() == "add":
            if not (self.batch_number and self.batch_number.strip()):
                raise ValueError("Batch number is required when adding stock.")
            if not (self.expiry_date and self.expiry_date.strip()):
                raise ValueError("Expiry date is required when adding stock.")
        return self


class AdjustStockResponse(BaseModel):
    """Response after stock adjustment. Confirms delta was applied (previous + delta = new)."""
    success: bool = True
    message: str = Field(..., description="Success message")
    item_id: UUID = Field(..., description="Item that was adjusted")
    branch_id: UUID = Field(..., description="Branch where stock was adjusted")
    quantity_delta: float = Field(..., description="Change in base units (positive = add, negative = reduce)")
    previous_stock: float = Field(..., description="Stock in base units before this adjustment")
    new_stock: float = Field(..., description="New total stock in base units after adjustment")
    new_stock_display: Optional[str] = Field(None, description="New stock in 3-tier form e.g. '1 packet + 1 sachet'")
    base_quantity: Optional[float] = Field(None, description="Numeric stock in retail units (same as new_stock)")
    retail_unit: Optional[str] = Field(None, description="Retail unit name for labeling base_quantity")


# --- Inventory corrections (audit trail, no mutation of sales/FEFO) ---

class CostAdjustmentRequest(BaseModel):
    """Cost adjustment: change batch unit cost (valuation only). Quantity unchanged."""
    branch_id: UUID = Field(..., description="Branch that owns the batch")
    batch_id: UUID = Field(..., description="InventoryLedger row id (specific batch)")
    new_unit_cost: float = Field(..., ge=0, description="New cost per base unit")
    reason: str = Field(..., min_length=1, description="Mandatory reason (audited)")


class BatchQuantityCorrectionRequest(BaseModel):
    """Quantity correction: align ledger to physical count for a batch. Forward correction only."""
    branch_id: UUID = Field(..., description="Branch that owns the batch")
    batch_number: str = Field(..., min_length=1, description="Batch/lot number")
    expiry_date: Optional[str] = Field(None, description="Expiry date YYYY-MM-DD (required if item tracks expiry)")
    physical_count: float = Field(..., description="Physical count in base units")
    reason: str = Field(..., min_length=1, description="Mandatory reason (audited)")


class BatchMetadataCorrectionRequest(BaseModel):
    """Metadata correction: fix batch_number or expiry_date for a batch."""
    branch_id: UUID = Field(..., description="Branch that owns the batch")
    batch_number: str = Field(..., min_length=1, description="Current batch/lot number")
    expiry_date: Optional[str] = Field(None, description="Current expiry YYYY-MM-DD")
    new_batch_number: Optional[str] = Field(None, max_length=200, description="New batch number (if correcting)")
    new_expiry_date: Optional[str] = Field(None, description="New expiry YYYY-MM-DD (if correcting)")
    reason: str = Field(..., min_length=1, description="Mandatory reason (audited)")


class CorrectionResponse(BaseModel):
    """Response after a correction. Returns success and updated batch snapshot."""
    success: bool = True
    message: str = Field(..., description="Success message")
    movement_id: UUID = Field(..., description="ItemMovement audit record id")
    item_id: UUID = Field(..., description="Item")
    branch_id: UUID = Field(..., description="Branch")


class LedgerBatchEntry(BaseModel):
    """Single ledger row with positive quantity (for cost-adjustment batch selection)."""
    ledger_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    unit_cost: float = 0
    quantity: float = Field(..., description="Quantity (balance) for this row")


class LedgerBatchesResponse(BaseModel):
    """Response for GET /api/items/{item_id}/ledger-batches (cost adjustment dropdown)."""
    entries: List[LedgerBatchEntry] = Field(default_factory=list)

