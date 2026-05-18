"""
Projection invalidation & freshness semantics (E6.5).

Defines when derived views are stale after replay/backfill — no projection caching enabled yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, FrozenSet, Literal, Optional

FreshnessClass = Literal["live", "eventually_consistent", "as_of_query", "invalidated_on_replay"]

FRESHNESS_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "no_projection_cache_enabled_in_e65",
        "replay_invalidates_lineage_derived_projections",
        "backfill_invalidates_branch_projections_for_window",
        "staleness_is_metadata_not_mutation",
        "users_must_not_treat_projections_as_balances",
    }
)


@dataclass(frozen=True)
class ProjectionFreshnessSpec:
    projection_id: str
    freshness_class: FreshnessClass
    invalidated_by_replay: bool
    invalidated_by_backfill: bool
    cacheable: bool
    max_staleness_seconds: Optional[int]


PROJECTION_FRESHNESS: Dict[str, ProjectionFreshnessSpec] = {
    "branch_cash_movement": ProjectionFreshnessSpec(
        projection_id="branch_cash_movement",
        freshness_class="eventually_consistent",
        invalidated_by_replay=True,
        invalidated_by_backfill=True,
        cacheable=False,
        max_staleness_seconds=None,
    ),
    "ar_recognized_vs_collected": ProjectionFreshnessSpec(
        projection_id="ar_recognized_vs_collected",
        freshness_class="eventually_consistent",
        invalidated_by_replay=True,
        invalidated_by_backfill=True,
        cacheable=False,
        max_staleness_seconds=None,
    ),
    "insurance_claim_exposure": ProjectionFreshnessSpec(
        projection_id="insurance_claim_exposure",
        freshness_class="eventually_consistent",
        invalidated_by_replay=True,
        invalidated_by_backfill=True,
        cacheable=False,
        max_staleness_seconds=None,
    ),
    "lineage_integrity_summary": ProjectionFreshnessSpec(
        projection_id="lineage_integrity_summary",
        freshness_class="as_of_query",
        invalidated_by_replay=False,
        invalidated_by_backfill=False,
        cacheable=False,
        max_staleness_seconds=0,
    ),
    "treasury_routing_snapshot": ProjectionFreshnessSpec(
        projection_id="treasury_routing_snapshot",
        freshness_class="eventually_consistent",
        invalidated_by_replay=True,
        invalidated_by_backfill=True,
        cacheable=False,
        max_staleness_seconds=None,
    ),
    "settlement_graph_health": ProjectionFreshnessSpec(
        projection_id="settlement_graph_health",
        freshness_class="live",
        invalidated_by_replay=True,
        invalidated_by_backfill=True,
        cacheable=False,
        max_staleness_seconds=0,
    ),
}


def get_freshness_spec(projection_id: str) -> ProjectionFreshnessSpec:
    spec = PROJECTION_FRESHNESS.get(projection_id)
    if spec is None:
        raise KeyError(f"No freshness spec for projection: {projection_id}")
    return spec


def build_freshness_envelope(
    projection_id: str,
    *,
    replay_occurred: bool = False,
    backfill_occurred: bool = False,
) -> dict:
    spec = get_freshness_spec(projection_id)
    now = datetime.now(timezone.utc)
    potentially_stale = (replay_occurred and spec.invalidated_by_replay) or (
        backfill_occurred and spec.invalidated_by_backfill
    )
    return {
        "freshness_class": spec.freshness_class,
        "cacheable": spec.cacheable,
        "rebuild_timestamp": now.isoformat(),
        "temporal_confidence": "low" if potentially_stale else "current",
        "invalidated_by_replay": replay_occurred and spec.invalidated_by_replay,
        "invalidated_by_backfill": backfill_occurred and spec.invalidated_by_backfill,
        "disclaimer": (
            "Derived snapshot — not a balance or authoritative position. "
            "Rebuild from financial_events after replay/backfill."
        ),
    }


def introspect_projection_freshness() -> list[dict]:
    return [
        {
            "projection_id": s.projection_id,
            "freshness_class": s.freshness_class,
            "invalidated_by_replay": s.invalidated_by_replay,
            "invalidated_by_backfill": s.invalidated_by_backfill,
            "cacheable": s.cacheable,
            "max_staleness_seconds": s.max_staleness_seconds,
        }
        for s in PROJECTION_FRESHNESS.values()
    ]
