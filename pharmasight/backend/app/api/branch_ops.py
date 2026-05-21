"""
Branch operational backlog API (unposted prior-date documents).
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import (
    ensure_ops_branch_access,
    get_authenticated_db,
    get_effective_company_id_from_request,
)
from app.models.company import Branch
from app.services.branch_operational_backlog import fetch_branch_operational_backlog

router = APIRouter(prefix="/branch-ops", tags=["Branch Operations"])


@router.get("/branch/{branch_id}/operational-backlog")
def get_branch_operational_backlog(
    branch_id: UUID,
    request: Request,
    business_date: Optional[date] = Query(
        None,
        description="Business date for today’s session (defaults to calendar today).",
    ),
    user_db: tuple = Depends(get_authenticated_db),
):
    """
    Prior-date unposted documents for the branch.
    blocking_documents affect stock workflows; informational_documents are listed only.
    """
    user, db = user_db
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    effective_company_id = get_effective_company_id_from_request(request, db, user)
    if effective_company_id is None or str(branch.company_id) != str(effective_company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this branch.")
    ensure_ops_branch_access(db, user.id, branch.company_id, branch_id, permission_name="items.view")
    biz = business_date or date.today()
    return fetch_branch_operational_backlog(db, branch.company_id, branch_id, biz)
