"""Schemas for E5 treasury and projections."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CashbookAccountResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: Optional[UUID] = None
    account_code: str
    name: str
    routing_type: str
    payment_mode: Optional[str] = None
    classification: str
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CashbookAccountCreate(BaseModel):
    branch_id: Optional[UUID] = None
    account_code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    routing_type: str
    payment_mode: Optional[str] = None
    classification: str = "branch_finance"
    notes: Optional[str] = None


class TreasuryProvisionResponse(BaseModel):
    created_count: int
    accounts: List[CashbookAccountResponse]


class BackfillRunRequest(BaseModel):
    branch_id: UUID
    date_from: date
    date_to: date


class BackfillRunResponse(BaseModel):
    run_id: UUID
    status: str
    events_created: int
    events_duplicate: int
    events_failed: int
    correlation_group: Optional[str] = None
    policy_pack_id: Optional[str] = None


class ProjectionExecuteResponse(BaseModel):
    projection_id: str
    derived: bool
    authoritative: bool
    data: Dict[str, Any]
