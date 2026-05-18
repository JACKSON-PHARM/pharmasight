"""
Causal lineage & replay semantics (E6.5).

Replay is deterministic lineage reconstruction — not smart recomputation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import FrozenSet, List, Optional, Sequence
from uuid import UUID

CAUSAL_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "events_are_evidence_not_authority",
        "occurred_at_defines_economic_order",
        "emitted_at_defines_system_order",
        "replay_preserves_idempotency_keys",
        "replay_preserves_occurred_at_from_failure_record",
        "replay_does_not_reorder_existing_events",
        "reconstruction_is_append_only",
        "causal_graph_is_directed_acyclic_at_emit_time",
        "compensations_reference_reversal_of_event_id",
        "backfill_replays_hooks_not_reinterprets_history",
    }
)

# Canonical ordering for failure replay batches
REPLAY_ORDER_KEYS: tuple[str, ...] = (
    "occurred_at",
    "emitted_at",
    "idempotency_key",
)


@dataclass(frozen=True)
class ReplayOrderingSpec:
    primary: str = "occurred_at"
    secondary: str = "emitted_at"
    tertiary: str = "idempotency_key"
    direction: str = "ascending"


REPLAY_ORDERING = ReplayOrderingSpec()


@dataclass(frozen=True)
class CausalDependency:
    """Declared dependency for reconstruction (documentation + future orchestration)."""

    parent_event_type: str
    child_event_type: str
    relationship: str


# Settlement flows: accrual must exist before settlement in causal order (by occurred_at)
CAUSAL_DEPENDENCIES: tuple[CausalDependency, ...] = (
    CausalDependency("receivable_accrued", "cash_received", "settlement_follows_accrual"),
    CausalDependency("payable_recognized", "cash_paid", "settlement_follows_accrual"),
    CausalDependency("insurance_claim_recognized", "insurance_settlement_received", "settlement_follows_accrual"),
    CausalDependency("receivable_accrued", "receivable_accrued_reversal", "compensation"),
)


def sort_failures_for_replay(failures: Sequence) -> List:
    """
    Deterministic replay order for emission failures.

    failures: objects with occurred_at, created_at/emitted_at, idempotency_key
    """

    def _key(f):
        occurred = getattr(f, "occurred_at", None) or datetime.min
        created = getattr(f, "created_at", None) or getattr(f, "emitted_at", None) or datetime.min
        idem = getattr(f, "idempotency_key", "") or ""
        return (occurred, created, idem)

    return sorted(failures, key=_key)


def introspect_causal_lineage_doctrine() -> dict:
    return {
        "invariants": sorted(CAUSAL_INVARIANTS),
        "replay_ordering": {
            "primary": REPLAY_ORDERING.primary,
            "secondary": REPLAY_ORDERING.secondary,
            "tertiary": REPLAY_ORDERING.tertiary,
            "direction": REPLAY_ORDERING.direction,
        },
        "dependencies": [
            {
                "parent": d.parent_event_type,
                "child": d.child_event_type,
                "relationship": d.relationship,
            }
            for d in CAUSAL_DEPENDENCIES
        ],
        "reconstruction_principle": "append_only_idempotent_replay",
    }
