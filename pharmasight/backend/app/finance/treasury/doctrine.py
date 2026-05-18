"""
E5 treasury doctrine — cashbook_accounts are routing dimensions only.

Forbidden in this layer: ledger accounts, debit/credit, authoritative balances,
asset/liability typing, reconciliation truth, chart-of-accounts substitutes.
"""
from __future__ import annotations

from typing import FrozenSet

ROUTING_TYPES: FrozenSet[str] = frozenset(
    {"till", "mpesa", "bank", "insurance_pool", "company_treasury"}
)

DEFAULT_CLASSIFICATION_BY_ROUTING: dict[str, str] = {
    "till": "branch_finance",
    "mpesa": "branch_finance",
    "bank": "management",
    "insurance_pool": "confidential",
    "company_treasury": "executive",
}

FORBIDDEN_TREASURY_FIELD_NAMES: FrozenSet[str] = frozenset(
    {
        "debit",
        "credit",
        "balance",
        "running_balance",
        "account_type",
        "asset",
        "liability",
        "gl_account",
        "chart_of_accounts",
        "journal",
    }
)


def assert_treasury_field_safe(field_name: str) -> None:
    key = field_name.strip().lower()
    for forbidden in FORBIDDEN_TREASURY_FIELD_NAMES:
        if forbidden in key:
            raise ValueError(f"Treasury dimension forbids accounting field name: {field_name}")
