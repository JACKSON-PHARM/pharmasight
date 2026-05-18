"""
Backfill doctrine (E5.5 / E6) — controlled lineage reconstruction, not data patching.
"""
from __future__ import annotations

from typing import FrozenSet

BACKFILL_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "append_only_events",
        "idempotent_replay_via_hooks",
        "preserve_operational_occurred_at",
        "preserve_policy_pack_at_run_time",
        "preserve_classification_from_event_registry",
        "no_event_updates",
        "no_smart_recomputation",
        "no_balance_materialization",
        "audited_runs_in_finance_backfill_runs",
        "correlation_group_per_run",
    }
)

BACKFILL_FORBIDDEN: FrozenSet[str] = frozenset(
    {
        "update financial_events",
        "delete financial_events",
        "recompute balances",
        "change occurred_at on existing",
        "apply current policy to historical rows retroactively without audit",
    }
)
