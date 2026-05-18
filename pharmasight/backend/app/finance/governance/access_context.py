"""
FinanceAccessContext dataclass (E2.5) — immutable authorization state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional
from uuid import UUID

from app.finance.governance.query_scope import (
    BranchQueryScope,
    apply_branch_query_scope,
    branch_ids_for_query_from_scope,
    resolve_branch_query_scope,
)


@dataclass(frozen=True)
class FinanceAccessContext:
    """Immutable finance authorization state for a user within a company."""

    user_id: UUID
    company_id: UUID
    visibility_scope: str
    allowed_branch_ids: FrozenSet[UUID]
    allowed_department_ids: Optional[FrozenSet[UUID]]
    max_classification: str

    def resolve_branch_query_scope(
        self, branch_id: Optional[UUID] = None
    ) -> BranchQueryScope:
        return resolve_branch_query_scope(
            visibility_scope=self.visibility_scope,
            allowed_branch_ids=self.allowed_branch_ids,
            branch_id=branch_id,
        )

    def branch_ids_for_query(
        self, branch_id: Optional[UUID] = None
    ) -> Optional[FrozenSet[UUID]]:
        scope = self.resolve_branch_query_scope(branch_id)
        if not scope.is_safe_to_query:
            return frozenset()
        return branch_ids_for_query_from_scope(scope)

    def apply_branch_filter(self, query, branch_column, branch_id: Optional[UUID] = None):
        scope = self.resolve_branch_query_scope(branch_id)
        return apply_branch_query_scope(query, branch_column, scope)
