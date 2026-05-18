"""
Treasury doctrine (E5.5 / E6) — routing buckets only, not hidden GL.

Preferred terminology: routing bucket, treasury channel, operational treasury lane, movement stream.
Forbidden: ledger, account balance, posting, chart, asset, liability (as treasury concepts).
"""
from __future__ import annotations

from typing import FrozenSet

from app.finance.treasury.doctrine import (
    FORBIDDEN_TREASURY_FIELD_NAMES,
    ROUTING_TYPES,
    assert_treasury_field_safe,
)

TREASURY_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "cashbook_accounts_are_routing_dimensions_only",
        "no_authoritative_balances_stored",
        "no_debit_credit_semantics",
        "no_gl_account_mapping_in_treasury_layer",
        "classification_governs_visibility",
        "movement_derived_from_events_not_stored_cumulative",
    }
)

PREFERRED_TREASURY_TERMS: FrozenSet[str] = frozenset(
    {
        "routing bucket",
        "treasury channel",
        "operational treasury lane",
        "movement stream",
        "routing_type",
    }
)

FORBIDDEN_TREASURY_LABELS: FrozenSet[str] = frozenset(
    {
        "ledger",
        "ledger account",
        "account balance",
        "chart of accounts",
        "posting",
        "account type",
        "asset account",
        "liability account",
        "trial balance",
        "reconciliation truth",
    }
)


def assert_treasury_label_safe(label: str) -> None:
    """Reject user-facing/API labels that imply accounting semantics."""
    low = (label or "").strip().lower()
    for forbidden in FORBIDDEN_TREASURY_LABELS:
        if forbidden in low:
            raise ValueError(f"Treasury label implies accounting semantics: {forbidden}")
    assert_treasury_field_safe(label)


UI_PRESENTATION_RULES: dict[str, str] = {
    "never_label_as_balance": "Use 'period movement' or 'routing channel movement'",
    "never_label_as_ledger": "Use 'treasury routing bucket' or 'operational channel'",
    "always_show_disclaimer": "Derived snapshot — not cash on hand authority",
    "show_rebuild_timestamp": "Required on all treasury movement views",
    "authoritative_flag": "always false in API responses",
}

def introspect_treasury_doctrine() -> dict:
    return {
        "invariants": sorted(TREASURY_INVARIANTS),
        "routing_types": sorted(ROUTING_TYPES),
        "preferred_terms": sorted(PREFERRED_TREASURY_TERMS),
        "forbidden_field_names": sorted(FORBIDDEN_TREASURY_FIELD_NAMES),
        "forbidden_labels": sorted(FORBIDDEN_TREASURY_LABELS),
        "ui_presentation": UI_PRESENTATION_RULES,
        "movement_vs_holdings": (
            "Treasury APIs expose movement streams for a period; "
            "they do not expose holdings or authoritative liquidity positions."
        ),
    }
