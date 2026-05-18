"""
ReportContext — thin wrapper around FinanceAccessContext (E2 / E2.5).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional
from uuid import UUID

from app.finance.governance.access_context import FinanceAccessContext
from app.finance.governance.query_scope import BranchQueryScope


@dataclass(frozen=True)
class ReportContext:
    access: FinanceAccessContext

    @property
    def company_id(self) -> UUID:
        return self.access.company_id

    @property
    def visibility_scope(self) -> str:
        return self.access.visibility_scope

    @property
    def max_classification(self) -> str:
        return self.access.max_classification

    @property
    def allowed_branch_ids(self) -> FrozenSet[UUID]:
        return self.access.allowed_branch_ids

    @classmethod
    def from_access(cls, access: FinanceAccessContext) -> ReportContext:
        return cls(access=access)

    def resolve_branch_query_scope(
        self, branch_id: Optional[UUID] = None
    ) -> BranchQueryScope:
        return self.access.resolve_branch_query_scope(branch_id)

    def branch_ids_for_query(
        self, branch_id: Optional[UUID] = None
    ) -> Optional[FrozenSet[UUID]]:
        return self.access.branch_ids_for_query(branch_id)

    def apply_branch_filter(self, query, branch_column, branch_id: Optional[UUID] = None):
        return self.access.apply_branch_filter(query, branch_column, branch_id)
