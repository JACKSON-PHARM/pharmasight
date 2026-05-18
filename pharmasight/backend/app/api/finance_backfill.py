"""
Controlled financial event backfill API (E5).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_tenant_db
from app.finance.events.backfill import run_controlled_backfill
from app.finance.governance.access import deny_unless_finance_permission, resolve_finance_branch_id
from app.finance.governance.classification import BRANCH_FINANCE
from app.finance.governance.request_context import bind_fastapi_request
from app.models import User
from app.models.finance_backfill import FinanceBackfillRun
from app.schemas.finance_e5 import BackfillRunRequest, BackfillRunResponse

router = APIRouter(prefix="/finance/backfill", tags=["Finance Backfill"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.post("/runs", response_model=BackfillRunResponse)
def start_backfill_run(
    body: BackfillRunRequest,
    request: Request,
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    ctx = deny_unless_finance_permission(
        db, user, company_id, "finance.reports.audit_read", BRANCH_FINANCE,
        registry_id="finance.backfill.run",
    )
    resolve_finance_branch_id(
        ctx,
        db,
        branch_id_query=body.branch_id,
        classification=BRANCH_FINANCE,
        permission="finance.reports.audit_read",
        registry_id="finance.backfill.run",
    )
    try:
        outcome = run_controlled_backfill(
            db,
            company_id=company_id,
            branch_id=body.branch_id,
            date_from=body.date_from,
            date_to=body.date_to,
            actor_user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    run = db.query(FinanceBackfillRun).filter(FinanceBackfillRun.id == outcome.run_id).first()
    return BackfillRunResponse(
        run_id=outcome.run_id,
        status=outcome.status,
        events_created=outcome.events_created,
        events_duplicate=outcome.events_duplicate,
        events_failed=outcome.events_failed,
        correlation_group=run.correlation_group if run else None,
        policy_pack_id=run.policy_pack_id if run else None,
    )
