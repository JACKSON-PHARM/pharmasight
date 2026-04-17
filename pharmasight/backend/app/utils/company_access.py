"""
Company-based subscription access (single source of truth).

Tenancy architecture: `companies.id` is the tenant. Subscription gating must be derived from
company fields only, not from legacy `tenants` registry rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Any

CompanyAccess = Literal["blocked", "active", "trial", "expired"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_company_access(company: Optional[Any], *, now: Optional[datetime] = None) -> CompanyAccess:
    """
    Compute access from companies table fields (single source of truth).

    Rules (as requested):
    - if not company.is_active => "blocked"
    - if company.subscription_status == "active" => "active"
    - if company.trial_expires_at:
        - now < trial_expires_at => "trial"
        - else => "expired"
    - else => "active" (treat nulls as full access)
    """
    if company is None:
        # Defensive default: if we cannot resolve the company row, don't block the entire app.
        return "active"

    if not bool(getattr(company, "is_active", True)):
        return "blocked"

    sub_status = (getattr(company, "subscription_status", None) or "").strip().lower()
    if sub_status == "active":
        return "active"

    trial_expires_at = getattr(company, "trial_expires_at", None)
    if trial_expires_at is not None:
        n = now or now_utc()
        end = trial_expires_at
        if getattr(end, "tzinfo", None) is None:
            end = end.replace(tzinfo=timezone.utc)
        return "trial" if n < end else "expired"

    return "active"


def company_access_to_subscription_access(access: CompanyAccess) -> str:
    """
    Map company access -> frontend `subscription_access` values used by existing SPA logic.
    """
    if access == "trial":
        return "trial"
    if access == "expired":
        return "trial_expired"
    if access == "blocked":
        return "blocked"
    return "full"

