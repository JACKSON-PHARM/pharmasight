"""
Projection doctrine (E5.5 / E6) — governed derived views only.

Projections are disposable, rebuildable, and never authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Literal, Tuple

PROJECTION_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "projections_are_disposable",
        "projections_are_rebuildable",
        "projections_never_authoritative",
        "projections_cannot_own_business_state",
        "projections_cannot_mutate_operational_truth",
        "projections_cannot_persist_balances_as_truth",
        "projections_must_declare_lineage_source",
        "projections_must_declare_temporal_semantics",
        "projections_cannot_introduce_accounting_semantics",
        "projections_cannot_bypass_finance_access_context",
    }
)

FORBIDDEN_PROJECTION_TERMS: FrozenSet[str] = frozenset(
    {
        "trial balance",
        "balance sheet",
        "retained earnings",
        "debit",
        "credit",
        "journal entry",
        "general ledger",
        "chart of accounts",
        "fiscal close",
        "authoritative balance",
        "running balance",
    }
)

TemporalBasis = Literal["occurred_at", "emitted_at", "as_of_query"]
ConsistencyMode = Literal["current", "eventual"]


@dataclass(frozen=True)
class ProjectionContract:
    """E6 projection specification contract — required for every registered projection."""

    projection_id: str
    title: str
    description: str
    permission: str
    classification: str
    branch_scoped: bool
    company_scoped: bool
    lineage_source: str
    lineage_event_types: Tuple[str, ...]
    replay_rebuildable: bool
    policy_pack_aware: bool
    temporal_basis: TemporalBasis
    temporal_semantics: str
    consistency: ConsistencyMode
    scope_expectation: str
    cacheable: bool
    authoritative: bool
    mutates_operational_truth: bool
    persists_balances: bool
    notes: str = ""

    def __post_init__(self) -> None:
        validate_projection_contract(self)


def validate_projection_contract(spec: ProjectionContract) -> None:
    if spec.authoritative is not False:
        raise ValueError(f"projection {spec.projection_id}: authoritative must be False")
    if spec.mutates_operational_truth is not False:
        raise ValueError(f"projection {spec.projection_id}: cannot mutate operational truth")
    if spec.persists_balances is not False:
        raise ValueError(f"projection {spec.projection_id}: cannot persist balances as truth")
    if not spec.replay_rebuildable:
        raise ValueError(f"projection {spec.projection_id}: must be replay-rebuildable")
    if not spec.lineage_source:
        raise ValueError(f"projection {spec.projection_id}: lineage_source required")
    if not spec.lineage_event_types and not any(
        k in spec.lineage_source for k in ("integrity", "settlement_links", "settlement")
    ):
        raise ValueError(f"projection {spec.projection_id}: lineage_event_types required")
    text = f"{spec.title} {spec.description} {spec.notes}".lower()
    for term in FORBIDDEN_PROJECTION_TERMS:
        if term in text:
            raise ValueError(f"projection {spec.projection_id}: forbidden accounting term '{term}'")


def validate_projection_registry(registry: Dict[str, ProjectionContract]) -> None:
    for spec in registry.values():
        validate_projection_contract(spec)


def contract_to_introspection(spec: ProjectionContract) -> dict:
    return {
        "projection_id": spec.projection_id,
        "title": spec.title,
        "description": spec.description,
        "permission": spec.permission,
        "classification": spec.classification,
        "branch_scoped": spec.branch_scoped,
        "company_scoped": spec.company_scoped,
        "lineage_source": spec.lineage_source,
        "lineage_event_types": list(spec.lineage_event_types),
        "replay_rebuildable": spec.replay_rebuildable,
        "policy_pack_aware": spec.policy_pack_aware,
        "temporal_basis": spec.temporal_basis,
        "temporal_semantics": spec.temporal_semantics,
        "consistency": spec.consistency,
        "scope_expectation": spec.scope_expectation,
        "cacheable": spec.cacheable,
        "authoritative": spec.authoritative,
        "mutates_operational_truth": spec.mutates_operational_truth,
        "persists_balances": spec.persists_balances,
        "invariants": sorted(PROJECTION_INVARIANTS),
        "notes": spec.notes,
    }


def wrap_projection_payload(
    spec: ProjectionContract,
    payload: dict,
    *,
    replay_occurred: bool = False,
    backfill_occurred: bool = False,
) -> dict:
    """E6/E6.5 envelope — contract + freshness metadata on every projection."""
    from app.finance.doctrine.projection_freshness import build_freshness_envelope

    return {
        **payload,
        "contract": {
            "projection_id": spec.projection_id,
            "derived": True,
            "authoritative": False,
            "replay_rebuildable": spec.replay_rebuildable,
            "temporal_basis": spec.temporal_basis,
            "consistency": spec.consistency,
            "cacheable": spec.cacheable,
            "lineage_event_types": list(spec.lineage_event_types),
        },
        "freshness": build_freshness_envelope(
            spec.projection_id,
            replay_occurred=replay_occurred,
            backfill_occurred=backfill_occurred,
        ),
    }
