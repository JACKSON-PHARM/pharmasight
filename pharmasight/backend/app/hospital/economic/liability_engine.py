"""
H2 — Liability allocation engine.

Splits accrued care charge value across obligors (versioned, append-only runs).
Does not create receivables (H4) or mutate invoices.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.hospital.economic.coverage_service import ensure_primary_coverage_for_pfj, get_primary_coverage
from app.hospital.economic.financial_hooks import on_liability_allocated
from app.models.hospital_economic import (
    CareCharge,
    LiabilityAllocationLine,
    LiabilityAllocationRun,
    PatientFinancialJourney,
    PfjCoverageProfile,
)

logger = logging.getLogger(__name__)

_QUANT = Decimal("0.0001")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class ObligorSlice:
    obligor_type: str
    amount_inclusive: Decimal
    insurance_provider_id: Optional[UUID] = None
    employer_ref: Optional[str] = None
    line_kind: str = "obligated"
    notes: Optional[str] = None


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


def compute_slices_from_coverage(
    gross: Decimal,
    profile: Optional[PfjCoverageProfile],
    *,
    insurer_line_kind: str = "obligated",
) -> List[ObligorSlice]:
    """Derive obligor splits from primary coverage (policy hints only — not authorization)."""
    gross = _round_money(max(gross, _ZERO))
    if gross <= _ZERO:
        return []

    if profile is None or profile.obligor_route == "self_pay":
        return [ObligorSlice(obligor_type="patient", amount_inclusive=gross)]

    if profile.obligor_route == "employer":
        return [
            ObligorSlice(
                obligor_type="employer",
                amount_inclusive=gross,
                employer_ref=profile.employer_name,
            )
        ]

    if profile.obligor_route == "insurance":
        pct = Decimal(str(profile.insurer_coverage_percent or 80))
        if profile.patient_copay_percent is not None:
            patient_pct = Decimal(str(profile.patient_copay_percent))
            pct = Decimal("100") - patient_pct
        insurer_amt = _round_money(gross * pct / Decimal("100"))
        patient_amt = gross - insurer_amt
        if profile.patient_copay_fixed is not None:
            copay = _round_money(Decimal(str(profile.patient_copay_fixed)))
            if copay > gross:
                copay = gross
            patient_amt = copay
            insurer_amt = gross - patient_amt
        slices: List[ObligorSlice] = []
        if insurer_amt > _ZERO:
            slices.append(
                ObligorSlice(
                    obligor_type="insurer",
                    amount_inclusive=insurer_amt,
                    insurance_provider_id=profile.insurance_provider_id,
                    line_kind=insurer_line_kind,
                )
            )
        if patient_amt > _ZERO:
            slices.append(ObligorSlice(obligor_type="patient", amount_inclusive=patient_amt))
        if not slices:
            slices.append(ObligorSlice(obligor_type="patient", amount_inclusive=gross))
        return slices

    # mixed: default 50/50 until manual reallocation
    half = _round_money(gross / Decimal("2"))
    remainder = gross - half
    return [
        ObligorSlice(
            obligor_type="insurer",
            amount_inclusive=half,
            insurance_provider_id=profile.insurance_provider_id if profile else None,
            line_kind=insurer_line_kind,
        ),
        ObligorSlice(obligor_type="patient", amount_inclusive=remainder),
    ]


def _validate_slices(gross: Decimal, slices: List[ObligorSlice]) -> None:
    total = sum((s.amount_inclusive for s in slices), _ZERO)
    if _round_money(total) != _round_money(gross):
        raise ValueError(f"Liability slices must sum to gross {gross}; got {total}")


def get_active_allocation_run(
    db: Session, *, company_id: UUID, care_charge_id: UUID
) -> Optional[LiabilityAllocationRun]:
    return (
        db.query(LiabilityAllocationRun)
        .options(joinedload(LiabilityAllocationRun.lines))
        .filter(
            LiabilityAllocationRun.company_id == company_id,
            LiabilityAllocationRun.care_charge_id == care_charge_id,
            LiabilityAllocationRun.status == "active",
        )
        .first()
    )


def _next_version(db: Session, care_charge_id: UUID) -> int:
    latest = (
        db.query(LiabilityAllocationRun.version)
        .filter(LiabilityAllocationRun.care_charge_id == care_charge_id)
        .order_by(LiabilityAllocationRun.version.desc())
        .first()
    )
    return (latest[0] if latest else 0) + 1


def _create_run(
    db: Session,
    *,
    charge: CareCharge,
    pfj: PatientFinancialJourney,
    slices: List[ObligorSlice],
    reason: str,
    created_by: Optional[UUID] = None,
    supersede_previous: bool = True,
) -> LiabilityAllocationRun:
    gross = _round_money(Decimal(str(charge.amount_inclusive or 0)))
    _validate_slices(gross, slices)

    previous: Optional[LiabilityAllocationRun] = None
    if supersede_previous:
        previous = get_active_allocation_run(db, company_id=charge.company_id, care_charge_id=charge.id)
        if previous:
            previous.status = "superseded"
            previous.superseded_at = datetime.now(timezone.utc)
            db.add(previous)

    version = _next_version(db, charge.id)
    run = LiabilityAllocationRun(
        company_id=charge.company_id,
        pfj_id=pfj.id,
        care_charge_id=charge.id,
        version=version,
        allocation_reason=reason,
        status="active",
        gross_amount_inclusive=gross,
        created_by=created_by,
    )
    db.add(run)
    db.flush()

    if previous:
        previous.superseded_by_run_id = run.id
        db.add(previous)

    for sl in slices:
        db.add(
            LiabilityAllocationLine(
                run_id=run.id,
                obligor_type=sl.obligor_type,
                insurance_provider_id=sl.insurance_provider_id,
                employer_ref=sl.employer_ref,
                amount_inclusive=sl.amount_inclusive,
                line_kind=sl.line_kind,
                notes=sl.notes,
            )
        )
    db.flush()
    db.refresh(run)
    on_liability_allocated(db, run, charge=charge)
    return run


def allocate_charge_liability(
    db: Session,
    care_charge_id: UUID,
    *,
    reason: str = "initial",
    created_by: Optional[UUID] = None,
    slices: Optional[List[ObligorSlice]] = None,
) -> Optional[LiabilityAllocationRun]:
    """
    Allocate or return existing active run for a charge.
    Idempotent when active run already exists and reason is 'initial'.
    """
    charge = (
        db.query(CareCharge)
        .filter(CareCharge.id == care_charge_id, CareCharge.accrual_status == "accrued")
        .first()
    )
    if not charge or charge.reversed_at:
        return None

    existing = get_active_allocation_run(db, company_id=charge.company_id, care_charge_id=charge.id)
    if existing and reason == "initial":
        return existing

    pfj = (
        db.query(PatientFinancialJourney)
        .filter(
            PatientFinancialJourney.id == charge.pfj_id,
            PatientFinancialJourney.company_id == charge.company_id,
        )
        .first()
    )
    if not pfj:
        return None

    profile = ensure_primary_coverage_for_pfj(db, pfj=pfj)
    gross = _round_money(Decimal(str(charge.amount_inclusive or 0)))
    if gross <= _ZERO:
        return existing

    insurer_kind = "obligated"
    if profile and profile.obligor_route == "insurance" and slices is None:
        from app.hospital.economic.authorization_engine import has_approved_coverage_auth

        if not has_approved_coverage_auth(
            db,
            company_id=charge.company_id,
            pfj_id=pfj.id,
            insurance_provider_id=profile.insurance_provider_id,
            care_charge_id=charge.id,
        ):
            insurer_kind = "pending_authorization"

    use_slices = (
        slices
        if slices is not None
        else compute_slices_from_coverage(gross, profile, insurer_line_kind=insurer_kind)
    )
    if not use_slices:
        use_slices = [ObligorSlice(obligor_type="patient", amount_inclusive=gross)]

    try:
        return _create_run(
            db,
            charge=charge,
            pfj=pfj,
            slices=use_slices,
            reason=reason,
            created_by=created_by,
            supersede_previous=reason != "initial" or existing is not None,
        )
    except ValueError:
        logger.exception("liability allocation validation failed charge_id=%s", care_charge_id)
        raise


def reallocate_after_denial(
    db: Session,
    care_charge_id: UUID,
    *,
    denied_insurer_amount: Decimal,
    created_by: Optional[UUID] = None,
) -> Optional[LiabilityAllocationRun]:
    """Move denied insurer portion to patient residual."""
    charge = db.query(CareCharge).filter(CareCharge.id == care_charge_id).first()
    if not charge:
        return None
    run = get_active_allocation_run(db, company_id=charge.company_id, care_charge_id=charge.id)
    if not run:
        return allocate_charge_liability(db, care_charge_id, reason="denial_reallocation", created_by=created_by)

    gross = _round_money(Decimal(str(charge.amount_inclusive or 0)))
    patient_amt = _ZERO
    insurer_amt = _ZERO
    provider_id = None
    for line in run.lines:
        amt = Decimal(str(line.amount_inclusive or 0))
        if line.obligor_type == "patient":
            patient_amt += amt
        elif line.obligor_type == "insurer":
            insurer_amt += amt
            provider_id = line.insurance_provider_id

    shift = min(_round_money(denied_insurer_amount), insurer_amt)
    new_slices: List[ObligorSlice] = []
    new_insurer = insurer_amt - shift
    new_patient = patient_amt + shift
    if new_insurer > _ZERO:
        new_slices.append(
            ObligorSlice(
                obligor_type="insurer",
                amount_inclusive=new_insurer,
                insurance_provider_id=provider_id,
            )
        )
    if new_patient > _ZERO:
        new_slices.append(ObligorSlice(obligor_type="patient", amount_inclusive=new_patient))
    if not new_slices:
        new_slices = [ObligorSlice(obligor_type="patient", amount_inclusive=gross)]

    pfj = db.query(PatientFinancialJourney).filter(PatientFinancialJourney.id == charge.pfj_id).first()
    if not pfj:
        return None
    return _create_run(
        db,
        charge=charge,
        pfj=pfj,
        slices=new_slices,
        reason="denial_reallocation",
        created_by=created_by,
        supersede_previous=True,
    )


def summarize_pfj_liability(
    db: Session, *, company_id: UUID, pfj_id: UUID
) -> dict[str, Decimal]:
    """Derived obligor exposure from active allocation lines (not stored balance)."""
    totals = {"patient": _ZERO, "insurer": _ZERO, "employer": _ZERO, "guarantor": _ZERO, "total": _ZERO}
    runs = (
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
    for run in runs:
        for line in run.lines:
            if line.line_kind != "obligated":
                continue
            amt = Decimal(str(line.amount_inclusive or 0))
            key = line.obligor_type
            if key in totals:
                totals[key] += amt
            totals["total"] += amt
    return {k: _round_money(v) for k, v in totals.items()}
