"""
Patient Financial Journey (PFJ) — constitutional economic root for hospital care.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.clinic import Encounter, Patient
from app.models.hospital_economic import PatientFinancialJourney

_ACTIVE_PFJ_STATUSES = frozenset({"open", "accruing", "pending_discharge"})


def get_active_pfj_for_patient(
    db: Session, *, company_id: UUID, patient_id: UUID
) -> Optional[PatientFinancialJourney]:
    return (
        db.query(PatientFinancialJourney)
        .filter(
            PatientFinancialJourney.company_id == company_id,
            PatientFinancialJourney.patient_id == patient_id,
            PatientFinancialJourney.status.in_(tuple(_ACTIVE_PFJ_STATUSES)),
        )
        .order_by(PatientFinancialJourney.opened_at.desc())
        .first()
    )


def open_pfj(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    patient_id: UUID,
    intake_payment_mode_hint: Optional[str] = None,
    intake_insurance_scheme_hint: Optional[str] = None,
) -> PatientFinancialJourney:
    existing = get_active_pfj_for_patient(db, company_id=company_id, patient_id=patient_id)
    if existing:
        return existing
    pfj = PatientFinancialJourney(
        company_id=company_id,
        branch_id=branch_id,
        patient_id=patient_id,
        status="open",
        intake_payment_mode_hint=(intake_payment_mode_hint or "").strip() or None,
        intake_insurance_scheme_hint=(intake_insurance_scheme_hint or "").strip() or None,
    )
    db.add(pfj)
    db.flush()
    return pfj


def ensure_pfj_for_encounter(
    db: Session,
    *,
    encounter: Encounter,
    patient: Patient,
) -> PatientFinancialJourney:
    if encounter.pfj_id:
        pfj = (
            db.query(PatientFinancialJourney)
            .filter(
                PatientFinancialJourney.id == encounter.pfj_id,
                PatientFinancialJourney.company_id == encounter.company_id,
            )
            .first()
        )
        if pfj:
            return pfj
    pfj = open_pfj(
        db,
        company_id=encounter.company_id,
        branch_id=encounter.branch_id,
        patient_id=patient.id,
        intake_payment_mode_hint=encounter.intake_payment_mode,
        intake_insurance_scheme_hint=encounter.intake_insurance_scheme,
    )
    encounter.pfj_id = pfj.id
    if pfj.status == "open":
        pfj.status = "accruing"
    db.add(encounter)
    db.add(pfj)
    db.flush()
    return pfj


def get_pfj_scoped(db: Session, *, pfj_id: UUID, company_id: UUID) -> Optional[PatientFinancialJourney]:
    return (
        db.query(PatientFinancialJourney)
        .filter(PatientFinancialJourney.id == pfj_id, PatientFinancialJourney.company_id == company_id)
        .first()
    )
