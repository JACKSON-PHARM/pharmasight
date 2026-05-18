"""Schemas for financial_events API (E3/E4)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FinancialEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    branch_id: UUID
    operational_domain: str
    event_type: str
    classification: str
    event_schema_version: int
    occurred_at: datetime
    emitted_at: datetime
    amount: Decimal
    currency_code: str
    economic_direction: str
    source_entity_type: str
    source_entity_id: UUID
    source_reference: Optional[str] = None
    idempotency_key: str
    reversal_of_event_id: Optional[UUID] = None
    caused_by_event_id: Optional[UUID] = None
    payload_json: dict[str, Any]
    governance_metadata_json: dict[str, Any]
    operational_status: str = "emitted"
    emission_channel: str = "original"
    correlation_group: Optional[str] = None
    replay_source_failure_id: Optional[UUID] = None


class SettlementLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    settlement_event_id: UUID
    settles_event_id: UUID
    amount_settled: Decimal
    settlement_semantic: str
    created_at: datetime


class ReplayLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    replay_result: str
    financial_event_id: Optional[UUID] = None
    actor_user_id: Optional[UUID] = None
    created_at: datetime
    detail_json: dict[str, Any]


class FinancialEventLineageResponse(BaseModel):
    event: FinancialEventResponse
    reversals: List[FinancialEventResponse]
    caused_by: Optional[FinancialEventResponse] = None
    settles: List[FinancialEventResponse] = []
    settlement_links: dict[str, List[SettlementLinkResponse]] = {}
    replay_logs: List[ReplayLogResponse] = []
    correlation_events: List[FinancialEventResponse] = []


class EmissionFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    idempotency_key: str
    source_entity_type: str
    source_entity_id: UUID
    error_message: str
    retry_count: int
    resolved_at: Optional[datetime] = None
    last_replay_at: Optional[datetime] = None
    last_replay_result: Optional[str] = None
    resolved_event_id: Optional[UUID] = None
    created_at: datetime


class IntegrityFindingResponse(BaseModel):
    code: str
    severity: str
    source_entity_type: str
    source_entity_id: UUID
    branch_id: Optional[UUID] = None
    expected_event_type: str
    expected_idempotency_key: str
    message: str


class ReplayOutcomeResponse(BaseModel):
    failure_id: UUID
    result: str
    financial_event_id: Optional[UUID] = None
    message: str
