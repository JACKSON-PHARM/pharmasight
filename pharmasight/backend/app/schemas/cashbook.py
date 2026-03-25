"""
Cashbook schemas (money movement tracking).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class CashbookEntryResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    date: date
    type: str  # inflow | outflow
    amount: Decimal
    payment_mode: str  # cash | mpesa | bank
    source_type: str  # expense | supplier_payment | sale
    source_id: UUID
    reference_number: Optional[str] = None
    description: Optional[str] = None
    created_by: UUID

    class Config:
        from_attributes = True


class CashbookDailyRow(BaseModel):
    date: date
    total_inflow: Decimal = Decimal("0")
    total_outflow: Decimal = Decimal("0")
    net_cashflow: Decimal = Decimal("0")


class CashbookSummaryResponse(BaseModel):
    branch_id: Optional[UUID] = None
    start_date: date
    end_date: date
    total_inflow: Decimal = Decimal("0")
    total_outflow: Decimal = Decimal("0")
    net_cashflow: Decimal = Decimal("0")
    breakdown: List[CashbookDailyRow] = []

