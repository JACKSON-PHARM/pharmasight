"""
Governed projection registry (E5 / E6) — every entry is a validated ProjectionContract.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List

from app.finance.doctrine.projection import (
    ProjectionContract,
    contract_to_introspection,
    validate_projection_registry,
)
from app.finance.governance.classification import (
    BRANCH_FINANCE,
    CONFIDENTIAL,
    MANAGEMENT,
)

PROJECTION_REGISTRY: Dict[str, ProjectionContract] = {
    "branch_cash_movement": ProjectionContract(
        projection_id="branch_cash_movement",
        title="Branch cash movement (derived)",
        description="Period inflow/outflow from financial_events — movement stream, not balance.",
        permission="finance.reports.management",
        classification=BRANCH_FINANCE,
        branch_scoped=True,
        company_scoped=False,
        lineage_source="financial_events",
        lineage_event_types=(
            "cash_received",
            "retail_cash_collected",
            "insurance_settlement_received",
            "cash_paid",
            "expense_recognized",
        ),
        replay_rebuildable=True,
        policy_pack_aware=True,
        temporal_basis="occurred_at",
        temporal_semantics="occurred_at within [since, until]; period movement only",
        consistency="current",
        scope_expectation="BRANCH",
        cacheable=False,
        authoritative=False,
        mutates_operational_truth=False,
        persists_balances=False,
        notes="Disposable snapshot — rebuildable from events.",
    ),
    "ar_recognized_vs_collected": ProjectionContract(
        projection_id="ar_recognized_vs_collected",
        title="AR recognized vs collected",
        description="Wholesale AR accrual vs customer payment inflows from lineage.",
        permission="finance.reports.management",
        classification=MANAGEMENT,
        branch_scoped=True,
        company_scoped=False,
        lineage_source="financial_events + settlement_links",
        lineage_event_types=("receivable_accrued", "cash_received"),
        replay_rebuildable=True,
        policy_pack_aware=True,
        temporal_basis="occurred_at",
        temporal_semantics="occurred_at window",
        consistency="current",
        scope_expectation="BRANCH",
        cacheable=False,
        authoritative=False,
        mutates_operational_truth=False,
        persists_balances=False,
    ),
    "insurance_claim_exposure": ProjectionContract(
        projection_id="insurance_claim_exposure",
        title="Insurance claim economic exposure",
        description="Claim accrual vs settlement inflow — claim lifecycle lineage only.",
        permission="finance.reports.management",
        classification=CONFIDENTIAL,
        branch_scoped=True,
        company_scoped=False,
        lineage_source="financial_events",
        lineage_event_types=("insurance_claim_recognized", "insurance_settlement_received"),
        replay_rebuildable=True,
        policy_pack_aware=True,
        temporal_basis="occurred_at",
        temporal_semantics="occurred_at window",
        consistency="current",
        scope_expectation="BRANCH",
        cacheable=False,
        authoritative=False,
        mutates_operational_truth=False,
        persists_balances=False,
    ),
    "lineage_integrity_summary": ProjectionContract(
        projection_id="lineage_integrity_summary",
        title="Lineage integrity summary",
        description="Aggregated integrity findings — operational tables remain truth.",
        permission="finance.reports.audit_read",
        classification=BRANCH_FINANCE,
        branch_scoped=True,
        company_scoped=False,
        lineage_source="integrity verifier + financial_events",
        lineage_event_types=(),
        replay_rebuildable=True,
        policy_pack_aware=False,
        temporal_basis="as_of_query",
        temporal_semantics="as-of query execution",
        consistency="current",
        scope_expectation="BRANCH",
        cacheable=False,
        authoritative=False,
        mutates_operational_truth=False,
        persists_balances=False,
    ),
    "treasury_routing_snapshot": ProjectionContract(
        projection_id="treasury_routing_snapshot",
        title="Treasury routing movement snapshot",
        description="Period movement by routing bucket — not cumulative treasury position.",
        permission="finance.cashbook.view_branch",
        classification=BRANCH_FINANCE,
        branch_scoped=True,
        company_scoped=False,
        lineage_source="financial_events + cashbook_accounts",
        lineage_event_types=(
            "cash_received",
            "retail_cash_collected",
            "insurance_settlement_received",
            "cash_paid",
            "expense_recognized",
        ),
        replay_rebuildable=True,
        policy_pack_aware=False,
        temporal_basis="occurred_at",
        temporal_semantics="occurred_at window; routing channel movement only",
        consistency="current",
        scope_expectation="BRANCH",
        cacheable=False,
        authoritative=False,
        mutates_operational_truth=False,
        persists_balances=False,
        notes="Uses routing_type channels — not account balances.",
    ),
    "settlement_graph_health": ProjectionContract(
        projection_id="settlement_graph_health",
        title="Settlement graph health",
        description="Read-only settlement link semantics verification.",
        permission="finance.reports.audit_read",
        classification=BRANCH_FINANCE,
        branch_scoped=True,
        company_scoped=False,
        lineage_source="financial_event_settlement_links",
        lineage_event_types=(),
        replay_rebuildable=True,
        policy_pack_aware=False,
        temporal_basis="as_of_query",
        temporal_semantics="as-of query — graph state at read time",
        consistency="current",
        scope_expectation="BRANCH",
        cacheable=False,
        authoritative=False,
        mutates_operational_truth=False,
        persists_balances=False,
    ),
}

# E6: fail fast if any contract violates doctrine
validate_projection_registry(PROJECTION_REGISTRY)


def get_projection_spec(projection_id: str) -> ProjectionContract:
    spec = PROJECTION_REGISTRY.get(projection_id)
    if spec is None:
        raise KeyError(f"Unknown projection: {projection_id}")
    return spec


def list_projection_ids() -> FrozenSet[str]:
    return frozenset(PROJECTION_REGISTRY.keys())


def introspect_projection_registry() -> List[dict]:
    return [contract_to_introspection(s) for s in PROJECTION_REGISTRY.values()]
