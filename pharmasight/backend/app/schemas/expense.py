"""
Expense engine schemas (OPEX only; no stock/supplier linkage).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class ExpenseCategoryBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = True


class ExpenseCategoryCreate(ExpenseCategoryBase):
    company_id: UUID


class ExpenseCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ExpenseCategoryResponse(ExpenseCategoryBase):
    id: UUID
    company_id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExpenseBase(BaseModel):
    branch_id: UUID
    category_id: UUID
    description: str
    amount: Decimal
    expense_date: date
    payment_mode: str = Field(..., description="cash | mpesa | bank")
    reference_number: Optional[str] = None
    attachment_url: Optional[str] = None


class ExpenseCreate(ExpenseBase):
    company_id: UUID


class ExpenseUpdate(BaseModel):
    category_id: Optional[UUID] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    expense_date: Optional[date] = None
    payment_mode: Optional[str] = None
    reference_number: Optional[str] = None
    attachment_url: Optional[str] = None


class ExpenseResponse(ExpenseBase):
    id: UUID
    company_id: UUID
    status: str
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    created_by: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    category_name: Optional[str] = None

    class Config:
        from_attributes = True


class ExpenseDailyRow(BaseModel):
    date: date
    total_expenses: Decimal


class ExpenseSummaryResponse(BaseModel):
    branch_id: Optional[UUID] = None
    start_date: date
    end_date: date
    total_expenses: Decimal
    breakdown: List[ExpenseDailyRow] = []

