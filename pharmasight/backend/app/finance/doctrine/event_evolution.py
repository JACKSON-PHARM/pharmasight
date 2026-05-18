"""
Event schema evolution doctrine (E6.5).

Governs how financial_events types evolve without breaking replay/projections.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List

from app.finance.events.registry import FINANCIAL_EVENT_REGISTRY

EVOLUTION_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "event_schema_version_immutable_per_row",
        "new_versions_add_optional_payload_fields_only",
        "breaking_changes_require_new_event_type",
        "deprecation_is_registry_level_not_delete",
        "replay_uses_failure_record_schema_version",
        "projections_declare_compatible_event_types",
        "no_in_place_payload_semantic_change",
    }
)

COMPATIBILITY_POLICY: dict[str, str] = {
    "minor_version": "additive payload fields only; projections unchanged",
    "major_version": "new event_type required; old type frozen",
    "deprecation": "stop emitting; existing rows remain; compensating types allowed",
    "replay": "use stored failure schema_version and idempotency_key",
}


def build_projection_compatibility_matrix() -> List[dict]:
    """Which event types each projection lineage set depends on."""
    from app.finance.projections.registry import PROJECTION_REGISTRY

    rows = []
    for spec in PROJECTION_REGISTRY.values():
        rows.append(
            {
                "projection_id": spec.projection_id,
                "lineage_event_types": list(spec.lineage_event_types),
                "schema_versions": _schema_versions_for_types(spec.lineage_event_types),
                "replay_rebuildable": spec.replay_rebuildable,
            }
        )
    return rows


def _schema_versions_for_types(event_types: tuple[str, ...]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for et in event_types:
        s = FINANCIAL_EVENT_REGISTRY.get(et)
        if s:
            out[et] = s.schema_version
    return out


def introspect_event_evolution_doctrine() -> dict:
    registry_versions = {
        et: spec.schema_version for et, spec in FINANCIAL_EVENT_REGISTRY.items()
    }
    return {
        "invariants": sorted(EVOLUTION_INVARIANTS),
        "compatibility_policy": COMPATIBILITY_POLICY,
        "registry_schema_versions": registry_versions,
        "projection_compatibility_matrix": build_projection_compatibility_matrix(),
    }
