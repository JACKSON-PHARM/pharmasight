"""
Plan context helper for tenant limits and demo configuration.

This module intentionally does not perform any additional database queries.
It only reads fields that are already present on the provided Tenant instance.
"""
from __future__ import annotations

from typing import Any, Dict


def get_tenant_plan_context(tenant: Any) -> Dict[str, Any]:
    """
    Return a lightweight plan context for the given tenant.

    The function relies solely on attributes already loaded on the tenant object
    and MUST NOT perform any additional database queries. This keeps it safe
    to call from performance‑sensitive paths (e.g. per‑request enforcement).

    Returned keys:
      - plan_type
      - product_limit
      - branch_limit
      - user_limit
      - demo_expires_at
    """
    if tenant is None:
        return {
            "plan_type": None,
            "product_limit": None,
            "branch_limit": None,
            "user_limit": None,
            "demo_expires_at": None,
        }

    # Use getattr with defaults so this works even if some fields
    # are not present on older Tenant instances in long‑running processes.
    return {
        "plan_type": getattr(tenant, "plan_type", None),
        "product_limit": getattr(tenant, "product_limit", None),
        "branch_limit": getattr(tenant, "branch_limit", None),
        "user_limit": getattr(tenant, "user_limit", None),
        "demo_expires_at": getattr(tenant, "demo_expires_at", None),
    }


__all__ = ["get_tenant_plan_context"]

