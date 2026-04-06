"""
Subscription / trial display and enforcement helpers (master `tenants` row).

Uses only attributes on the Tenant model — no extra DB queries beyond the caller's lookup.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def is_trial_expired(tenant: Optional[Any]) -> bool:
    """True if tenant is on trial and trial_ends_at is in the past (UTC)."""
    if tenant is None:
        return False
    if (getattr(tenant, "status", None) or "") != "trial":
        return False
    end = getattr(tenant, "trial_ends_at", None)
    if not end:
        return False
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end < datetime.now(timezone.utc)


def compute_subscription_billing_state(tenant: Optional[Any]) -> Dict[str, Any]:
    """
    UI + enforcement context for the current organization (master tenant row).

    subscription_access:
      - full: paid / active, legacy, or trial without an end date
      - trial: time-limited trial still valid
      - trial_expired: trial end date passed (still status=trial)
    """
    if tenant is None:
        return {
            "subscription_access": "full",
            "tenant_status": None,
            "trial_ends_at": None,
            "trial_days_remaining": None,
        }

    st = (getattr(tenant, "status", None) or "").lower()
    if st == "active":
        return {
            "subscription_access": "full",
            "tenant_status": getattr(tenant, "status", None),
            "trial_ends_at": None,
            "trial_days_remaining": None,
        }

    if st == "trial":
        te = getattr(tenant, "trial_ends_at", None)
        if te is None:
            return {
                "subscription_access": "trial",
                "tenant_status": getattr(tenant, "status", None),
                "trial_ends_at": None,
                "trial_days_remaining": None,
            }
        end = te
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if end < now:
            return {
                "subscription_access": "trial_expired",
                "tenant_status": getattr(tenant, "status", None),
                "trial_ends_at": te,
                "trial_days_remaining": 0,
            }
        # Match admin UI: Math.floor((end - now) / dayMs)
        delta_ms = (end - now).total_seconds() * 1000.0
        days_left = int(math.floor(delta_ms / (1000 * 60 * 60 * 24)))
        return {
            "subscription_access": "trial",
            "tenant_status": getattr(tenant, "status", None),
            "trial_ends_at": te,
            "trial_days_remaining": max(0, days_left),
        }

    return {
        "subscription_access": "full",
        "tenant_status": getattr(tenant, "status", None),
        "trial_ends_at": None,
        "trial_days_remaining": None,
    }


__all__ = ["is_trial_expired", "compute_subscription_billing_state"]
