"""
Deprecated branch helpers — delegate to FinanceAccessContext only (E2.5).

Do not add new callers; use resolve_finance_access_context + assert_access.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.finance.governance.classification import OPERATIONAL, normalize_classification
from app.finance.governance.context import assert_access, resolve_finance_access_context
from app.models import Branch, User


def assert_finance_branch_access(
    db: Session,
    *,
    user_id: UUID,
    company_id: UUID,
    branch_id: UUID,
    classification: str = OPERATIONAL,
    registry_id: str | None = None,
) -> Branch:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found",
        )
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch or branch.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found",
        )
    ctx = resolve_finance_access_context(user, db, company_id)
    assert_access(
        ctx,
        normalize_classification(classification),
        db,
        branch_id=branch_id,
        registry_id=registry_id,
    )
    return branch


def assert_finance_branch_access_optional(
    db: Session,
    *,
    user_id: UUID,
    company_id: UUID,
    branch_id: UUID | None,
    classification: str = OPERATIONAL,
    registry_id: str | None = None,
) -> None:
    if branch_id is None:
        return
    assert_finance_branch_access(
        db,
        user_id=user_id,
        company_id=company_id,
        branch_id=branch_id,
        classification=classification,
        registry_id=registry_id,
    )
