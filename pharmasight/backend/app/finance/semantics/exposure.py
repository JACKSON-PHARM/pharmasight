"""
Derived economic exposure state (E6.5) — from events + settlement links only.

Never persisted. Never authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.doctrine.economic_position import (
    ACCRUAL_EVENT_TYPES,
    EXPOSURE_STATE_DISPUTED,
    EXPOSURE_STATE_EXHAUSTED_CLAIM,
    EXPOSURE_STATE_FULLY_SETTLED,
    EXPOSURE_STATE_NO_ACCRUAL,
    EXPOSURE_STATE_OPEN,
    EXPOSURE_STATE_PARTIALLY_SETTLED,
    EXPOSURE_STATE_REVERSED,
    EXPOSURE_STATE_STALE,
)
from app.finance.events.settlement import fetch_settlement_links_for_event
from app.models.financial_event import FinancialEvent

STALE_EXPOSURE_DAYS = 365


@dataclass(frozen=True)
class DerivedExposureState:
    state: str
    accrual_event_id: UUID
    accrual_event_type: str
    accrual_amount: str
    settled_amount: str
    remaining_exposure: str
    settlement_link_count: int
    authoritative: bool
    derived_at: str
    source_entity_type: str
    source_entity_id: UUID
    disclaimer: str


def derive_exposure_for_accrual_event(
    db: Session,
    *,
    company_id: UUID,
    accrual_event_id: UUID,
    as_of: Optional[datetime] = None,
) -> DerivedExposureState:
    now = as_of or datetime.now(timezone.utc)
    accrual = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.id == accrual_event_id, FinancialEvent.company_id == company_id)
        .first()
    )
    if not accrual:
        return DerivedExposureState(
            state=EXPOSURE_STATE_NO_ACCRUAL,
            accrual_event_id=accrual_event_id,
            accrual_event_type="",
            accrual_amount="0",
            settled_amount="0",
            remaining_exposure="0",
            settlement_link_count=0,
            authoritative=False,
            derived_at=now.isoformat(),
            source_entity_type="",
            source_entity_id=accrual_event_id,
            disclaimer="No accrual lineage event found.",
        )

    if accrual.event_type not in ACCRUAL_EVENT_TYPES:
        return DerivedExposureState(
            state=EXPOSURE_STATE_NO_ACCRUAL,
            accrual_event_id=accrual_event_id,
            accrual_event_type=accrual.event_type,
            accrual_amount=str(accrual.amount),
            settled_amount="0",
            remaining_exposure=str(accrual.amount),
            settlement_link_count=0,
            authoritative=False,
            derived_at=now.isoformat(),
            source_entity_type=accrual.source_entity_type,
            source_entity_id=accrual.source_entity_id,
            disclaimer="Event is not an accrual-type economic recognition.",
        )

    reversed = (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.reversal_of_event_id == accrual.id,
        )
        .first()
    )
    if reversed:
        return DerivedExposureState(
            state=EXPOSURE_STATE_REVERSED,
            accrual_event_id=accrual.id,
            accrual_event_type=accrual.event_type,
            accrual_amount=str(accrual.amount),
            settled_amount="0",
            remaining_exposure="0",
            settlement_link_count=0,
            authoritative=False,
            derived_at=now.isoformat(),
            source_entity_type=accrual.source_entity_type,
            source_entity_id=accrual.source_entity_id,
            disclaimer="Compensating reversal exists — exposure closed in lineage.",
        )

    payload = accrual.payload_json or {}
    if payload.get("disputed") or payload.get("claim_status") == "disputed":
        state_hint = EXPOSURE_STATE_DISPUTED
    else:
        state_hint = None

    links = fetch_settlement_links_for_event(db, company_id=company_id, event_id=accrual.id)
    settled_by = links.get("settled_by") or []
    settled_total = sum(Decimal(str(l.amount_settled or 0)) for l in settled_by)
    accrual_amt = Decimal(str(accrual.amount or 0))
    remaining = max(accrual_amt - settled_total, Decimal("0"))

    if settled_total <= 0:
        state = state_hint or EXPOSURE_STATE_OPEN
    elif remaining <= Decimal("0.0001"):
        state = (
            EXPOSURE_STATE_EXHAUSTED_CLAIM
            if accrual.event_type == "insurance_claim_recognized"
            else EXPOSURE_STATE_FULLY_SETTLED
        )
    else:
        state = state_hint or EXPOSURE_STATE_PARTIALLY_SETTLED

    occurred = accrual.occurred_at
    if occurred and occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    if occurred and (now - occurred) > timedelta(days=STALE_EXPOSURE_DAYS) and state == EXPOSURE_STATE_OPEN:
        state = EXPOSURE_STATE_STALE

    return DerivedExposureState(
        state=state,
        accrual_event_id=accrual.id,
        accrual_event_type=accrual.event_type,
        accrual_amount=str(accrual_amt),
        settled_amount=str(settled_total),
        remaining_exposure=str(remaining),
        settlement_link_count=len(settled_by),
        authoritative=False,
        derived_at=now.isoformat(),
        source_entity_type=accrual.source_entity_type,
        source_entity_id=accrual.source_entity_id,
        disclaimer=(
            "Derived exposure from immutable lineage — not stored, not a ledger balance. "
            "Operational invoice/payment/claim records remain authoritative."
        ),
    )
