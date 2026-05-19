"""
H3 — Authorization lifecycle (pre-auth gates insurer liability recognition).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.hospital.economic.liability_engine import allocate_charge_liability, reallocate_after_denial
from app.models.hospital_economic import CareAuthorization, CareCharge, PatientFinancialJourney

_APPROVED = frozenset({"approved", "partial"})


def has_approved_coverage_auth(
    db: Session,
    *,
    company_id: UUID,
    pfj_id: UUID,
    insurance_provider_id: Optional[UUID] = None,
    care_charge_id: Optional[UUID] = None,
) -> bool:
    q = db.query(CareAuthorization).filter(
        CareAuthorization.company_id == company_id,
        CareAuthorization.pfj_id == pfj_id,
        CareAuthorization.status.in_(tuple(_APPROVED)),
    )
    if insurance_provider_id:
        q = q.filter(CareAuthorization.insurance_provider_id == insurance_provider_id)
    if care_charge_id:
        q = q.filter(
            (CareAuthorization.care_charge_id == care_charge_id)
            | (CareAuthorization.care_charge_id.is_(None))
        )
    return q.first() is not None


def list_authorizations(
    db: Session, *, company_id: UUID, pfj_id: UUID
) -> List[CareAuthorization]:
    return (
        db.query(CareAuthorization)
        .filter(CareAuthorization.company_id == company_id, CareAuthorization.pfj_id == pfj_id)
        .order_by(CareAuthorization.created_at.desc())
        .all()
    )


def request_authorization(
    db: Session,
    *,
    company_id: UUID,
    pfj_id: UUID,
    requested_amount: Decimal,
    insurance_provider_id: Optional[UUID] = None,
    care_charge_id: Optional[UUID] = None,
    reference_number: Optional[str] = None,
    notes: Optional[str] = None,
    created_by: Optional[UUID] = None,
) -> CareAuthorization:
    auth = CareAuthorization(
        company_id=company_id,
        pfj_id=pfj_id,
        care_charge_id=care_charge_id,
        insurance_provider_id=insurance_provider_id,
        status="requested",
        reference_number=(reference_number or "").strip() or None,
        requested_amount=requested_amount,
        approved_amount=Decimal("0"),
        notes=(notes or "").strip() or None,
        created_by=created_by,
    )
    db.add(auth)
    db.flush()
    return auth


def decide_authorization(
    db: Session,
    *,
    authorization_id: UUID,
    company_id: UUID,
    status: str,
    approved_amount: Optional[Decimal] = None,
    valid_from: Optional[date] = None,
    valid_until: Optional[date] = None,
    decided_by: Optional[UUID] = None,
    notes: Optional[str] = None,
) -> CareAuthorization:
    status = (status or "").strip().lower()
    if status not in ("approved", "partial", "denied", "expired"):
        raise ValueError("Invalid authorization status")
    auth = (
        db.query(CareAuthorization)
        .filter(CareAuthorization.id == authorization_id, CareAuthorization.company_id == company_id)
        .first()
    )
    if not auth:
        raise ValueError("Authorization not found")
    auth.status = status
    auth.decided_by = decided_by
    auth.decided_at = datetime.now(timezone.utc)
    if notes:
        auth.notes = notes
    if valid_from:
        auth.valid_from = valid_from
    if valid_until:
        auth.valid_until = valid_until
    if status in _APPROVED:
        auth.approved_amount = approved_amount if approved_amount is not None else auth.requested_amount
    elif status == "denied":
        auth.approved_amount = Decimal("0")
    db.add(auth)
    db.flush()

    if status in _APPROVED:
        _refresh_pfj_liability_after_auth(db, pfj_id=auth.pfj_id, company_id=company_id)
    elif status == "denied" and auth.care_charge_id:
        reallocate_after_denial(
            db,
            auth.care_charge_id,
            denied_insurer_amount=auth.requested_amount,
            created_by=decided_by,
        )
    return auth


def _refresh_pfj_liability_after_auth(db: Session, *, pfj_id: UUID, company_id: UUID) -> None:
    charges = (
        db.query(CareCharge)
        .filter(
            CareCharge.pfj_id == pfj_id,
            CareCharge.company_id == company_id,
            CareCharge.accrual_status == "accrued",
            CareCharge.reversed_at.is_(None),
        )
        .all()
    )
    for ch in charges:
        try:
            allocate_charge_liability(db, ch.id, reason="coverage_change")
        except Exception:
            import logging

            logging.getLogger(__name__).exception("reallocate after auth pfj=%s charge=%s", pfj_id, ch.id)


def pending_authorization_total(db: Session, *, company_id: UUID, pfj_id: UUID) -> Decimal:
    from app.models.hospital_economic import LiabilityAllocationLine, LiabilityAllocationRun

    total = Decimal("0")
    from sqlalchemy.orm import joinedload

    runs = (
        db.query(LiabilityAllocationRun)
        .options(joinedload(LiabilityAllocationRun.lines))
        .join(CareCharge, CareCharge.id == LiabilityAllocationRun.care_charge_id)
        .filter(
            LiabilityAllocationRun.company_id == company_id,
            LiabilityAllocationRun.pfj_id == pfj_id,
            LiabilityAllocationRun.status == "active",
        )
        .all()
    )
    for run in runs:
        for line in run.lines:
            if line.line_kind == "pending_authorization" and line.obligor_type == "insurer":
                total += Decimal(str(line.amount_inclusive or 0))
    return total
