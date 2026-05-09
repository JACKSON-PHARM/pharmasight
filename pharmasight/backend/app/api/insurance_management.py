from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.dependencies import get_current_user, get_tenant_db, _user_has_permission
from app.models import (
    InsuranceProvider,
    InsuranceClaim,
    InsuranceSettlement,
    InsuranceSettlementAllocation,
    InsuranceLedgerEntry,
    SalesInvoice,
    Branch,
)
from app.schemas.insurance_management import (
    InsuranceProviderCreate,
    InsuranceProviderUpdate,
    InsuranceProviderResponse,
    InsuranceClaimResponse,
    InsuranceClaimStatusUpdate,
    InsuranceSettlementCreate,
    InsuranceSettlementResponse,
    InsuranceAgingRow,
)
from app.services.cashbook_service import ensure_cashbook_entry_for_insurance_settlement

router = APIRouter()


def _effective_company_id(request: Request) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if not cid:
        raise HTTPException(status_code=403, detail="Company context required")
    return cid


def _claim_no(db: Session, company_id: UUID) -> str:
    n = db.query(func.count(InsuranceClaim.id)).filter(InsuranceClaim.company_id == company_id).scalar() or 0
    return f"ICL-{str(company_id)[:8].upper()}-{int(n) + 1:06d}"


def _settle_no(db: Session, company_id: UUID) -> str:
    n = db.query(func.count(InsuranceSettlement.id)).filter(InsuranceSettlement.company_id == company_id).scalar() or 0
    return f"IST-{str(company_id)[:8].upper()}-{int(n) + 1:06d}"


@router.get("/providers", response_model=list[InsuranceProviderResponse])
def list_providers(
    request: Request,
    active_only: bool = Query(False),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "sales.view"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    q = db.query(InsuranceProvider).filter(InsuranceProvider.company_id == company_id)
    if active_only:
        q = q.filter(InsuranceProvider.is_active == True)
    return q.order_by(InsuranceProvider.name.asc()).all()


@router.post("/providers", response_model=InsuranceProviderResponse, status_code=status.HTTP_201_CREATED)
def create_provider(
    body: InsuranceProviderCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "settings.edit"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    row = InsuranceProvider(company_id=company_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/providers/{provider_id}", response_model=InsuranceProviderResponse)
def update_provider(
    provider_id: UUID,
    body: InsuranceProviderUpdate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "settings.edit"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    row = db.query(InsuranceProvider).filter(InsuranceProvider.id == provider_id, InsuranceProvider.company_id == company_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.get("/claims", response_model=list[InsuranceClaimResponse])
def list_claims(
    request: Request,
    provider_id: Optional[UUID] = Query(None),
    status_filter: Optional[str] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "sales.view"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    q = db.query(InsuranceClaim).filter(InsuranceClaim.company_id == company_id)
    if provider_id:
        q = q.filter(InsuranceClaim.insurance_provider_id == provider_id)
    if status_filter:
        q = q.filter(InsuranceClaim.status == status_filter)
    return q.order_by(InsuranceClaim.created_at.desc()).all()


@router.patch("/claims/{claim_id}/status", response_model=InsuranceClaimResponse)
def update_claim_status(
    claim_id: UUID,
    body: InsuranceClaimStatusUpdate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "sales.edit"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    row = db.query(InsuranceClaim).filter(InsuranceClaim.id == claim_id, InsuranceClaim.company_id == company_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Claim not found")
    row.status = body.status
    if body.approved_amount is not None:
        row.approved_amount = body.approved_amount
    if body.notes is not None:
        row.notes = body.notes
    db.commit()
    db.refresh(row)
    return row


@router.post("/settlements", response_model=InsuranceSettlementResponse, status_code=status.HTTP_201_CREATED)
def create_settlement(
    body: InsuranceSettlementCreate,
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "sales.edit"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    branch = db.query(Branch).filter(Branch.id == body.branch_id, Branch.company_id == company_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    settlement = InsuranceSettlement(
        company_id=company_id,
        branch_id=body.branch_id,
        insurance_provider_id=body.insurance_provider_id,
        settlement_number=_settle_no(db, company_id),
        settlement_date=body.settlement_date,
        method=body.method,
        reference=body.reference,
        amount=body.amount,
        notes=body.notes,
        created_by=user.id,
    )
    db.add(settlement)
    db.flush()
    allocated_total = Decimal("0")
    for alloc in body.allocations:
        claim = db.query(InsuranceClaim).filter(
            InsuranceClaim.id == alloc.insurance_claim_id,
            InsuranceClaim.company_id == company_id,
            InsuranceClaim.insurance_provider_id == body.insurance_provider_id,
        ).with_for_update().first()
        if not claim:
            raise HTTPException(status_code=404, detail=f"Claim not found: {alloc.insurance_claim_id}")
        if alloc.allocated_amount > claim.outstanding_amount:
            raise HTTPException(status_code=400, detail=f"Allocation exceeds claim outstanding: {claim.claim_number}")
        db.add(InsuranceSettlementAllocation(
            insurance_settlement_id=settlement.id,
            insurance_claim_id=claim.id,
            allocated_amount=alloc.allocated_amount,
        ))
        claim.settled_amount = Decimal(str(claim.settled_amount or 0)) + alloc.allocated_amount
        claim.outstanding_amount = Decimal(str(claim.outstanding_amount or 0)) - alloc.allocated_amount
        claim.status = "settled" if claim.outstanding_amount <= Decimal("0.0001") else "partially_settled"
        allocated_total += alloc.allocated_amount
    db.add(InsuranceLedgerEntry(
        company_id=company_id,
        branch_id=body.branch_id,
        insurance_provider_id=body.insurance_provider_id,
        date=body.settlement_date,
        entry_type="settlement",
        reference_id=settlement.id,
        debit=Decimal("0"),
        credit=allocated_total if body.allocations else body.amount,
        notes=body.reference or "Insurance settlement",
    ))
    ensure_cashbook_entry_for_insurance_settlement(db, settlement=settlement)
    db.commit()
    return db.query(InsuranceSettlement).options(selectinload(InsuranceSettlement.allocations)).filter(InsuranceSettlement.id == settlement.id).first()


@router.get("/settlements", response_model=list[InsuranceSettlementResponse])
def list_settlements(
    request: Request,
    provider_id: Optional[UUID] = Query(None),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "sales.view"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    q = db.query(InsuranceSettlement).options(selectinload(InsuranceSettlement.allocations)).filter(InsuranceSettlement.company_id == company_id)
    if provider_id:
        q = q.filter(InsuranceSettlement.insurance_provider_id == provider_id)
    return q.order_by(InsuranceSettlement.settlement_date.desc()).all()


@router.get("/statement")
def insurer_statement(
    request: Request,
    provider_id: UUID = Query(...),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "reports.view"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    rows = db.query(InsuranceLedgerEntry).filter(
        InsuranceLedgerEntry.company_id == company_id,
        InsuranceLedgerEntry.insurance_provider_id == provider_id,
    ).order_by(InsuranceLedgerEntry.date.asc(), InsuranceLedgerEntry.created_at.asc()).all()
    return rows


@router.get("/aging", response_model=list[InsuranceAgingRow])
def insurer_aging(
    request: Request,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user = current_user_and_db[0]
    if not _user_has_permission(db, user.id, "reports.view"):
        raise HTTPException(status_code=403, detail="Permission denied")
    company_id = _effective_company_id(request)
    today = date.today()
    claims = db.query(InsuranceClaim, InsuranceProvider).join(
        InsuranceProvider, InsuranceProvider.id == InsuranceClaim.insurance_provider_id
    ).filter(
        InsuranceClaim.company_id == company_id,
        InsuranceClaim.outstanding_amount > 0,
    ).all()
    buckets = {}
    for claim, provider in claims:
        key = str(provider.id)
        if key not in buckets:
            buckets[key] = {"provider_id": provider.id, "provider_name": provider.name, "current": Decimal("0"), "days_31_60": Decimal("0"), "days_61_90": Decimal("0"), "days_91_plus": Decimal("0")}
        age_days = (today - (claim.due_date or today)).days
        amt = Decimal(str(claim.outstanding_amount or 0))
        if age_days <= 30:
            buckets[key]["current"] += amt
        elif age_days <= 60:
            buckets[key]["days_31_60"] += amt
        elif age_days <= 90:
            buckets[key]["days_61_90"] += amt
        else:
            buckets[key]["days_91_plus"] += amt
    out = []
    for _, v in buckets.items():
        total = v["current"] + v["days_31_60"] + v["days_61_90"] + v["days_91_plus"]
        out.append(InsuranceAgingRow(**v, total=total))
    return sorted(out, key=lambda x: x.total, reverse=True)

