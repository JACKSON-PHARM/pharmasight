"""
Aggregated PFJ workspace for UI (single round-trip).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.hospital.economic.authorization_engine import list_authorizations, pending_authorization_total
from app.hospital.economic.coverage_service import get_primary_coverage
from app.hospital.economic.liability_engine import get_active_allocation_run, summarize_pfj_liability
from app.hospital.economic.pfj_service import get_active_pfj_for_patient, get_pfj_scoped
from app.hospital.economic.timeline import build_pfj_timeline
from app.models.clinic import Patient
from app.models.hospital_economic import CareCharge, HospitalRecognitionRecord, PatientFinancialJourney


def build_patient_workspace(
    db: Session,
    *,
    company_id: UUID,
    patient_id: UUID,
) -> Dict[str, Any]:
    patient = (
        db.query(Patient)
        .filter(Patient.id == patient_id, Patient.company_id == company_id)
        .first()
    )
    if not patient:
        return {"patient": None, "pfj": None}

    pfj = get_active_pfj_for_patient(db, company_id=company_id, patient_id=patient_id)
    if not pfj:
        pfj = (
            db.query(PatientFinancialJourney)
            .filter(
                PatientFinancialJourney.company_id == company_id,
                PatientFinancialJourney.patient_id == patient_id,
            )
            .order_by(PatientFinancialJourney.opened_at.desc())
            .first()
        )

    payload: Dict[str, Any] = {
        "patient": {
            "id": str(patient.id),
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
        },
        "pfj": None,
        "coverage": None,
        "liability_summary": None,
        "pending_authorization": "0",
        "timeline": [],
        "charges": [],
        "authorizations": [],
        "recognitions_count": 0,
    }

    if not pfj:
        return payload

    payload["pfj"] = {
        "id": str(pfj.id),
        "status": pfj.status,
        "opened_at": pfj.opened_at.isoformat() if pfj.opened_at else None,
        "intake_payment_mode_hint": pfj.intake_payment_mode_hint,
        "intake_insurance_scheme_hint": pfj.intake_insurance_scheme_hint,
    }
    cov = get_primary_coverage(db, company_id=company_id, pfj_id=pfj.id)
    if cov:
        payload["coverage"] = {
            "obligor_route": cov.obligor_route,
            "insurance_provider_id": str(cov.insurance_provider_id) if cov.insurance_provider_id else None,
            "insurer_coverage_percent": str(cov.insurer_coverage_percent),
            "employer_name": cov.employer_name,
            "member_id": cov.member_id,
        }
    payload["liability_summary"] = {
        k: str(v) for k, v in summarize_pfj_liability(db, company_id=company_id, pfj_id=pfj.id).items()
    }
    payload["pending_authorization"] = str(
        pending_authorization_total(db, company_id=company_id, pfj_id=pfj.id)
    )
    payload["timeline"] = build_pfj_timeline(db, pfj_id=pfj.id, company_id=company_id)
    payload["recognitions_count"] = (
        db.query(HospitalRecognitionRecord)
        .filter(HospitalRecognitionRecord.pfj_id == pfj.id)
        .count()
    )

    charges = (
        db.query(CareCharge)
        .filter(CareCharge.pfj_id == pfj.id, CareCharge.company_id == company_id)
        .order_by(CareCharge.accrued_at.desc())
        .limit(100)
        .all()
    )
    for ch in charges:
        run = get_active_allocation_run(db, company_id=company_id, care_charge_id=ch.id)
        lines = []
        if run:
            lines = [
                {
                    "obligor_type": ln.obligor_type,
                    "amount_inclusive": str(ln.amount_inclusive),
                    "line_kind": ln.line_kind,
                }
                for ln in run.lines
            ]
        payload["charges"].append(
            {
                "id": str(ch.id),
                "charge_kind": ch.charge_kind,
                "description": ch.description,
                "amount_inclusive": str(ch.amount_inclusive),
                "accrual_status": ch.accrual_status,
                "accrued_at": ch.accrued_at.isoformat() if ch.accrued_at else None,
                "liability": lines,
            }
        )

    for auth in list_authorizations(db, company_id=company_id, pfj_id=pfj.id):
        payload["authorizations"].append(
            {
                "id": str(auth.id),
                "status": auth.status,
                "requested_amount": str(auth.requested_amount),
                "approved_amount": str(auth.approved_amount),
                "reference_number": auth.reference_number,
                "created_at": auth.created_at.isoformat() if auth.created_at else None,
            }
        )

    return payload
