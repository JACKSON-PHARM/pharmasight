"""
Company-scoped plan limits and demo detection (Option B).

All entitlement-style limits MUST read from `companies` only — never from Tenant.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

# Stripe / admin.html statuses that mean "not a self-service demo tenant" for cap purposes,
# even if subscription_plan was left as demo by mistake.
_LICENSED_SUBSCRIPTION_STATUSES = frozenset(
    {"active", "paid", "trialing", "past_due"},
)


def company_is_demo_plan(company: Any) -> bool:
    """
    Demo-style caps apply when the company slug is ``demo``.

    Admin tooling often updates ``subscription_status`` while the plan slug is accidentally left
    as ``demo``. Treat licensed billing statuses as non-demo so caps lift.
    """
    plan = (getattr(company, "subscription_plan", None) or "").strip().lower()
    if plan != "demo":
        return False
    status = (getattr(company, "subscription_status", None) or "").strip().lower()
    if status in _LICENSED_SUBSCRIPTION_STATUSES:
        return False
    return True


def company_trial_expires_effective(company: Any) -> Optional[datetime]:
    """
    Trial end shown in admin / licensing UI: use ``trial_expires_at`` when set; otherwise for
    ``subscription_plan == demo`` infer ``created_at + DEMO_DURATION_DAYS`` so legacy rows still show a date.
    """
    te = getattr(company, "trial_expires_at", None)
    if te is not None:
        return te if isinstance(te, datetime) else None
    plan = (getattr(company, "subscription_plan", None) or "").strip().lower()
    if plan != "demo":
        return None
    created = getattr(company, "created_at", None)
    if not isinstance(created, datetime):
        return None
    from app.config import settings

    days = int(getattr(settings, "DEMO_DURATION_DAYS", 7) or 7)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created + timedelta(days=days)


def sync_demo_plan_slug_with_subscription_status(company: Any) -> None:
    """
    Mutates ``company`` in memory: if status is licensed but plan slug is still ``demo``, clear the slug.

    Keeps the DB consistent with how operators use admin.html (status vs plan).
    """
    status = (getattr(company, "subscription_status", None) or "").strip().lower()
    plan = (getattr(company, "subscription_plan", None) or "").strip().lower()
    if status in _LICENSED_SUBSCRIPTION_STATUSES and plan == "demo":
        company.subscription_plan = None


def _demo_default_product_limit() -> int:
    from app.config import settings

    v = getattr(settings, "DEMO_PRODUCT_LIMIT", 100) or 100
    return int(v)


def _demo_default_user_limit() -> int:
    from app.config import settings

    v = getattr(settings, "DEMO_USER_LIMIT", 1) or 1
    return int(v)


def _demo_default_branch_limit() -> int:
    return 1


def company_product_limit(company: Any) -> Optional[int]:
    v = getattr(company, "product_limit", None)
    if v is not None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    if company_is_demo_plan(company):
        return _demo_default_product_limit()
    return None


def company_branch_limit(company: Any) -> Optional[int]:
    v = getattr(company, "branch_limit", None)
    if v is not None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    if company_is_demo_plan(company):
        return _demo_default_branch_limit()
    return None


def company_user_limit(company: Any) -> Optional[int]:
    v = getattr(company, "user_limit", None)
    if v is not None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    if company_is_demo_plan(company):
        return _demo_default_user_limit()
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
    "company_trial_expires_effective",
    "sync_demo_plan_slug_with_subscription_status",
    "company_product_limit",
    "company_branch_limit",
    "company_user_limit",
    "count_distinct_company_users",
]
