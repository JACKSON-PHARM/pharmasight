"""
Operational financial intelligence API — confidence, recovery exposure.

Governance and lineage remain traceable underneath; intelligence surfaces are
operational narratives, not authoritative ledgers.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.classification import BRANCH_FINANCE, MANAGEMENT
from app.finance.governance.request_context import bind_fastapi_request
from app.finance.intelligence.branch_confidence import (
    assess_branch_financial_confidence,
    default_confidence_period,
)
from app.finance.intelligence.recovery_exposure import build_recovery_exposure_intelligence
from app.models import User
from app.schemas.finance_intelligence import (
    BranchConfidenceResponse,
    RecoveryExposureResponse,
)

router = APIRouter(prefix="/finance/intelligence", tags=["Finance Intelligence"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/branch-confidence", response_model=BranchConfidenceResponse)
def get_branch_financial_confidence(
    request: Request,
    branch_id: UUID = Query(..., description="Branch scope"),
    since: date | None = Query(None, description="Assessment period start"),
    until: date | None = Query(None, description="Assessment period end"),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Branch Financial Confidence Index — progressive authority gate.

    Does not elevate projections to authoritative; exposes maturity for operational UX.
    """
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    if until is None:
        until = date.today()
    if since is None:
        since, _ = default_confidence_period(until=until)
    if since > until:
        raise HTTPException(status_code=400, detail="since must be <= until")

    guard_finance_report_access(
        db,
        user,
        company_id,
        "finance.reports.management",
        MANAGEMENT,
        branch_id=branch_id,
    )

    data = assess_branch_financial_confidence(
        db,
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )
    return BranchConfidenceResponse.model_validate(data)


@router.get("/recovery-exposure", response_model=RecoveryExposureResponse)
def get_recovery_exposure_intelligence(
    request: Request,
    branch_id: UUID = Query(..., description="Branch scope"),
    since: date = Query(..., description="Lineage summary period start"),
    until: date = Query(..., description="Lineage summary period end"),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Revenue Recovery & Exposure Intelligence — who owes us, aging risk, payer delay.

    Open balances from operational records; period movement from lineage projections.
    """
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    if since > until:
        raise HTTPException(status_code=400, detail="since must be <= until")

    guard_finance_report_access(
        db,
        user,
        company_id,
        "finance.reports.management",
        MANAGEMENT,
        branch_id=branch_id,
    )

    data = build_recovery_exposure_intelligence(
        db,
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )
    return RecoveryExposureResponse.model_validate(data)
