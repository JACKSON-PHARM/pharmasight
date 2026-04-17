"""
Plan / limit context for SaaS enforcement.

Option B: all product limits and demo-style caps are read from `companies` only.
Re-exports helpers from ``company_plan_limits``; do not add Tenant-based helpers here.
"""
from __future__ import annotations

from app.utils.company_plan_limits import (  # noqa: F401
    company_is_demo_plan,
    company_product_limit,
    company_branch_limit,
    company_user_limit,
    count_distinct_company_users,
)

__all__ = [
    "company_is_demo_plan",
    "company_product_limit",
    "company_branch_limit",
    "company_user_limit",
    "count_distinct_company_users",
]
