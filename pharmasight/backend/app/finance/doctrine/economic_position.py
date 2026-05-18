"""
Economic position semantics (E6.5) — derived exposure states from lineage only.

Never stored. Never authoritative. Operational tables remain source of truth.
"""
from __future__ import annotations

from typing import FrozenSet

# Canonical derived states (not DB enums — computed at read time)
EXPOSURE_STATE_OPEN = "open_exposure"
EXPOSURE_STATE_PARTIALLY_SETTLED = "partially_settled"
EXPOSURE_STATE_FULLY_SETTLED = "fully_settled"
EXPOSURE_STATE_REVERSED = "reversed_exposure"
EXPOSURE_STATE_EXHAUSTED_CLAIM = "exhausted_claim"
EXPOSURE_STATE_STALE = "stale_exposure"
EXPOSURE_STATE_DISPUTED = "disputed_exposure"
EXPOSURE_STATE_NO_ACCRUAL = "no_accrual_lineage"

ALL_EXPOSURE_STATES: FrozenSet[str] = frozenset(
    {
        EXPOSURE_STATE_OPEN,
        EXPOSURE_STATE_PARTIALLY_SETTLED,
        EXPOSURE_STATE_FULLY_SETTLED,
        EXPOSURE_STATE_REVERSED,
        EXPOSURE_STATE_EXHAUSTED_CLAIM,
        EXPOSURE_STATE_STALE,
        EXPOSURE_STATE_DISPUTED,
        EXPOSURE_STATE_NO_ACCRUAL,
    }
)

# Allowed transitions (derived read model — not workflow engine)
EXPOSURE_TRANSITIONS: dict[str, frozenset[str]] = {
    EXPOSURE_STATE_OPEN: frozenset(
        {EXPOSURE_STATE_PARTIALLY_SETTLED, EXPOSURE_STATE_FULLY_SETTLED, EXPOSURE_STATE_REVERSED}
    ),
    EXPOSURE_STATE_PARTIALLY_SETTLED: frozenset(
        {EXPOSURE_STATE_FULLY_SETTLED, EXPOSURE_STATE_REVERSED, EXPOSURE_STATE_DISPUTED}
    ),
    EXPOSURE_STATE_FULLY_SETTLED: frozenset({EXPOSURE_STATE_REVERSED}),
    EXPOSURE_STATE_REVERSED: frozenset(),
    EXPOSURE_STATE_EXHAUSTED_CLAIM: frozenset({EXPOSURE_STATE_REVERSED}),
    EXPOSURE_STATE_STALE: frozenset(
        {EXPOSURE_STATE_PARTIALLY_SETTLED, EXPOSURE_STATE_FULLY_SETTLED, EXPOSURE_STATE_REVERSED}
    ),
    EXPOSURE_STATE_DISPUTED: frozenset(
        {EXPOSURE_STATE_PARTIALLY_SETTLED, EXPOSURE_STATE_FULLY_SETTLED, EXPOSURE_STATE_REVERSED}
    ),
}

ACCRUAL_EVENT_TYPES: FrozenSet[str] = frozenset(
    {
        "receivable_accrued",
        "payable_recognized",
        "insurance_claim_recognized",
    }
)

SETTLEMENT_INFLOW_TYPES: FrozenSet[str] = frozenset(
    {
        "cash_received",
        "cash_paid",
        "insurance_settlement_received",
        "retail_cash_collected",
    }
)

ECONOMIC_POSITION_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "exposure_never_stored",
        "exposure_derived_from_events_and_links_only",
        "operational_entities_remain_authoritative",
        "reversal_compensates_events_not_links",
        "partial_settlement_by_link_aggregation",
        "open_vs_closed_is_derived_not_mutated",
        "stale_is_temporal_not_accounting",
        "disputed_is_operational_signal_not_gl",
    }
)


def introspect_economic_position_doctrine() -> dict:
    return {
        "states": sorted(ALL_EXPOSURE_STATES),
        "transitions": {k: sorted(v) for k, v in EXPOSURE_TRANSITIONS.items()},
        "accrual_event_types": sorted(ACCRUAL_EVENT_TYPES),
        "settlement_inflow_types": sorted(SETTLEMENT_INFLOW_TYPES),
        "invariants": sorted(ECONOMIC_POSITION_INVARIANTS),
        "authoritative": False,
    }
