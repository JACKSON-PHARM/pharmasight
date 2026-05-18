"""
Enriched financial event lineage reads (E4).
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.events.settlement import fetch_settlement_links_for_event
from app.models.financial_event import FinancialEvent, FinancialEventReplayLog


def build_enriched_lineage(
    db: Session,
    *,
    company_id: UUID,
    event: FinancialEvent,
) -> dict[str, Any]:
    reversals = (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.reversal_of_event_id == event.id,
        )
        .order_by(FinancialEvent.emitted_at.asc())
        .all()
    )
    caused_by = None
    if event.caused_by_event_id:
        caused_by = (
            db.query(FinancialEvent)
            .filter(FinancialEvent.id == event.caused_by_event_id, FinancialEvent.company_id == company_id)
            .first()
        )
    settles_events = (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.caused_by_event_id == event.id,
        )
        .all()
    )
    settlement_links = fetch_settlement_links_for_event(db, company_id=company_id, event_id=event.id)
    replay_logs = (
        db.query(FinancialEventReplayLog)
        .filter(
            FinancialEventReplayLog.company_id == company_id,
            FinancialEventReplayLog.idempotency_key == event.idempotency_key,
        )
        .order_by(FinancialEventReplayLog.created_at.desc())
        .limit(20)
        .all()
    )
    if event.replay_source_failure_id:
        replay_logs = (
            db.query(FinancialEventReplayLog)
            .filter(FinancialEventReplayLog.failure_id == event.replay_source_failure_id)
            .order_by(FinancialEventReplayLog.created_at.desc())
            .all()
        ) + replay_logs

    correlation_events: list[FinancialEvent] = []
    if event.correlation_group:
        correlation_events = (
            db.query(FinancialEvent)
            .filter(
                FinancialEvent.company_id == company_id,
                FinancialEvent.correlation_group == event.correlation_group,
                FinancialEvent.id != event.id,
            )
            .order_by(FinancialEvent.occurred_at.asc())
            .limit(50)
            .all()
        )

    return {
        "event": event,
        "reversals": reversals,
        "caused_by": caused_by,
        "settles": settles_events,
        "settlement_links": settlement_links,
        "replay_logs": replay_logs,
        "correlation_events": correlation_events,
    }
