"""
Finance visibility scopes (E2).
"""
from __future__ import annotations

from typing import FrozenSet

FinanceVisibilityScope = str

SELF: FinanceVisibilityScope = "SELF"
TILL: FinanceVisibilityScope = "TILL"
DEPARTMENT: FinanceVisibilityScope = "DEPARTMENT"
BRANCH: FinanceVisibilityScope = "BRANCH"
MULTI_BRANCH: FinanceVisibilityScope = "MULTI_BRANCH"
COMPANY: FinanceVisibilityScope = "COMPANY"
AUDIT_READ: FinanceVisibilityScope = "AUDIT_READ"

ALL_VISIBILITY_SCOPES: FrozenSet[str] = frozenset(
    {
        SELF,
        TILL,
        DEPARTMENT,
        BRANCH,
        MULTI_BRANCH,
        COMPANY,
        AUDIT_READ,
    }
)

SCOPE_RANK: dict[str, int] = {
    SELF: 0,
    TILL: 1,
    DEPARTMENT: 2,
    BRANCH: 3,
    MULTI_BRANCH: 4,
    COMPANY: 5,
    AUDIT_READ: 5,
}

COMPANY_WIDE_SCOPES: FrozenSet[str] = frozenset({COMPANY, AUDIT_READ})


def scope_rank(value: str) -> int:
    key = (value or "").strip().upper()
    if key not in SCOPE_RANK:
        raise ValueError(f"Unknown finance visibility scope: {value}")
    return SCOPE_RANK[key]


def effective_scope(scopes: list[str]) -> str:
    """Widest scope across branch assignments (most permissive visibility)."""
    if not scopes:
        return BRANCH
    return max(scopes, key=lambda s: scope_rank(s))
