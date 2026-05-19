"""
PFJ timeline — explainable hospital finance (kernel read model).
"""
from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models.financial_event import FinancialEvent
from app.models.hospital_economic import CareCharge, LiabilityAllocationRun, PatientFinancialJourney


def build_pfj_timeline(db: Session, *, pfj_id: UUID, company_id: UUID) -> List[dict[str, Any]]:
    pfj = (
        db.query(PatientFinancialJourney)
        .filter(PatientFinancialJourney.id == pfj_id, PatientFinancialJourney.company_id == company_id)
        .first()
    )
    if not pfj:
        return []

    prefix = f"patient_financial_journey:{pfj_id}"
    events: List[dict[str, Any]] = []

    for ch in (
        db.query(CareCharge)
        .filter(CareCharge.pfj_id == pfj_id, CareCharge.company_id == company_id)
        .order_by(CareCharge.accrued_at.asc())
        .all()
    ):
        events.append(
            {
                "at": ch.accrued_at.isoformat() if ch.accrued_at else None,
                "kind": "care_charge",
                "summary": f"{ch.charge_kind}: {ch.description}",
                "amount_inclusive": str(ch.amount_inclusive),
                "accrual_status": ch.accrual_status,
                "clinical_trigger": ch.clinical_trigger,
                "entity_type": "care_charge",
                "entity_id": str(ch.id),
                "encounter_id": str(ch.encounter_id) if ch.encounter_id else None,
            }
        )

    for run in (
        db.query(LiabilityAllocationRun)
        .options(joinedload(LiabilityAllocationRun.lines))
        .filter(
            LiabilityAllocationRun.company_id == company_id,
            LiabilityAllocationRun.pfj_id == pfj_id,
        )
        .order_by(LiabilityAllocationRun.created_at.asc())
        .all()
    ):
        parts = ", ".join(
            f"{ln.obligor_type} {ln.amount_inclusive}" for ln in (run.lines or []) if ln.line_kind == "obligated"
        )
        events.append(
            {
                "at": run.created_at.isoformat() if run.created_at else None,
                "kind": "liability_allocation",
                "summary": f"v{run.version} {run.allocation_reason}: {parts or '—'}",
                "amount_inclusive": str(run.gross_amount_inclusive),
                "entity_type": "liability_allocation_run",
                "entity_id": str(run.id),
                "status": run.status,
                "care_charge_id": str(run.care_charge_id),
            }
        )

    for fe in (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.correlation_group == prefix,
        )
        .order_by(FinancialEvent.occurred_at.asc())
        .all()
    ):
        events.append(
            {
                "at": fe.occurred_at.isoformat() if fe.occurred_at else None,
                "kind": "financial_event",
                "summary": fe.event_type,
                "amount_inclusive": str(fe.amount),
                "entity_type": fe.source_entity_type,
                "entity_id": str(fe.source_entity_id),
                "event_type": fe.event_type,
                "economic_direction": fe.economic_direction,
            }
        )

    events.sort(key=lambda e: e.get("at") or "")
    return events
