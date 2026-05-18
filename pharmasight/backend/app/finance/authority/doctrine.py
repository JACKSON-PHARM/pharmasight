"""
E6.7 — Authority & transition governance doctrine.

Bridges constitutional commercial spine with finance lineage / accounting eligibility.
"""
from __future__ import annotations

from typing import FrozenSet

from app.domain.commercial_transaction_state import TransactionState

# Institutional roles (map to permissions in eligibility.py)
AUTHORITY_ROLES: FrozenSet[str] = frozenset(
    {
        "operational_staff",
        "branch_finance",
        "billing_clerk",
        "finance_manager",
        "finance_auditor",
        "fiscal_officer",
        "system",
    }
)

# Commercial transitions and required permission hints
TRANSITION_AUTHORITY: dict[str, dict[str, str]] = {
    "commercial_stabilization": {
        "target_states": "BILLING_ACCEPTED,FISCAL_READY",
        "permission_hint": "sales.edit or hospital.billing.adjust",
    },
    "fiscal_externalization": {
        "target_states": "FISCAL_EXTERNALIZED",
        "permission_hint": "fiscal_officer / eTIMS submit workflow",
    },
    "settlement_active": {
        "target_states": "SETTLEMENT_ACTIVE",
        "permission_hint": "wholesale.ar.collect or retail.till.operate",
    },
    "dispute_freeze": {
        "target_states": "DISPUTE_FROZEN",
        "permission_hint": "finance.reports.management",
    },
    "accounting_proposal": {
        "action": "generate_journal_proposal",
        "permission": "finance.gl.view",
    },
    "accounting_approve": {
        "action": "approve_journal_proposal",
        "permission": "finance.gl.post",
    },
    "accounting_post": {
        "action": "post_journal_proposal",
        "permission": "finance.gl.post",
    },
}

# States that permit accounting interpretation (posting eligibility)
POSTING_ELIGIBLE_COMMERCIAL_STATES: FrozenSet[str] = frozenset(
    {
        TransactionState.BILLING_ACCEPTED.value,
        TransactionState.FISCAL_READY.value,
        TransactionState.FISCAL_EXTERNALIZED.value,
        TransactionState.SETTLEMENT_ACTIVE.value,
        TransactionState.SETTLEMENT_CLOSED.value,
    }
)

BLOCKING_COMMERCIAL_STATES: FrozenSet[str] = frozenset(
    {
        TransactionState.DRAFT.value,
        TransactionState.EXCEPTION_HOLD.value,
        TransactionState.DISPUTE_FROZEN.value,
        TransactionState.REVERSED.value,
    }
)

MUTATION_WINDOWS: dict[str, str] = {
    "operational_edit": "DRAFT only — sales invoice lines editable",
    "commercial_batch": "DRAFT -> BATCHED locks stock economics",
    "fiscal_externalization": "After FISCAL_READY; KRA/eTIMS is external authority",
    "lineage_immutable": "financial_events append-only after emit",
    "proposal_mutable": "journal_proposals editable only in draft status",
    "posted_immutable": "posted proposals require reversal proposal, never edit",
}

REVERSIBILITY_TYPES: dict[str, str] = {
    "operational_correction": "Edit operational source before batch (DRAFT)",
    "commercial_reversal": "constitutional_state -> REVERSED on commercial_transactions",
    "lineage_compensation": "financial_events reversal_of_event_id append-only",
    "settlement_append": "settlement_links append-only; no link deletion",
    "accounting_reversal": "new journal_proposal with reversal_of_proposal_id",
    "fiscal_credit_note": "operational + KRA workflow — not lineage mutation",
    "accounting_adjustment": "separate proposal artifact — never mutates events",
}

EXTERNALIZATION_BOUNDARIES: dict[str, str] = {
    "pre_externalization": "Internal commercial truth editable per mutation windows",
    "fiscal_ready": "Ready for regulator submission — internal edits restricted",
    "fiscal_externalized": "KRA/eTIMS submission is external fiscal authority",
    "post_externalization": "Commercial spine locked; corrections via reversal/amendment paths",
    "lineage_never_external": "financial_events remain economic evidence, not KRA payload clone",
}

AUTHORITY_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "commercial_spine_is_operational_constitutional_truth",
        "financial_events_are_economic_evidence",
        "projections_are_never_authoritative",
        "accounting_proposals_are_interpretation_only",
        "posting_never_mutates_lineage",
        "fiscal_externalization_is_separate_from_accounting_post",
    }
)


def introspect_authority_doctrine() -> dict:
    return {
        "authority_roles": sorted(AUTHORITY_ROLES),
        "transition_authority": TRANSITION_AUTHORITY,
        "posting_eligible_commercial_states": sorted(POSTING_ELIGIBLE_COMMERCIAL_STATES),
        "blocking_commercial_states": sorted(BLOCKING_COMMERCIAL_STATES),
        "mutation_windows": MUTATION_WINDOWS,
        "reversibility_types": REVERSIBILITY_TYPES,
        "externalization_boundaries": EXTERNALIZATION_BOUNDARIES,
        "invariants": sorted(AUTHORITY_INVARIANTS),
    }
