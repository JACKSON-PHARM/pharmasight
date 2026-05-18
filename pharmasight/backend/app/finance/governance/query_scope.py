"""
Deterministic branch query scoping for FinanceAccessContext (E2.5).

Pure functions — no ORM mutation, no hidden context state changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import false

from app.finance.governance.scope import COMPANY_WIDE_SCOPES


class BranchQueryMode(str, Enum):
    UNRESTRICTED_COMPANY = "unrestricted_company"
    FILTER_BRANCHES = "filter_branches"
    DENY_EMPTY = "deny_empty"


@dataclass(frozen=True)
class BranchQueryScope:
    """Resolved branch filter for list/report SQL queries."""

    mode: BranchQueryMode
    branch_ids: FrozenSet[UUID]

    @property
    def must_apply_sql_filter(self) -> bool:
        return self.mode == BranchQueryMode.FILTER_BRANCHES

    @property
    def is_safe_to_query(self) -> bool:
        return self.mode != BranchQueryMode.DENY_EMPTY


def ensure_branch_in_allowed(
    branch_id: UUID,
    allowed_branch_ids: FrozenSet[UUID],
) -> None:
    if branch_id not in allowed_branch_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this branch",
        )


def resolve_branch_query_scope(
    *,
    visibility_scope: str,
    allowed_branch_ids: FrozenSet[UUID],
    branch_id: Optional[UUID] = None,
) -> BranchQueryScope:
    """
    Resolve how list/report queries must constrain branch_id.

    Never treat an empty allowed set as "all branches".
    """
    if branch_id is not None:
        ensure_branch_in_allowed(branch_id, allowed_branch_ids)
        return BranchQueryScope(
            mode=BranchQueryMode.FILTER_BRANCHES,
            branch_ids=frozenset({branch_id}),
        )

    if not allowed_branch_ids:
        return BranchQueryScope(mode=BranchQueryMode.DENY_EMPTY, branch_ids=frozenset())

    if visibility_scope in COMPANY_WIDE_SCOPES:
        return BranchQueryScope(
            mode=BranchQueryMode.UNRESTRICTED_COMPANY,
            branch_ids=allowed_branch_ids,
        )

    return BranchQueryScope(
        mode=BranchQueryMode.FILTER_BRANCHES,
        branch_ids=allowed_branch_ids,
    )


def branch_ids_for_query_from_scope(scope: BranchQueryScope) -> Optional[FrozenSet[UUID]]:
    """Return branch ids for SQL .in_() filter, or None when company-wide unrestricted."""
    if scope.mode == BranchQueryMode.UNRESTRICTED_COMPANY:
        return None
    if scope.mode == BranchQueryMode.DENY_EMPTY:
        return frozenset()
    return scope.branch_ids


def apply_branch_query_scope(query, branch_column, scope: BranchQueryScope):
    """Apply deterministic branch filtering to a SQLAlchemy query."""
    if scope.mode == BranchQueryMode.UNRESTRICTED_COMPANY:
        return query
    if scope.mode == BranchQueryMode.DENY_EMPTY:
        return query.filter(false())
    return query.filter(branch_column.in_(scope.branch_ids))
