"""Schemas for E7 journal proposals."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class JournalProposalLineResponse(BaseModel):
    id: UUID
    line_order: int
    account_semantic: str
    line_direction: str
    amount: Decimal
    description: Optional[str] = None

    class Config:
        from_attributes = True


class JournalProposalEvidenceResponse(BaseModel):
    financial_event_id: UUID
    link_semantic: str

    class Config:
        from_attributes = True


class JournalProposalResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    proposal_number: str
    status: str
    policy_pack_id: str
    source_financial_event_id: UUID
    reversal_of_proposal_id: Optional[UUID] = None
    commercial_transaction_id: Optional[UUID] = None
    currency_code: str
    total_amount: Decimal
    occurred_at: datetime
    authoritative: bool = False
    derived: bool = True
    lines: List[JournalProposalLineResponse] = []
    evidence: List[JournalProposalEvidenceResponse] = []
    created_at: datetime
    approved_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GenerateProposalRequest(BaseModel):
    financial_event_id: UUID
    policy_pack_id: str = "STANDARD_KENYA"


class ProposalActionResponse(BaseModel):
    success: bool
    message: str
    proposal_id: UUID


class PostingEligibilityResponse(BaseModel):
    eligible: bool
    reasons: List[str]
    commercial_state: Optional[str] = None
    requires_permission: str
