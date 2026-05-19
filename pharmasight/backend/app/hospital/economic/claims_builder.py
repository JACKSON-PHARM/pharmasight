"""
H5 — Build insurance claim from PFJ insurer-obligated charges (claim lines → care_charges).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models.hospital_economic import (
    CareCharge,
    InsuranceClaimLine,
    LiabilityAllocationRun,
    PatientFinancialJourney,
)
from app.models.insurance_financial import InsuranceClaim, InsuranceProvider


def _insurer_obligated_total(db: Session, *, company_id: UUID, pfj_id: UUID) -> Tuple[Decimal, List[Tuple[CareCharge, Decimal]]]:
    total = Decimal("0")
    pairs: List[Tuple[CareCharge, Decimal]] = []
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
    charge_map = {r.care_charge_id: r for r in runs}
    charges = db.query(CareCharge).filter(CareCharge.id.in_(list(charge_map.keys()))).all()
    for charge in charges:
        run = charge_map.get(charge.id)
        if not run:
            continue
        amt = Decimal("0")
        for line in run.lines:
            if line.obligor_type == "insurer" and line.line_kind == "obligated":
                amt += Decimal(str(line.amount_inclusive or 0))
        if amt > 0:
            total += amt
            pairs.append((charge, amt))
    return total, pairs


def build_insurance_claim_from_pfj(
    db: Session,
    *,
    pfj: PatientFinancialJourney,
    insurance_provider_id: UUID,
    sales_invoice_id: UUID,
    created_by: UUID,
    claim_number: Optional[str] = None,
) -> InsuranceClaim:
    provider = (
        db.query(InsuranceProvider)
        .filter(InsuranceProvider.id == insurance_provider_id, InsuranceProvider.company_id == pfj.company_id)
        .first()
    )
    if not provider:
        raise ValueError("Insurance provider not found")

    total, pairs = _insurer_obligated_total(db, company_id=pfj.company_id, pfj_id=pfj.id)
    if total <= 0:
        raise ValueError("No insurer-obligated charges to claim on this PFJ")

    if not claim_number:
        n = db.query(InsuranceClaim).filter(InsuranceClaim.company_id == pfj.company_id).count()
        claim_number = f"PFJ-{str(pfj.id)[:8].upper()}-{n + 1}"

    claim = InsuranceClaim(
        company_id=pfj.company_id,
        branch_id=pfj.branch_id,
        insurance_provider_id=insurance_provider_id,
        sales_invoice_id=sales_invoice_id,
        pfj_id=pfj.id,
        claim_number=claim_number,
        status="submitted",
        billed_amount=total,
        approved_amount=Decimal("0"),
        settled_amount=Decimal("0"),
        outstanding_amount=total,
        created_by=created_by,
    )
    db.add(claim)
    db.flush()

    for charge, amt in pairs:
        db.add(
            InsuranceClaimLine(
                insurance_claim_id=claim.id,
                care_charge_id=charge.id,
                amount_inclusive=amt,
            )
        )
    db.flush()

    try:
        from app.finance.events.hooks import on_insurance_claim_financial_event

        on_insurance_claim_financial_event(db, claim, lifecycle_status=claim.status)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("claim financial hook non-fatal")

    return claim


def resolve_invoice_for_pfj(db: Session, *, pfj_id: UUID, company_id: UUID) -> Optional[UUID]:
    ch = (
        db.query(CareCharge)
        .filter(
            CareCharge.pfj_id == pfj_id,
            CareCharge.company_id == company_id,
            CareCharge.sales_invoice_id.isnot(None),
        )
        .order_by(CareCharge.accrued_at.desc())
        .first()
    )
    return ch.sales_invoice_id if ch else None
