"""
Orchestration boundary doctrine (E6.5 / pre-E7).

Defines what economic lineage infrastructure IS and what accounting orchestration may NEVER do.
"""
from __future__ import annotations

from typing import FrozenSet

# E3–E6 layer identity
LINEAGE_LAYER_PURPOSE = (
    "Immutable economic evidence, governed projections, treasury routing, "
    "and settlement lineage — not accounting authority."
)

EVENTS_ARE: FrozenSet[str] = frozenset(
    {
        "evidence",
        "economic_lineage",
        "replay_rebuildable",
        "governance_classified",
        "append_only",
    }
)

EVENTS_ARE_NOT: FrozenSet[str] = frozenset(
    {
        "accounting_truth",
        "settlement_truth_for_operations",
        "authoritative_balances",
        "fiscal_authority",
        "operational_authority",
        "gl_substitute",
        "journal_substitute",
    }
)

# What E7+ accounting orchestration MAY consume (read-only from lineage perspective)
E7_MAY_CONSUME: FrozenSet[str] = frozenset(
    {
        "financial_events",
        "settlement_links",
        "correlation_groups",
        "derived_exposure_states",
        "governed_projections",
        "treasury_routing_dimension",
    }
)

# What E7+ MUST NEVER mutate
E7_MUST_NEVER: FrozenSet[str] = frozenset(
    {
        "financial_events rows",
        "settlement_links rows",
        "operational_invoices",
        "operational_payments",
        "commercial_transactions",
        "cashbook_entries as operational source",
        "projection_registry semantics",
    }
)

# What E7+ MUST NEVER do inside lineage tables
E7_FORBIDDEN_ON_LINEAGE: FrozenSet[str] = frozenset(
    {
        "update financial_events.amount",
        "update financial_events.occurred_at",
        "delete financial_events",
        "mutate settlement_links",
        "store cumulative balances on events",
        "post directly into financial_events",
    }
)

ORCHESTRATION_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "posting_proposals_are_separate_artifacts",
        "journals_never_write_to_financial_events",
        "gl_never_becomes_source_of_operational_truth",
        "replay_remains_idempotent_after_e7",
        "projections_remain_non_authoritative_after_e7",
    }
)


def introspect_orchestration_boundary() -> dict:
    return {
        "layer_purpose": LINEAGE_LAYER_PURPOSE,
        "events_are": sorted(EVENTS_ARE),
        "events_are_not": sorted(EVENTS_ARE_NOT),
        "e7_may_consume": sorted(E7_MAY_CONSUME),
        "e7_must_never": sorted(E7_MUST_NEVER),
        "e7_forbidden_on_lineage": sorted(E7_FORBIDDEN_ON_LINEAGE),
        "invariants": sorted(ORCHESTRATION_INVARIANTS),
    }
