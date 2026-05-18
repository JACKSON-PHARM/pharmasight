"""
Finance context resolution (E2 / E2.5).

resolve_finance_access_context() is the sole resolution authority.
"""
from __future__ import annotations

from typing import FrozenSet, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.classification import (
    effective_max_classification,
    normalize_classification,
)
from app.finance.governance.enforcement import assert_finance_access
from app.finance.governance.scope import (
    ALL_VISIBILITY_SCOPES,
    COMPANY_WIDE_SCOPES,
    effective_scope,
)
from app.models import Branch, User, UserBranchRole


def _normalize_scope(value: Optional[str]) -> str:
    raw = (value or "BRANCH").strip().upper()
    if raw not in ALL_VISIBILITY_SCOPES:
        return "BRANCH"
    return raw


def resolve_finance_access_context(
    user: User,
    db: Session,
    company_id: UUID,
) -> FinanceAccessContext:
    """
    Build FinanceAccessContext from user_branch_roles for the company.

    Raises 403 when the user has no branch assignments in the company.
    """
    rows = (
        db.query(UserBranchRole)
        .join(Branch, Branch.id == UserBranchRole.branch_id)
        .filter(
            UserBranchRole.user_id == user.id,
            Branch.company_id == company_id,
        )
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No branch access for this company",
        )

    scopes = [_normalize_scope(getattr(r, "finance_visibility_scope", None)) for r in rows]
    classifications = [
        normalize_classification(getattr(r, "max_finance_classification", None))
        for r in rows
    ]
    vis = effective_scope(scopes)
    max_cls = effective_max_classification(classifications)

    assigned_branch_ids = frozenset(r.branch_id for r in rows)

    dept_ids: set[UUID] = set()
    for r in rows:
        dept_id = getattr(r, "department_store_id", None)
        if dept_id is not None:
            dept_ids.add(dept_id)

    if vis in COMPANY_WIDE_SCOPES:
        company_branch_ids = frozenset(
            b[0]
            for b in db.query(Branch.id).filter(Branch.company_id == company_id).all()
        )
        allowed_branches = company_branch_ids if company_branch_ids else assigned_branch_ids
        allowed_departments: Optional[FrozenSet[UUID]] = None
    else:
        allowed_branches = assigned_branch_ids
        if vis == "DEPARTMENT":
            allowed_departments = frozenset(dept_ids) if dept_ids else frozenset()
        else:
            allowed_departments = frozenset(dept_ids) if dept_ids else None

    return FinanceAccessContext(
        user_id=user.id,
        company_id=company_id,
        visibility_scope=vis,
        allowed_branch_ids=allowed_branches,
        allowed_department_ids=allowed_departments,
        max_classification=max_cls,
    )


def assert_access(
    ctx: FinanceAccessContext,
    classification: str,
    db: Session,
    *,
    branch_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    permission: Optional[str] = None,
    registry_id: Optional[str] = None,
) -> None:
    """Delegate to central enforcement (telemetry + registry metadata)."""
    assert_finance_access(
        ctx,
        classification,
        db,
        branch_id=branch_id,
        department_id=department_id,
        permission=permission,
        registry_id=registry_id,
    )
