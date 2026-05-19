"""
H4 — Recognition policies: obligated liability → receivable evidence (financial_events).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.hospital.economic.financial_hooks import on_obligor_receivable_recognized
from app.models.hospital_economic import (
    CareCharge,
    HospitalRecognitionRecord,
    LiabilityAllocationLine,
    LiabilityAllocationRun,
)

_ZERO = Decimal("0")


def _active_runs_for_pfj(db: Session, *, company_id: UUID, pfj_id: UUID) -> List[LiabilityAllocationRun]:
    return (
        db.query(LiabilityAllocationRun)
        .options(joinedload(LiabilityAllocationRun.lines))
        .join(CareCharge, CareCharge.id == LiabilityAllocationRun.care_charge_id)
        .filter(
            LiabilityAllocationRun.company_id == company_id,
            LiabilityAllocationRun.pfj_id == pfj_id,
            LiabilityAllocationRun.status == "active",
            CareCharge.accrual_status == "accrued",
            CareCharge.reversed_at.is_(None),
        )
        .all()
    )


def _already_recognized(db: Session, line_id: UUID, obligor_type: str) -> bool:
    return (
        db.query(HospitalRecognitionRecord)
        .filter(
            HospitalRecognitionRecord.allocation_line_id == line_id,
            HospitalRecognitionRecord.obligor_type == obligor_type,
        )
        .first()
        is not None
    )


def recognize_allocation_line(
    db: Session,
    *,
    line: LiabilityAllocationLine,
    charge: CareCharge,
    obligor_type: str,
) -> Optional[HospitalRecognitionRecord]:
    if line.line_kind != "obligated":
        return None
    if line.obligor_type != obligor_type:
        return None
    amt = Decimal(str(line.amount_inclusive or 0))
    if amt <= _ZERO:
        return None
    if _already_recognized(db, line.id, obligor_type):
        return (
            db.query(HospitalRecognitionRecord)
            .filter(
                HospitalRecognitionRecord.allocation_line_id == line.id,
                HospitalRecognitionRecord.obligor_type == obligor_type,
            )
            .first()
        )
    event_id = on_obligor_receivable_recognized(
        db, charge=charge, line=line, obligor_type=obligor_type, amount=amt
    )
    rec = HospitalRecognitionRecord(
        company_id=charge.company_id,
        pfj_id=charge.pfj_id,
        care_charge_id=charge.id,
        allocation_line_id=line.id,
        obligor_type=obligor_type,
        recognized_amount=amt,
        financial_event_id=event_id,
    )
    db.add(rec)
    db.flush()
    return rec


def recognize_pfj_obligor_portion(
    db: Session,
    *,
    company_id: UUID,
    pfj_id: UUID,
    obligor_type: str,
) -> List[HospitalRecognitionRecord]:
    """Recognize all obligated, not-yet-recognized slices for an obligor on this PFJ."""
    out: List[HospitalRecognitionRecord] = []
    runs = _active_runs_for_pfj(db, company_id=company_id, pfj_id=pfj_id)
    charge_ids = {r.care_charge_id for r in runs}
    charges = {
        c.id: c
        for c in db.query(CareCharge).filter(CareCharge.id.in_(charge_ids)).all()
    }
    for run in runs:
        charge = charges.get(run.care_charge_id)
        if not charge:
            continue
        for line in run.lines:
            if line.obligor_type != obligor_type:
                continue
            rec = recognize_allocation_line(
                db, line=line, charge=charge, obligor_type=obligor_type
            )
            if rec:
                out.append(rec)
    return out
