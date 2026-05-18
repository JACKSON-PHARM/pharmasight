"""
Finance shadow reconciliation API (Stage 2A) — treasury movement validation.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.classification import MANAGEMENT
from app.finance.governance.request_context import bind_fastapi_request
from app.finance.reconciliation.lineage_coverage import introspect_lineage_coverage_matrix
from app.finance.reconciliation.treasury_movement import reconcile_treasury_movement
from app.models import User
from app.schemas.finance_reconciliation import TreasuryMovementReconciliationResponse

router = APIRouter(prefix="/finance/reconciliation", tags=["Finance Reconciliation"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/treasury-movement", response_model=TreasuryMovementReconciliationResponse)
def get_treasury_movement_reconciliation(
    request: Request,
    branch_id: UUID = Query(..., description="Branch scope"),
    since: date = Query(..., description="Period start (inclusive)"),
    until: date = Query(..., description="Period end (inclusive)"),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Shadow replacement: legacy cashbook vs branch_cash_movement projection with drift taxonomy.
    Reconciliation validates lineage; it does not elevate legacy aggregates as truth.
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
    guard_finance_report_access(
        db,
        user,
        company_id,
        "finance.cashbook.view_branch",
        "branch_finance",
        branch_id=branch_id,
    )

    data = reconcile_treasury_movement(
        db,
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )
    return TreasuryMovementReconciliationResponse.model_validate(data)


@router.get("/coverage-matrix")
def get_lineage_coverage_matrix(
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Operational workflow → expected lineage mapping (governance metadata)."""
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(
        db, user, company_id, "finance.reports.management", MANAGEMENT
    )
    return {
        "workflows": introspect_lineage_coverage_matrix(),
        "doctrine": {
            "legacy_cashbook_observational_only": True,
            "projections_derived_from_lineage": True,
            "reconciliation_validates_adoption": True,
        },
    }
