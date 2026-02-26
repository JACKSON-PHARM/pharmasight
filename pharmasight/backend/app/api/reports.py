"""
Reports API — read-only. Branch-scoped item movement report.
"""
from datetime import date
from typing import Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, _user_has_permission
from app.models import Branch, User, UserBranchRole
from app.schemas.reports import ItemMovementReportResponse
from app.services.item_movement_report_service import build_item_movement_report

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


def require_reports_view_and_branch(
    user_db: Tuple[User, Session] = Depends(get_current_user),
    branch_id: UUID = Depends(get_branch_id_from_session),
) -> Tuple[User, Session, UUID]:
    """
    Require authenticated user with reports.view permission and valid branch access.
    Branch must be from session (X-Branch-ID). User must have a role at that branch.
    """
    user, db = user_db
    if not _user_has_permission(db, user.id, "reports.view"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission reports.view required to view this report.",
        )
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found.")
    has_branch_access = db.query(UserBranchRole).filter(
        UserBranchRole.user_id == user.id,
        UserBranchRole.branch_id == branch_id,
    ).first() is not None
    if not has_branch_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this branch.",
        )
    return (user, db, branch_id)


@router.get("/item-movement", response_model=ItemMovementReportResponse)
def get_item_movement_report(
    item_id: UUID = Query(..., description="Item UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    auth: Tuple[User, Session, UUID] = Depends(require_reports_view_and_branch),
):
    """
    Branch-scoped Item Movement Report. Read-only.
    Branch is taken from session (X-Branch-ID header). Uses only inventory_ledger.
    """
    user, db, branch_id = auth
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date.",
        )
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found.")
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
