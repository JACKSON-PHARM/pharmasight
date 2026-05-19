"""
Hospital Economic Kernel API — PFJ, charges, liability (H1–H2).

No billing UI; read/debug and kernel integration only.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_current_user, get_tenant_db
from app.hospital.economic.liability_engine import (
    ObligorSlice,
    allocate_charge_liability,
    get_active_allocation_run,
    summarize_pfj_liability,
)
from app.hospital.economic.authorization_engine import decide_authorization, list_authorizations, request_authorization
from app.hospital.economic.claims_builder import build_insurance_claim_from_pfj, resolve_invoice_for_pfj
from app.hospital.economic.coverage_service import get_primary_coverage, upsert_primary_coverage
from app.hospital.economic.discharge_service import close_pfj_financial
from app.hospital.economic.pfj_service import get_active_pfj_for_patient, get_pfj_scoped
from app.hospital.economic.recognition_engine import recognize_pfj_obligor_portion
from app.hospital.economic.timeline import build_pfj_timeline
from app.hospital.economic.workspace import build_patient_workspace
from app.models.hospital_economic import PatientFinancialJourney
from app.models import User
from app.models.hospital_economic import CareCharge, LiabilityAllocationRun
from app.schemas.hospital_economic import (
    CareChargeResponse,
    CoverageProfileResponse,
    CoverageProfileUpsert,
    LiabilityAllocationResponse,
    LiabilityLineResponse,
    LiabilityReallocateRequest,
    PFJLiabilitySummaryResponse,
    PFJResponse,
    PFJTimelineResponse,
)

router = APIRouter(prefix="/hospital/economic", tags=["Hospital Economic Kernel"])


def _company_id(db: Session, user: User) -> UUID:
    from app.api.clinic import _company_id as clinic_company_id

    return clinic_company_id(db, user)


def _run_to_response(run: LiabilityAllocationRun) -> LiabilityAllocationResponse:
    return LiabilityAllocationResponse(
        run_id=run.id,
        care_charge_id=run.care_charge_id,
        version=run.version,
        allocation_reason=run.allocation_reason,
        gross_amount_inclusive=run.gross_amount_inclusive,
        lines=[
            LiabilityLineResponse(
                obligor_type=ln.obligor_type,
                amount_inclusive=ln.amount_inclusive,
                line_kind=ln.line_kind,
                insurance_provider_id=ln.insurance_provider_id,
                employer_ref=ln.employer_ref,
            )
            for ln in (run.lines or [])
        ],
    )


@router.get("/pfj/{pfj_id}", response_model=PFJResponse)
def get_pfj(
    pfj_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    pfj = get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id)
    if not pfj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PFJ not found")
    return pfj


@router.get("/pfj/for-patient/{patient_id}/active", response_model=Optional[PFJResponse])
def get_active_pfj_for_patient_endpoint(
    patient_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    return get_active_pfj_for_patient(db, company_id=company_id, patient_id=patient_id)


@router.get("/pfj/{pfj_id}/timeline", response_model=PFJTimelineResponse)
def get_pfj_timeline(
    pfj_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PFJ not found")
    events = build_pfj_timeline(db, pfj_id=pfj_id, company_id=company_id)
    return PFJTimelineResponse(pfj_id=pfj_id, events=events)


@router.get("/pfj/{pfj_id}/liability-summary", response_model=PFJLiabilitySummaryResponse)
def get_pfj_liability_summary(
    pfj_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PFJ not found")
    totals = summarize_pfj_liability(db, company_id=company_id, pfj_id=pfj_id)
    return PFJLiabilitySummaryResponse(pfj_id=pfj_id, obligor_totals=totals)


@router.get("/pfj/{pfj_id}/coverage", response_model=Optional[CoverageProfileResponse])
def get_pfj_coverage(
    pfj_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PFJ not found")
    return get_primary_coverage(db, company_id=company_id, pfj_id=pfj_id)


@router.put("/pfj/{pfj_id}/coverage", response_model=CoverageProfileResponse)
def upsert_pfj_coverage(
    pfj_id: UUID,
    body: CoverageProfileUpsert,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PFJ not found")
    route = (body.obligor_route or "").strip().lower()
    if route not in ("self_pay", "insurance", "employer", "mixed"):
        raise HTTPException(status_code=400, detail="Invalid obligor_route")
    profile = upsert_primary_coverage(
        db,
        company_id=company_id,
        pfj_id=pfj_id,
        obligor_route=route,
        insurance_provider_id=body.insurance_provider_id,
        employer_name=body.employer_name,
        member_id=body.member_id,
        policy_number=body.policy_number,
        insurer_coverage_percent=body.insurer_coverage_percent,
        patient_copay_percent=body.patient_copay_percent,
        patient_copay_fixed=body.patient_copay_fixed,
    )
    from app.hospital.economic.authorization_engine import _refresh_pfj_liability_after_auth

    _refresh_pfj_liability_after_auth(db, pfj_id=pfj_id, company_id=company_id)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/charges", response_model=List[CareChargeResponse])
def list_care_charges(
    pfj_id: Optional[UUID] = Query(None),
    encounter_id: Optional[UUID] = Query(None),
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not pfj_id and not encounter_id:
        raise HTTPException(status_code=400, detail="Provide pfj_id or encounter_id")
    q = db.query(CareCharge).filter(CareCharge.company_id == company_id)
    if pfj_id:
        q = q.filter(CareCharge.pfj_id == pfj_id)
    if encounter_id:
        q = q.filter(CareCharge.encounter_id == encounter_id)
    rows = q.order_by(CareCharge.accrued_at.desc()).limit(500).all()
    return [
        CareChargeResponse(
            id=r.id,
            pfj_id=r.pfj_id,
            encounter_id=r.encounter_id,
            charge_kind=r.charge_kind,
            accrual_status=r.accrual_status,
            clinical_trigger=r.clinical_trigger,
            description=r.description,
            amount_exclusive=r.amount_exclusive,
            vat_amount=r.vat_amount,
            amount_inclusive=r.amount_inclusive,
            accrued_at=r.accrued_at,
            sales_invoice_id=r.sales_invoice_id,
            bridge_only=bool(r.sales_invoice_id),
        )
        for r in rows
    ]


@router.get("/charges/{charge_id}/liability", response_model=Optional[LiabilityAllocationResponse])
def get_charge_liability(
    charge_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    charge = db.query(CareCharge).filter(CareCharge.id == charge_id, CareCharge.company_id == company_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Charge not found")
    run = get_active_allocation_run(db, company_id=company_id, care_charge_id=charge_id)
    if not run:
        return None
    return _run_to_response(run)


@router.post("/charges/{charge_id}/reallocate", response_model=LiabilityAllocationResponse)
def reallocate_charge_liability(
    charge_id: UUID,
    body: LiabilityReallocateRequest,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    charge = db.query(CareCharge).filter(CareCharge.id == charge_id, CareCharge.company_id == company_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Charge not found")
    gross = Decimal(str(charge.amount_inclusive or 0))
    slices = [
        ObligorSlice(
            obligor_type=s.obligor_type,
            amount_inclusive=Decimal(str(s.amount_inclusive)),
            insurance_provider_id=s.insurance_provider_id,
            employer_ref=s.employer_ref,
            line_kind=s.line_kind or "obligated",
        )
        for s in body.slices
    ]
    total = sum(s.amount_inclusive for s in slices)
    if total != gross:
        raise HTTPException(
            status_code=400,
            detail=f"Slices must sum to charge gross {gross}; got {total}",
        )
    try:
        run = allocate_charge_liability(
            db,
            charge_id,
            reason=(body.reason or "manual").strip() or "manual",
            created_by=user.id,
            slices=slices,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not run:
        raise HTTPException(status_code=400, detail="Could not allocate liability")
    db.commit()
    run = (
        db.query(LiabilityAllocationRun)
        .options(joinedload(LiabilityAllocationRun.lines))
        .filter(LiabilityAllocationRun.id == run.id)
        .first()
    )
    return _run_to_response(run)


@router.get("/patients/{patient_id}/workspace")
def get_patient_workspace(
    patient_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    data = build_patient_workspace(db, company_id=company_id, patient_id=patient_id)
    if not data.get("patient"):
        raise HTTPException(status_code=404, detail="Patient not found")
    return data


@router.post("/pfj/{pfj_id}/authorizations")
def create_authorization(
    pfj_id: UUID,
    body: dict,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=404, detail="PFJ not found")
    row = request_authorization(
        db,
        company_id=company_id,
        pfj_id=pfj_id,
        requested_amount=Decimal(str(body.get("requested_amount") or 0)),
        insurance_provider_id=body.get("insurance_provider_id"),
        care_charge_id=body.get("care_charge_id"),
        reference_number=body.get("reference_number"),
        notes=body.get("notes"),
        created_by=user.id,
    )
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.patch("/authorizations/{authorization_id}")
def patch_authorization(
    authorization_id: UUID,
    body: dict,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    try:
        row = decide_authorization(
            db,
            authorization_id=authorization_id,
            company_id=company_id,
            status=body.get("status"),
            approved_amount=Decimal(str(body["approved_amount"])) if body.get("approved_amount") is not None else None,
            decided_by=user.id,
            notes=body.get("notes"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/pfj/{pfj_id}/recognize/patient")
def recognize_patient_portion(
    pfj_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=404, detail="PFJ not found")
    recs = recognize_pfj_obligor_portion(db, company_id=company_id, pfj_id=pfj_id, obligor_type="patient")
    db.commit()
    return {"recognized_count": len(recs)}


@router.post("/pfj/{pfj_id}/recognize/insurer")
def recognize_insurer_portion(
    pfj_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    if not get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id):
        raise HTTPException(status_code=404, detail="PFJ not found")
    recs = recognize_pfj_obligor_portion(db, company_id=company_id, pfj_id=pfj_id, obligor_type="insurer")
    db.commit()
    return {"recognized_count": len(recs)}


@router.post("/pfj/{pfj_id}/build-claim")
def build_claim(
    pfj_id: UUID,
    body: dict,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    pfj = get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id)
    if not pfj:
        raise HTTPException(status_code=404, detail="PFJ not found")
    cov = get_primary_coverage(db, company_id=company_id, pfj_id=pfj_id)
    provider_id = body.get("insurance_provider_id") or (cov.insurance_provider_id if cov else None)
    if not provider_id:
        raise HTTPException(status_code=400, detail="insurance_provider_id required")
    invoice_id = body.get("sales_invoice_id") or resolve_invoice_for_pfj(db, pfj_id=pfj_id, company_id=company_id)
    if not invoice_id:
        raise HTTPException(status_code=400, detail="No bridge invoice on PFJ — create an OPD encounter first")
    try:
        claim = build_insurance_claim_from_pfj(
            db,
            pfj=pfj,
            insurance_provider_id=provider_id,
            sales_invoice_id=invoice_id,
            created_by=user.id,
            claim_number=body.get("claim_number"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"claim_id": str(claim.id), "claim_number": claim.claim_number, "billed_amount": str(claim.billed_amount)}


@router.post("/pfj/{pfj_id}/discharge")
def discharge_pfj(
    pfj_id: UUID,
    body: dict,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    pfj = get_pfj_scoped(db, pfj_id=pfj_id, company_id=company_id)
    if not pfj:
        raise HTTPException(status_code=404, detail="PFJ not found")
    record = close_pfj_financial(db, pfj=pfj, closed_by=user.id, notes=body.get("notes"))
    db.commit()
    return {
        "pfj_status": pfj.status,
        "patient_residual": str(record.patient_residual),
        "insurer_outstanding": str(record.insurer_outstanding),
    }
