"""
Operational Financial Command Center API — business-facing financial state.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.dependencies import get_current_user, get_tenant_db
from app.finance.command_center.overview import build_command_center_overview
from app.finance.governance.access import guard_finance_report_access
from app.finance.governance.classification import MANAGEMENT
from app.finance.governance.request_context import bind_fastapi_request
from app.models import User
from app.schemas.finance_command_center import CommandCenterOverviewResponse

router = APIRouter(prefix="/finance/command-center", tags=["Finance Command Center"])


def _company_id(request: Request, db: Session, user: User) -> UUID:
    cid = getattr(request.state, "effective_company_id", None)
    if cid is not None:
        return cid
    from app.dependencies import get_effective_company_id_for_user

    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(status_code=400, detail="Company context not available")
    return cid


@router.get("/overview", response_model=CommandCenterOverviewResponse)
def get_command_center_overview(
    request: Request,
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    branch_id: Optional[UUID] = Query(None, description="Scope; omit for company-wide position"),
    user_db=Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Executive financial position: liquidity, AR/AP, profit, branch ranking, top debtors/creditors.
    GL-authoritative amounts where posted; subledgers for control reconciliation.
    """
    bind_fastapi_request(request)
    user, _ = user_db
    company_id = _company_id(request, db, user)
    today = date.today()
    fd = from_date or date(today.year, today.month, 1)
    td = to_date or today
    if fd > td:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")

    guard_finance_report_access(
        db, user, company_id, "accounting.reports", MANAGEMENT, branch_id=branch_id
    )

    try:
        data = build_command_center_overview(
            db,
            company_id=company_id,
            branch_id=branch_id,
            from_date=fd,
            to_date=td,
        )
        return CommandCenterOverviewResponse(**data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("command-center overview failed company_id=%s branch_id=%s", company_id, branch_id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not build financial overview: {exc}",
        ) from exc
