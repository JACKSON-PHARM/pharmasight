"""
Finance data classification (E2 / E2.5).

Business classifications use ordered lanes. AUDIT is an orthogonal lane — not a superset
of executive clearance. classification_allows() encodes this without a single global rank.
"""
from __future__ import annotations

from typing import FrozenSet, Optional, Sequence

FinanceClassification = str

OPERATIONAL: FinanceClassification = "operational"
BRANCH_FINANCE: FinanceClassification = "branch_finance"
MANAGEMENT: FinanceClassification = "management"
CONFIDENTIAL: FinanceClassification = "confidential"
EXECUTIVE: FinanceClassification = "executive"
AUDIT: FinanceClassification = "audit"

ALL_CLASSIFICATIONS: FrozenSet[str] = frozenset(
    {
        OPERATIONAL,
        BRANCH_FINANCE,
        MANAGEMENT,
        CONFIDENTIAL,
        EXECUTIVE,
        AUDIT,
    }
)

# Ordered business lanes (extensible: add lanes without renumbering audit)
BUSINESS_LANE_ORDER: tuple[str, ...] = (
    OPERATIONAL,
    BRANCH_FINANCE,
    MANAGEMENT,
    CONFIDENTIAL,
    EXECUTIVE,
)

_BUSINESS_LANE_INDEX: dict[str, int] = {
    name: idx for idx, name in enumerate(BUSINESS_LANE_ORDER)
}

# Deprecated linear rank — tests / migration only; prefer classification_allows()
CLASSIFICATION_RANK: dict[str, int] = {
    OPERATIONAL: 1,
    BRANCH_FINANCE: 2,
    MANAGEMENT: 3,
    CONFIDENTIAL: 4,
    EXECUTIVE: 5,
    AUDIT: 99,
}


def normalize_classification(value: Optional[str], *, default: str = MANAGEMENT) -> str:
    raw = (value or default).strip().lower()
    if raw not in ALL_CLASSIFICATIONS:
        return default
    return raw


def classification_rank(value: str) -> int:
    """Legacy ordinal; audit uses sentinel 99 — do not use for authorization."""
    key = normalize_classification(value)
    return CLASSIFICATION_RANK[key]


def business_lane_index(value: str) -> int:
    key = normalize_classification(value)
    if key == AUDIT:
        raise ValueError("audit is not a business lane")
    return _BUSINESS_LANE_INDEX[key]


def classification_allows(max_allowed: str, required: str) -> bool:
    """
    True when holder max_allowed may access data at required classification.

    - AUDIT-required endpoints: holder must have audit clearance.
    - AUDIT holders: may read any business-lane classification (read governance).
    - Business lanes: standard monotonic lane ordering within BUSINESS_LANE_ORDER.
    """
    holder = normalize_classification(max_allowed)
    needed = normalize_classification(required)

    if needed == AUDIT:
        return holder == AUDIT

    if holder == AUDIT:
        return True

    return business_lane_index(holder) >= business_lane_index(needed)


def effective_max_classification(classifications: Sequence[str]) -> str:
    """
  Aggregate assignment classifications into a single holder ceiling.

  Audit on any assignment grants audit lane; otherwise highest business lane wins.
    """
    if not classifications:
        return MANAGEMENT
    normalized = [normalize_classification(c) for c in classifications]
    if AUDIT in normalized:
        return AUDIT
    return max(normalized, key=business_lane_index)
