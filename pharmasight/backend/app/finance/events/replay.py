"""
Deterministic replay for financial_event_emission_failures (E4).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.doctrine.causal_lineage import sort_failures_for_replay
from app.finance.events.emitter import EmitFinancialEventRequest, EmitResult, emit_financial_event
from app.finance.events.lifecycle import EMISSION_CHANNEL_REPLAY, OPERATIONAL_STATUS_REPLAYED
from app.models.financial_event import FinancialEvent, FinancialEventEmissionFailure, FinancialEventReplayLog

logger = logging.getLogger("pharmasight.finance.events")

FINANCIAL_EVENT_REPLAY_ATTEMPTED = "financial_event_replay_attempted"
FINANCIAL_EVENT_REPLAY_SUCCEEDED = "financial_event_replay_succeeded"


@dataclass(frozen=True)
class ReplayOutcome:
    failure_id: UUID
    result: EmitResult
    financial_event_id: Optional[UUID]
    message: str


def _log_replay(
    db: Session,
    *,
    company_id: UUID,
    failure_id: Optional[UUID],
    idempotency_key: str,
    replay_result: str,
    financial_event_id: Optional[UUID],
    actor_user_id: Optional[UUID],
    detail: dict,
) -> None:
    try:
        db.add(
            FinancialEventReplayLog(
                company_id=company_id,
                failure_id=failure_id,
                idempotency_key=idempotency_key,
                replay_result=replay_result,
                financial_event_id=financial_event_id,
                actor_user_id=actor_user_id,
                detail_json=detail,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("replay log write failed", exc_info=True)


def replay_emission_failure(
    db: Session,
    failure_id: UUID,
    *,
    company_id: UUID,
    actor_user_id: Optional[UUID] = None,
) -> ReplayOutcome:
    """Replay one unresolved failure; preserves idempotency_key and occurred_at."""
    failure = (
        db.query(FinancialEventEmissionFailure)
        .filter(
            FinancialEventEmissionFailure.id == failure_id,
            FinancialEventEmissionFailure.company_id == company_id,
        )
        .first()
    )
    if not failure:
        return ReplayOutcome(failure_id=failure_id, result=EmitResult.FAILED, financial_event_id=None, message="not_found")
    if failure.resolved_at is not None:
        return ReplayOutcome(
            failure_id=failure_id,
            result=EmitResult.DUPLICATE,
            financial_event_id=failure.resolved_event_id,
            message="already_resolved",
        )
    if not failure.branch_id:
        return ReplayOutcome(failure_id=failure_id, result=EmitResult.FAILED, financial_event_id=None, message="missing_branch")

    logger.info(
        '{"event":"%s","failure_id":"%s","company_id":"%s"}',
        FINANCIAL_EVENT_REPLAY_ATTEMPTED,
        failure_id,
        company_id,
    )

    req = EmitFinancialEventRequest(
        event_type=failure.event_type,
        company_id=failure.company_id,
        branch_id=failure.branch_id,
        source_entity_id=failure.source_entity_id,
        occurred_at=failure.occurred_at,
        amount=failure.amount,
        currency_code=failure.currency_code,
        source_reference=failure.source_reference,
        payload=dict(failure.payload_json or {}),
        governance_metadata={
            **dict(failure.governance_metadata_json or {}),
            "replay": True,
            "replay_failure_id": str(failure_id),
        },
        idempotency_key=failure.idempotency_key,
        emission_channel=EMISSION_CHANNEL_REPLAY,
        operational_status=OPERATIONAL_STATUS_REPLAYED,
        replay_source_failure_id=failure_id,
    )

    result, event_id = emit_financial_event(db, req)
    now = datetime.now(timezone.utc)
    failure.last_replay_at = now
    failure.last_replay_result = result.value
    if result in (EmitResult.CREATED, EmitResult.DUPLICATE):
        failure.resolved_at = now
        if event_id:
            failure.resolved_event_id = event_id
        elif result == EmitResult.DUPLICATE:
            existing = (
                db.query(FinancialEvent)
                .filter(
                    FinancialEvent.company_id == company_id,
                    FinancialEvent.idempotency_key == failure.idempotency_key,
                )
                .first()
            )
            if existing:
                failure.resolved_event_id = existing.id
                event_id = existing.id
    try:
        db.commit()
    except Exception:
        db.rollback()

    _log_replay(
        db,
        company_id=company_id,
        failure_id=failure_id,
        idempotency_key=failure.idempotency_key,
        replay_result=result.value,
        financial_event_id=event_id,
        actor_user_id=actor_user_id,
        detail={"message": result.value},
    )

    if result == EmitResult.CREATED:
        logger.info(
            '{"event":"%s","failure_id":"%s","financial_event_id":"%s"}',
            FINANCIAL_EVENT_REPLAY_SUCCEEDED,
            failure_id,
            event_id,
        )

    return ReplayOutcome(
        failure_id=failure_id,
        result=result,
        financial_event_id=event_id,
        message=result.value,
    )


def replay_unresolved_failures(
    db: Session,
    *,
    company_id: UUID,
    actor_user_id: Optional[UUID] = None,
    limit: int = 100,
) -> List[ReplayOutcome]:
    rows = (
        db.query(FinancialEventEmissionFailure)
        .filter(
            FinancialEventEmissionFailure.company_id == company_id,
            FinancialEventEmissionFailure.resolved_at.is_(None),
        )
        .limit(limit)
        .all()
    )
    ordered = sort_failures_for_replay(rows)
    return [
        replay_emission_failure(db, r.id, company_id=company_id, actor_user_id=actor_user_id)
        for r in ordered
    ]
