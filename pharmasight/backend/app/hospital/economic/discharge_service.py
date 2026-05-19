"""
H6 — PFJ discharge settlement (financial close without stored running balance).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.hospital.economic.authorization_engine import pending_authorization_total
from app.hospital.economic.liability_engine import summarize_pfj_liability
from app.models.hospital_economic import PatientFinancialJourney, PfjDischargeSettlement

_ZERO = Decimal("0")


def close_pfj_financial(
    db: Session,
    *,
    pfj: PatientFinancialJourney,
    closed_by: Optional[UUID] = None,
    notes: Optional[str] = None,
) -> PfjDischargeSettlement:
    if pfj.status == "financial_closed":
        existing = (
            db.query(PfjDischargeSettlement)
            .filter(PfjDischargeSettlement.pfj_id == pfj.id)
            .first()
        )
        if existing:
            return existing

    totals = summarize_pfj_liability(db, company_id=pfj.company_id, pfj_id=pfj.id)
    pending = pending_authorization_total(db, company_id=pfj.company_id, pfj_id=pfj.id)

    record = PfjDischargeSettlement(
        company_id=pfj.company_id,
        pfj_id=pfj.id,
        patient_residual=totals.get("patient", _ZERO),
        insurer_outstanding=totals.get("insurer", _ZERO),
        notes=(notes or "").strip() or None,
        closed_by=closed_by,
        closed_at=datetime.now(timezone.utc),
    )
    pfj.status = "financial_closed"
    pfj.closed_at = record.closed_at
    db.add(record)
    db.add(pfj)
    db.flush()
    if pending > _ZERO:
        record.notes = ((record.notes or "") + f" Pending authorization: {pending}.").strip()
        db.add(record)
        db.flush()
    return record
