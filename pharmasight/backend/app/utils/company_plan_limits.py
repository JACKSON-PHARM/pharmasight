"""
Company-scoped plan limits and demo detection (Option B).

All entitlement-style limits MUST read from `companies` only — never from Tenant.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session


def company_is_demo_plan(company: Any) -> bool:
    """Self-service / demo-style plans use subscription_plan slug ``demo`` on the company row."""
    return (getattr(company, "subscription_plan", None) or "").strip().lower() == "demo"


def company_product_limit(company: Any) -> Optional[int]:
    v = getattr(company, "product_limit", None)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def company_branch_limit(company: Any) -> Optional[int]:
    v = getattr(company, "branch_limit", None)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def company_user_limit(company: Any) -> Optional[int]:
    v = getattr(company, "user_limit", None)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def count_distinct_company_users(db: Session, company_id: UUID) -> int:
    """Users with at least one branch role under a branch of this company (non-deleted users)."""
    from app.models.user import User, UserBranchRole
    from app.models.company import Branch

    n = (
        db.query(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(UserBranchRole, UserBranchRole.user_id == User.id)
        .join(Branch, Branch.id == UserBranchRole.branch_id)
        .filter(Branch.company_id == company_id, User.deleted_at.is_(None))
        .scalar()
    )
    return int(n or 0)


__all__ = [
    "company_is_demo_plan",
    "company_product_limit",
    "company_branch_limit",
    "company_user_limit",
    "count_distinct_company_users",
]
