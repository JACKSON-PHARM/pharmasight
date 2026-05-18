"""
Derived economic semantics API (E6.5) — read-only, non-authoritative.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.classification import BRANCH_FINANCE, CONFIDENTIAL, MANAGEMENT
from app.finance.governance.request_context import bind_fastapi_request
from app.finance.semantics.exposure import derive_exposure_for_accrual_event
from app.models import User
from app.models.financial_event import FinancialEvent

router = APIRouter(prefix="/finance/semantics", tags=["Finance Semantics"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/exposure/{accrual_event_id}")
def get_derived_exposure(
    accrual_event_id: UUID,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    event = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.id == accrual_event_id, FinancialEvent.company_id == company_id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Financial event not found")
    classification = event.classification or BRANCH_FINANCE
    if classification == "confidential":
        guard_finance_report_access(db, user, company_id, "finance.reports.management", CONFIDENTIAL)
    else:
        guard_finance_report_access(db, user, company_id, "finance.reports.management", MANAGEMENT)
    state = derive_exposure_for_accrual_event(
        db, company_id=company_id, accrual_event_id=accrual_event_id
    )
    return {
        "derived": True,
        "authoritative": False,
        "exposure": state,
    }
