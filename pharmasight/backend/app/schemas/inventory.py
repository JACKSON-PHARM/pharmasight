"""
Inventory schemas
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal


class InventoryLedgerBase(BaseModel):
    """Inventory ledger base schema"""
    company_id: UUID
    branch_id: UUID
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    transaction_type: str = Field(..., description="PURCHASE, SALE, ADJUSTMENT, TRANSFER, OPENING_BALANCE")
    reference_type: Optional[str] = None
    reference_id: Optional[UUID] = None
    quantity_delta: int = Field(..., description="Positive = add stock, Negative = remove stock (BASE UNITS)")
    unit_cost: Decimal = Field(..., ge=0, description="Cost per base unit")
    total_cost: Decimal = Field(..., ge=0)
    # Enhanced batch tracking fields
    batch_cost: Optional[Decimal] = None
    remaining_quantity: Optional[int] = None
    is_batch_tracked: Optional[bool] = True
    parent_batch_id: Optional[UUID] = None
    split_sequence: Optional[int] = 0


class InventoryLedgerCreate(InventoryLedgerBase):
    """Create inventory ledger entry"""
    created_by: UUID


class InventoryLedgerResponse(InventoryLedgerBase):
    """Inventory ledger response"""
    id: UUID
    created_by: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class StockBalance(BaseModel):
    """Current stock balance"""
    item_id: UUID
    item_name: str
    branch_id: UUID
    branch_name: str
    base_unit: str
    total_quantity: int = Field(..., description="Total stock in base units")
    batches: List["BatchStock"] = Field(default_factory=list)


class BatchStock(BaseModel):
    """Stock by batch"""
    batch_number: Optional[str]
    expiry_date: Optional[date]
    quantity: int = Field(..., description="Stock in base units")
    unit_cost: Decimal
    total_cost: Decimal


class StockAvailability(BaseModel):
    """Stock availability for sale"""
    item_id: UUID
    item_name: str
    base_unit: str
    total_base_units: int
    unit_breakdown: List["UnitBreakdown"] = Field(default_factory=list)
    batch_breakdown: List[BatchStock] = Field(default_factory=list)


class UnitBreakdown(BaseModel):
    """Stock breakdown by unit"""
    unit_name: str
    multiplier: float
    whole_units: int
    remainder_base_units: int
    display: str = Field(..., description="e.g., '8 boxes + 40 tablets'")


# Update forward references
StockBalance.model_rebuild()
StockAvailability.model_rebuild()

