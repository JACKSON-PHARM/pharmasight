"""
Company-based subscription access.

Delegates commercial access derivation to ``company_governance_service`` (single compiler).
Maps governance states to legacy ``CompanyAccess`` for existing SPA subscription gates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Any

from app.services.company_governance_service import (
    derive_commercial_access,
    map_commercial_access_to_company_access,
    subscription_access_for_company,
)

CompanyAccess = Literal["blocked", "active", "trial", "expired"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_company_access(company: Optional[Any], *, now: Optional[datetime] = None) -> CompanyAccess:
    if company is None:
        return "active"
    state = derive_commercial_access(company, now=now)
    return map_commercial_access_to_company_access(state)


def company_access_to_subscription_access(access: CompanyAccess) -> str:
    """Map CompanyAccess → SPA token (prefer subscription_access_for_company on auth/me)."""
    if access == "trial":
        return "trial"
    if access == "expired":
        return "trial_expired"
    if access == "blocked":
        return "blocked"
    return "full"


def get_subscription_access(company: Optional[Any], *, now: Optional[datetime] = None) -> str:
    """SPA subscription_access from governance compiler (single source of truth)."""
    return subscription_access_for_company(company, now=now)
