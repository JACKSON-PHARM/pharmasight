"""
PFJ coverage profiles — who may pay (not AR recognition).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.hospital_economic import PatientFinancialJourney, PfjCoverageProfile


def _normalize_hint(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def infer_obligor_route_from_pfj(pfj: PatientFinancialJourney) -> str:
    mode = _normalize_hint(pfj.intake_payment_mode_hint)
    scheme = _normalize_hint(pfj.intake_insurance_scheme_hint)
    if mode in ("insurance", "insured", "nhif", "sha"):
        return "insurance"
    if scheme and scheme not in ("cash", "self", "self_pay", "none"):
        return "insurance"
    if mode in ("corporate", "employer", "company"):
        return "employer"
    return "self_pay"


def get_primary_coverage(
    db: Session, *, company_id: UUID, pfj_id: UUID
) -> Optional[PfjCoverageProfile]:
    return (
        db.query(PfjCoverageProfile)
        .filter(
            PfjCoverageProfile.company_id == company_id,
            PfjCoverageProfile.pfj_id == pfj_id,
            PfjCoverageProfile.coverage_role == "primary",
            PfjCoverageProfile.is_active.is_(True),
        )
        .first()
    )


def ensure_primary_coverage_for_pfj(
    db: Session,
    *,
    pfj: PatientFinancialJourney,
    insurance_provider_id: Optional[UUID] = None,
    obligor_route: Optional[str] = None,
) -> PfjCoverageProfile:
    existing = get_primary_coverage(db, company_id=pfj.company_id, pfj_id=pfj.id)
    if existing:
        return existing
    route = obligor_route or infer_obligor_route_from_pfj(pfj)
    profile = PfjCoverageProfile(
        company_id=pfj.company_id,
        pfj_id=pfj.id,
        coverage_role="primary",
        obligor_route=route,
        insurance_provider_id=insurance_provider_id if route == "insurance" else None,
        insurer_coverage_percent=Decimal("80"),
        is_active=True,
    )
    db.add(profile)
    db.flush()
    return profile


def upsert_primary_coverage(
    db: Session,
    *,
    company_id: UUID,
    pfj_id: UUID,
    obligor_route: str,
    insurance_provider_id: Optional[UUID] = None,
    employer_name: Optional[str] = None,
    member_id: Optional[str] = None,
    policy_number: Optional[str] = None,
    insurer_coverage_percent: Optional[Decimal] = None,
    patient_copay_percent: Optional[Decimal] = None,
    patient_copay_fixed: Optional[Decimal] = None,
) -> PfjCoverageProfile:
    profile = get_primary_coverage(db, company_id=company_id, pfj_id=pfj_id)
    if not profile:
        profile = PfjCoverageProfile(
            company_id=company_id,
            pfj_id=pfj_id,
            coverage_role="primary",
            is_active=True,
        )
        db.add(profile)
    profile.obligor_route = obligor_route
    profile.insurance_provider_id = insurance_provider_id if obligor_route == "insurance" else None
    profile.employer_name = (employer_name or "").strip() or None
    profile.member_id = (member_id or "").strip() or None
    profile.policy_number = (policy_number or "").strip() or None
    if insurer_coverage_percent is not None:
        profile.insurer_coverage_percent = insurer_coverage_percent
    if patient_copay_percent is not None:
        profile.patient_copay_percent = patient_copay_percent
    if patient_copay_fixed is not None:
        profile.patient_copay_fixed = patient_copay_fixed
    db.flush()
    return profile
