"""
Reports API — read-only. Branch-scoped item movement report and batch movement report.
"""
from datetime import date
from typing import Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.finance.governance.classification import OPERATIONAL
from app.finance.governance.context import assert_access, resolve_finance_access_context
from app.models import Branch, User
from app.schemas.reports import ItemMovementReportResponse
from app.services.item_movement_report_service import (
    build_item_movement_report,
    build_batch_movement_report,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def get_branch_id_from_session(
    x_branch_id: str = Header(..., alias="X-Branch-ID", description="Current branch (session context)"),
) -> UUID:
    """Require X-Branch-ID header as current branch; return as UUID. Raises 400 if missing or invalid."""
    if not (x_branch_id and str(x_branch_id).strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Branch-ID header is required (current branch from session).",
        )
    try:
        return UUID(str(x_branch_id).strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Branch-ID format.",
        )


def require_operational_report_and_branch(
    user_db: Tuple[User, Session] = Depends(get_current_user),
    branch_id: UUID = Depends(get_branch_id_from_session),
) -> Tuple[User, Session, UUID, Branch]:
    """
    Inventory movement reports: finance.reports.operational + operational classification.
    Branch from session header; enforced via FinanceAccessContext.
    """
    user, db = user_db
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found.")
    ctx = resolve_finance_access_context(user, db, branch.company_id)
    assert_access(
        ctx,
        OPERATIONAL,
        db,
        branch_id=branch_id,
        permission="finance.reports.operational",
        registry_id="reports.item_movement",
    )
    return (user, db, branch_id, branch)


@router.get("/item-movement", response_model=ItemMovementReportResponse)
def get_item_movement_report(
    item_id: UUID = Query(..., description="Item UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    auth: Tuple[User, Session, UUID, Branch] = Depends(require_operational_report_and_branch),
):
    """
    Branch-scoped Item Movement Report. Read-only.
    Branch is taken from session (X-Branch-ID header). Uses only inventory_ledger.
    """
    user, db, branch_id, branch = auth
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date.",
        )
    try:
        report = build_item_movement_report(
            db,
            company_id=branch.company_id,
            branch_id=branch_id,
            item_id=item_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as e:
        err = str(e)
        if err == "item_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found or does not belong to your company.")
        if err == "branch_or_company_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch or company not found.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return report


@router.get("/batch-movement", response_model=ItemMovementReportResponse)
def get_batch_movement_report(
    item_id: UUID = Query(..., description="Item UUID"),
    batch_no: str = Query(..., min_length=1, description="Batch number"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID (defaults to session branch)"),
    auth: Tuple[User, Session, UUID, Branch] = Depends(require_operational_report_and_branch),
):
    """
    Branch-scoped Batch Movement Report. Read-only.
    Optional branch_id must be within FinanceAccessContext allowed branches.
    """
    user, db, session_branch_id, session_branch = auth
    effective_branch_id = branch_id if branch_id is not None else session_branch_id
    branch = (
        db.query(Branch).filter(Branch.id == effective_branch_id).first()
        if effective_branch_id != session_branch_id
        else session_branch
    )
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found.")
    ctx = resolve_finance_access_context(user, db, branch.company_id)
    assert_access(
        ctx,
        OPERATIONAL,
        db,
        branch_id=effective_branch_id,
        permission="finance.reports.operational",
        registry_id="reports.batch_movement",
    )
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date.",
        )
    try:
        report = build_batch_movement_report(
            db,
            company_id=branch.company_id,
            branch_id=effective_branch_id,
            item_id=item_id,
            batch_no=batch_no,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as e:
        err = str(e)
        if err == "item_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found or does not belong to your company.")
        if err == "branch_or_company_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch or company not found.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return report
