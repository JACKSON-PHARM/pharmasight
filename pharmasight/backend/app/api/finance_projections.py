"""
Governed financial projections API (E5) — derived views only.
"""
from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.doctrine.projection import PROJECTION_INVARIANTS
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.request_context import bind_fastapi_request
from app.finance.projections.engine import execute_projection
from app.finance.projections.registry import get_projection_spec, introspect_projection_registry
from app.models import User
from app.schemas.finance_e5 import ProjectionExecuteResponse

router = APIRouter(prefix="/finance/projections", tags=["Finance Projections"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/registry")
def list_projection_registry(
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    guard_finance_report_access(
        db, user, company_id, "finance.reports.audit_read", "branch_finance"
    )
    return {
        "projections": introspect_projection_registry(),
        "doctrine": {
            "invariants": sorted(PROJECTION_INVARIANTS),
            "derived_only": True,
            "authoritative": False,
            "mutable_balances_forbidden": True,
            "doctrine_api": "/api/finance/doctrine",
        },
    }


@router.get("/{projection_id}", response_model=ProjectionExecuteResponse)
def run_projection(
    projection_id: str,
    request: Request,
    branch_id: Optional[UUID] = Query(None),
    since: Optional[date] = Query(None),
    until: Optional[date] = Query(None),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    try:
        spec = get_projection_spec(projection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown projection: {projection_id}")
    guard_finance_report_access(db, user, company_id, spec.permission, spec.classification)
    if spec.branch_scoped and branch_id is None:
        raise HTTPException(status_code=400, detail="branch_id required for this projection")
    data = execute_projection(
        db,
        projection_id=projection_id,
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )
    return ProjectionExecuteResponse(
        projection_id=projection_id,
        derived=True,
        authoritative=False,
        data=data,
    )
