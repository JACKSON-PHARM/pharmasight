"""
Finance semantic doctrine (E5.5 / E6 / E6.5) — architectural invariants enforced in code and docs.
"""

from app.finance.doctrine.projection import (
    PROJECTION_INVARIANTS,
    ProjectionContract,
    validate_projection_contract,
    validate_projection_registry,
)
from app.finance.doctrine.correlation import CORRELATION_GOVERNANCE, validate_correlation_group
from app.finance.doctrine.settlement import SETTLEMENT_RULES, verify_settlement_graph, would_create_settlement_cycle
from app.finance.doctrine.temporal import TEMPORAL_SEMANTICS, resolve_temporal_filter
from app.finance.doctrine.backfill import BACKFILL_INVARIANTS, BACKFILL_FORBIDDEN
from app.finance.doctrine.treasury import TREASURY_INVARIANTS, assert_treasury_label_safe
from app.finance.doctrine.economic_position import introspect_economic_position_doctrine
from app.finance.doctrine.causal_lineage import introspect_causal_lineage_doctrine, sort_failures_for_replay
from app.finance.doctrine.projection_freshness import introspect_projection_freshness, build_freshness_envelope
from app.finance.doctrine.event_evolution import introspect_event_evolution_doctrine
from app.finance.doctrine.orchestration_boundary import introspect_orchestration_boundary

__all__ = [
    "PROJECTION_INVARIANTS",
    "ProjectionContract",
    "validate_projection_contract",
    "validate_projection_registry",
    "CORRELATION_GOVERNANCE",
    "validate_correlation_group",
    "SETTLEMENT_RULES",
    "verify_settlement_graph",
    "would_create_settlement_cycle",
    "TEMPORAL_SEMANTICS",
    "resolve_temporal_filter",
    "BACKFILL_INVARIANTS",
    "BACKFILL_FORBIDDEN",
    "TREASURY_INVARIANTS",
    "assert_treasury_label_safe",
    "introspect_economic_position_doctrine",
    "introspect_causal_lineage_doctrine",
    "sort_failures_for_replay",
    "introspect_projection_freshness",
    "build_freshness_envelope",
    "introspect_event_evolution_doctrine",
    "introspect_orchestration_boundary",
]
