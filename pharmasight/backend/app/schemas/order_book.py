"""
Order Book Pydantic schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from decimal import Decimal
from datetime import datetime, date


class OrderBookEntryBase(BaseModel):
    """Base schema for order book entries"""
    item_id: UUID
    supplier_id: Optional[UUID] = None
    quantity_needed: Decimal = Field(..., gt=0, description="Quantity needed in base units")
    unit_name: str
    reason: str = Field(..., description="AUTO_THRESHOLD, MANUAL_SALE, MANUAL_QUOTATION, MANUAL_ADD")
    source_reference_type: Optional[str] = None
    source_reference_id: Optional[UUID] = None
    notes: Optional[str] = None
    priority: int = Field(default=5, ge=1, le=10, description="Priority 1-10, higher = more urgent")


class OrderBookEntryCreate(OrderBookEntryBase):
    """Schema for creating a new order book entry"""
    entry_date: Optional[date] = Field(None, description="Date for this entry (default: today); items unique per date")


class OrderBookEntryResponse(OrderBookEntryBase):
    """Schema for order book entry response"""
    id: UUID
    company_id: UUID
    branch_id: UUID
    entry_date: Optional[date] = None
    status: str
    purchase_order_id: Optional[UUID] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    
    # Related data
    item_name: Optional[str] = None
    item_sku: Optional[str] = None
    supplier_name: Optional[str] = None
    current_stock: Optional[int] = None  # Current stock at branch
    
    class Config:
        from_attributes = True


class OrderBookEntryUpdate(BaseModel):
    """Schema for updating an order book entry"""
    quantity_needed: Optional[Decimal] = Field(None, gt=0)
    supplier_id: Optional[UUID] = None
    priority: Optional[int] = Field(None, ge=1, le=10)
    notes: Optional[str] = None


class OrderBookBulkCreate(BaseModel):
    """Schema for bulk creating order book entries from selected items"""
    item_ids: list[UUID] = Field(..., min_items=1)
    entry_date: Optional[date] = None  # Default: today; items unique per (branch, item, entry_date)
    supplier_id: Optional[UUID] = None
    reason: str = Field(default="MANUAL_ADD", description="Reason for bulk addition")
    notes: Optional[str] = None


class OrderBookBulkCreateResponse(BaseModel):
    """Response for bulk create: created entries and items skipped (already in order book)."""
    entries: list[OrderBookEntryResponse] = Field(default_factory=list)
    skipped_item_ids: list[UUID] = Field(default_factory=list, description="Item IDs already in order book")
    skipped_item_names: list[str] = Field(default_factory=list, description="Item names for display when skipped")


class CreatePurchaseOrderFromBook(BaseModel):
    """Schema for creating a purchase order from selected order book entries"""
    entry_ids: list[UUID] = Field(..., min_items=1, description="Order book entry IDs to convert")
    supplier_id: UUID
    order_date: str  # ISO date string
    reference: Optional[str] = None
    notes: Optional[str] = None


class AutoGenerateRequest(BaseModel):
    """Schema for auto-generating order book entries"""
    branch_id: UUID
    company_id: UUID


class OrderBookHistoryResponse(BaseModel):
    """Schema for order book history entry"""
    id: UUID
    company_id: UUID
    branch_id: UUID
    item_id: UUID
    supplier_id: Optional[UUID] = None
    quantity_needed: Decimal
    unit_name: str
    reason: str
    source_reference_type: Optional[str] = None
    source_reference_id: Optional[UUID] = None
    notes: Optional[str] = None
    priority: int
    status: str
    purchase_order_id: Optional[UUID] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime
    
    # Related data
    item_name: Optional[str] = None
    item_sku: Optional[str] = None
    supplier_name: Optional[str] = None
    
    class Config:
        from_attributes = True
