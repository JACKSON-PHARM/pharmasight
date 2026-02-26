"""
Branch Inventory Pydantic schemas.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


# ----- Branch Order -----
class BranchOrderLineBase(BaseModel):
    item_id: UUID
    unit_name: str
    quantity: Decimal = Field(..., gt=0)


class BranchOrderLineCreate(BranchOrderLineBase):
    pass


class BranchOrderLineResponse(BranchOrderLineBase):
    id: UUID
    branch_order_id: UUID
    fulfilled_qty: Decimal = Field(default=Decimal("0"))
    created_at: Optional[datetime] = None
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class BranchOrderCreate(BaseModel):
    ordering_branch_id: UUID
    supplying_branch_id: UUID
    lines: List[BranchOrderLineCreate]


class BranchOrderUpdate(BaseModel):
    lines: Optional[List[BranchOrderLineCreate]] = None


class BranchOrderResponse(BaseModel):
    id: UUID
    company_id: UUID
    ordering_branch_id: UUID
    supplying_branch_id: UUID
    order_number: Optional[str] = None
    status: str
    created_by: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    lines: List[BranchOrderLineResponse] = Field(default_factory=list)
    ordering_branch_name: Optional[str] = None
    supplying_branch_name: Optional[str] = None

    class Config:
        from_attributes = True


# ----- Branch Transfer -----
class BranchTransferLineBase(BaseModel):
    branch_order_line_id: Optional[UUID] = None
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    unit_name: str
    quantity: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0)


class BranchTransferLineCreate(BranchTransferLineBase):
    pass


class BranchTransferLineResponse(BranchTransferLineBase):
    id: UUID
    branch_transfer_id: UUID
    created_at: Optional[datetime] = None
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class BranchTransferCreate(BaseModel):
    supplying_branch_id: UUID
    receiving_branch_id: UUID
    branch_order_id: Optional[UUID] = None
    lines: List[BranchTransferLineCreate]


class BranchTransferResponse(BaseModel):
    id: UUID
    company_id: UUID
    supplying_branch_id: UUID
    receiving_branch_id: UUID
    branch_order_id: Optional[UUID] = None
    transfer_number: Optional[str] = None
    status: str
    created_by: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    lines: List[BranchTransferLineResponse] = Field(default_factory=list)
    supplying_branch_name: Optional[str] = None
    receiving_branch_name: Optional[str] = None

    class Config:
        from_attributes = True


# ----- Branch Receipt -----
class BranchReceiptLineResponse(BaseModel):
    id: UUID
    branch_receipt_id: UUID
    item_id: UUID
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: Decimal
    unit_cost: Decimal
    created_at: Optional[datetime] = None
    item_name: Optional[str] = None

    class Config:
        from_attributes = True


class BranchReceiptResponse(BaseModel):
    id: UUID
    company_id: UUID
    receiving_branch_id: UUID
    branch_transfer_id: UUID
    receipt_number: Optional[str] = None
    status: str
    received_at: Optional[datetime] = None
    received_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    lines: List[BranchReceiptLineResponse] = Field(default_factory=list)
    receiving_branch_name: Optional[str] = None

    class Config:
        from_attributes = True
