"""
Branch-scoped wholesale operations: company license + WHOLESALE_DISTRIBUTION doctrine.
"""
from __future__ import annotations

from typing import Callable, Tuple
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import ensure_user_has_branch_access, get_current_user, get_effective_company_id_for_user
from app.models.company import Branch
from app.models.user import User
from app.module_enforcement import is_module_enabled_for_company
from app.services.invoice_workflow_policy import is_wholesale_distribution_branch


def get_branch_id_from_session(
    x_branch_id: str = Header(..., alias="X-Branch-ID", description="Current branch (session context)"),
) -> UUID:
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


def require_wholesale_distribution_branch() -> Callable[..., Tuple[User, Session, UUID]]:
    """
    Company must have wholesale module; session branch must use WHOLESALE_DISTRIBUTION doctrine.
    """

    def _dependency(
        user_db: Tuple[User, Session] = Depends(get_current_user),
        branch_id: UUID = Depends(get_branch_id_from_session),
    ) -> Tuple[User, Session, UUID]:
        user, db = user_db
        company_id = get_effective_company_id_for_user(db, user)
        if company_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot resolve company for wholesale access",
            )
        if not is_module_enabled_for_company(db, company_id, "wholesale"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Wholesale module is not enabled for this company",
            )
        branch = (
            db.query(Branch)
            .filter(Branch.id == branch_id, Branch.company_id == company_id)
            .first()
        )
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found for this company",
            )
        ensure_user_has_branch_access(db, user.id, branch_id)
        if not is_wholesale_distribution_branch(db, branch_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Wholesale customer operations require a branch with "
                    "Wholesale distribution fiscal doctrine."
                ),
            )
        return user, db, branch_id

    return _dependency
