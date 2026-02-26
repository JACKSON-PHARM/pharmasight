"""
Report response schemas (read-only).
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ItemMovementDisplayOptions(BaseModel):
    """Column visibility for item movement report (from company report_settings.item_movement)."""
    show_batch_number: bool = False
    show_expiry_date: bool = False


class ItemMovementRow(BaseModel):
    """Single row in item movement report (synthetic opening row or ledger row)."""
    date: datetime
    document_type: str
    reference: str = ""
    qty_in: Decimal = Field(default=Decimal("0"), description="Quantity in (positive movement)")
    qty_out: Decimal = Field(default=Decimal("0"), description="Quantity out (absolute value of negative)")
    running_balance: Decimal
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None


class ItemMovementReportResponse(BaseModel):
    """Response for GET /api/reports/item-movement and GET /api/reports/batch-movement."""
    company_name: str
    branch_name: str
    item_name: str
    item_sku: Optional[str] = None
    start_date: date
    end_date: date
    display_options: ItemMovementDisplayOptions
    opening_balance: Decimal
    closing_balance: Decimal
    rows: List[ItemMovementRow] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ItemBatchInfo(BaseModel):
    """Single batch for GET /api/items/{item_id}/batches (dropdown)."""
    batch_no: str
    expiry_date: Optional[date] = None
    current_balance: Decimal = Field(default=Decimal("0"), description="Running balance from movements")


class ItemBatchesResponse(BaseModel):
    """Response for GET /api/items/{item_id}/batches."""
    batches: List[ItemBatchInfo] = Field(default_factory=list)
