"""
emit_financial_event — sole write path for financial_events (E3/E4).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Tuple
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.finance.doctrine.correlation import validate_correlation_group
from app.finance.events.lifecycle import (
    EMISSION_CHANNEL_ORIGINAL,
    OPERATIONAL_STATUS_COMPENSATED,
    OPERATIONAL_STATUS_EMITTED,
    OPERATIONAL_STATUS_REPLAYED,
)
from app.finance.events.payload import validate_event_payload
from app.finance.events.registry import FinancialEventSpec, build_idempotency_key, get_event_spec
from app.models.financial_event import FinancialEvent, FinancialEventEmissionFailure

logger = logging.getLogger("pharmasight.finance.events")

FINANCIAL_EVENT_EMISSION_FAILED = "financial_event_emission_failed"
FINANCIAL_EVENT_EMITTED = "financial_event_emitted"
FINANCIAL_EVENT_DUPLICATE_SKIPPED = "financial_event_duplicate_skipped"


class EmitResult(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True)
class EmitFinancialEventRequest:
    event_type: str
    company_id: UUID
    branch_id: UUID
    source_entity_id: UUID
    occurred_at: datetime
    amount: Decimal
    currency_code: str = "KES"
    source_reference: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    governance_metadata: Optional[dict[str, Any]] = None
    reversal_of_event_id: Optional[UUID] = None
    caused_by_event_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None
    operational_status: str = OPERATIONAL_STATUS_EMITTED
    emission_channel: str = EMISSION_CHANNEL_ORIGINAL
    correlation_group: Optional[str] = None
    replay_source_failure_id: Optional[UUID] = None


def _occurred_at_dt(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


def _record_failure(db: Session, req: EmitFinancialEventRequest, spec: FinancialEventSpec, error: str) -> None:
    try:
        key = req.idempotency_key or build_idempotency_key(
            spec, source_entity_id=str(req.source_entity_id), reversal_of_event_id=str(req.reversal_of_event_id or "")
        )
        existing = (
            db.query(FinancialEventEmissionFailure)
            .filter(
                FinancialEventEmissionFailure.company_id == req.company_id,
                FinancialEventEmissionFailure.idempotency_key == key,
                FinancialEventEmissionFailure.resolved_at.is_(None),
            )
            .first()
        )
        if existing:
            existing.retry_count = (existing.retry_count or 0) + 1
            existing.error_message = error[:4000]
        else:
            db.add(
                FinancialEventEmissionFailure(
                    company_id=req.company_id,
                    branch_id=req.branch_id,
                    operational_domain=spec.operational_domain,
                    event_type=spec.event_type,
                    idempotency_key=key,
                    source_entity_type=spec.source_entity_type,
                    source_entity_id=req.source_entity_id,
                    source_reference=req.source_reference,
                    occurred_at=_occurred_at_dt(req.occurred_at),
                    amount=abs(Decimal(str(req.amount))),
                    currency_code=(req.currency_code or "KES").upper()[:3],
                    economic_direction=spec.economic_direction,
                    classification=spec.classification,
                    event_schema_version=spec.schema_version,
                    payload_json=req.payload or {},
                    governance_metadata_json=req.governance_metadata or {},
                    error_message=error[:4000],
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("failed to persist financial_event_emission_failure", exc_info=True)


def _log_governance(event: str, **fields: Any) -> None:
    try:
        logger.info(json.dumps({"event": event, **fields}, default=str))
    except Exception:
        pass


def emit_financial_event(
    db: Session, request: EmitFinancialEventRequest
) -> Tuple[EmitResult, Optional[UUID]]:
    """
    Append one financial event. Never raises.

    Returns (result, financial_event_id when created or existing on duplicate).
    """
    try:
        spec = get_event_spec(request.event_type)
        amount = abs(Decimal(str(request.amount)))
        if amount <= 0:
            raise ValueError("amount must be positive for economically meaningful events")

        payload = dict(request.payload or {})
        validate_event_payload(payload)
        if request.correlation_group:
            validate_correlation_group(request.correlation_group, strict=True)

        idem = request.idempotency_key or build_idempotency_key(
            spec,
            source_entity_id=str(request.source_entity_id),
            reversal_of_event_id=str(request.reversal_of_event_id or ""),
        )

        op_status = request.operational_status
        if request.reversal_of_event_id is not None and op_status == OPERATIONAL_STATUS_EMITTED:
            op_status = OPERATIONAL_STATUS_COMPENSATED

        row = FinancialEvent(
            company_id=request.company_id,
            branch_id=request.branch_id,
            operational_domain=spec.operational_domain,
            event_type=spec.event_type,
            classification=spec.classification,
            event_schema_version=spec.schema_version,
            occurred_at=_occurred_at_dt(request.occurred_at),
            amount=amount,
            currency_code=(request.currency_code or "KES").upper()[:3],
            economic_direction=spec.economic_direction,
            source_entity_type=spec.source_entity_type,
            source_entity_id=request.source_entity_id,
            source_reference=request.source_reference,
            idempotency_key=idem,
            reversal_of_event_id=request.reversal_of_event_id,
            caused_by_event_id=request.caused_by_event_id,
            payload_json=payload,
            governance_metadata_json=request.governance_metadata or {},
            operational_status=op_status,
            emission_channel=request.emission_channel,
            correlation_group=request.correlation_group,
            replay_source_failure_id=request.replay_source_failure_id,
        )
        db.add(row)
        db.flush()
        event_id = row.id
        db.commit()
        _log_governance(
            FINANCIAL_EVENT_EMITTED,
            financial_event_id=str(event_id),
            event_type=spec.event_type,
            company_id=str(request.company_id),
            idempotency_key=idem,
            emission_channel=request.emission_channel,
            operational_status=op_status,
        )
        return EmitResult.CREATED, event_id
    except IntegrityError:
        db.rollback()
        existing_id = None
        try:
            idem = request.idempotency_key or build_idempotency_key(
                get_event_spec(request.event_type),
                source_entity_id=str(request.source_entity_id),
                reversal_of_event_id=str(request.reversal_of_event_id or ""),
            )
            existing = (
                db.query(FinancialEvent)
                .filter(
                    FinancialEvent.company_id == request.company_id,
                    FinancialEvent.idempotency_key == idem,
                )
                .first()
            )
            if existing:
                existing_id = existing.id
        except Exception:
            pass
        _log_governance(
            FINANCIAL_EVENT_DUPLICATE_SKIPPED,
            event_type=request.event_type,
            company_id=str(request.company_id),
            source_entity_id=str(request.source_entity_id),
        )
        return EmitResult.DUPLICATE, existing_id
    except Exception as exc:
        db.rollback()
        err = str(exc)
        logger.warning(
            json.dumps(
                {
                    "event": FINANCIAL_EVENT_EMISSION_FAILED,
                    "event_type": request.event_type,
                    "company_id": str(request.company_id),
                    "source_entity_id": str(request.source_entity_id),
                    "error": err,
                },
                default=str,
            )
        )
        try:
            spec = get_event_spec(request.event_type)
            _record_failure(db, request, spec, err)
        except Exception:
            pass
        return EmitResult.FAILED, None


def emit_reversal_event(
    db: Session,
    *,
    original_event_id: UUID,
    company_id: UUID,
    branch_id: UUID,
    source_entity_id: UUID,
    occurred_at: datetime,
    amount: Decimal,
    source_reference: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Tuple[EmitResult, Optional[UUID]]:
    """Emit compensating event for a prior financial_event."""
    original = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.id == original_event_id, FinancialEvent.company_id == company_id)
        .first()
    )
    if not original:
        return EmitResult.FAILED, None
    orig_spec = get_event_spec(original.event_type)
    if not orig_spec.reversibility or not orig_spec.compensating_event_type:
        return EmitResult.FAILED, None
    comp_spec = get_event_spec(orig_spec.compensating_event_type)
    return emit_financial_event(
        db,
        EmitFinancialEventRequest(
            event_type=comp_spec.event_type,
            company_id=company_id,
            branch_id=branch_id,
            source_entity_id=source_entity_id,
            occurred_at=occurred_at,
            amount=amount,
            currency_code=original.currency_code,
            source_reference=source_reference,
            payload=payload,
            reversal_of_event_id=original_event_id,
            operational_status=OPERATIONAL_STATUS_COMPENSATED,
            governance_metadata={"reverses_event_type": original.event_type},
        ),
    )
