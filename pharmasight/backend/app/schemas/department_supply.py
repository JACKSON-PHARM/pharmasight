from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DepartmentSupplyOrderLineIn(BaseModel):
    item_id: UUID
    unit_name: str
    quantity: Decimal = Field(..., gt=0)


class DepartmentSupplyOrderCreate(BaseModel):
    department_store_id: UUID
    notes: Optional[str] = None
    lines: List[DepartmentSupplyOrderLineIn] = Field(..., min_length=1)


class DepartmentSupplyOrderLineResponse(BaseModel):
    id: UUID
    department_supply_order_id: UUID
    item_id: UUID
    unit_name: str
    quantity: Decimal
    fulfilled_qty: Decimal
    created_at: Optional[datetime] = None
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class DepartmentSupplyOrderResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    department_store_id: UUID
    order_number: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_by: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    lines: List[DepartmentSupplyOrderLineResponse] = Field(default_factory=list)
    department_store_name: Optional[str] = None
    department_store_code: Optional[str] = None

    class Config:
        from_attributes = True


class DepartmentSupplyTransferFromOrder(BaseModel):
    """Create a draft transfer from an OPEN department supply order (pharmacy workstation)."""

    department_supply_order_id: UUID


class DepartmentSupplyTransferLineResponse(BaseModel):
    id: UUID
    department_supply_transfer_id: UUID
    department_supply_order_line_id: Optional[UUID] = None
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    unit_name: str
    quantity: Decimal
    unit_cost: Decimal
    created_at: Optional[datetime] = None
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class DepartmentSupplyTransferResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    department_store_id: UUID
    department_supply_order_id: Optional[UUID] = None
    transfer_number: Optional[str] = None
    status: str
    created_by: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    lines: List[DepartmentSupplyTransferLineResponse] = Field(default_factory=list)
    department_store_name: Optional[str] = None

    class Config:
        from_attributes = True


class DepartmentSupplyReceiptLineResponse(BaseModel):
    id: UUID
    department_supply_receipt_id: UUID
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: Decimal
    unit_cost: Decimal
    created_at: Optional[datetime] = None
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class DepartmentSupplyReceiptResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    department_store_id: UUID
    department_supply_transfer_id: UUID
    receipt_number: Optional[str] = None
    status: str
    received_at: Optional[datetime] = None
    received_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    lines: List[DepartmentSupplyReceiptLineResponse] = Field(default_factory=list)
    department_store_name: Optional[str] = None
    transfer_number: Optional[str] = None

    class Config:
        from_attributes = True
