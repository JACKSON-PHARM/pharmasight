"""
E7 accounting orchestration doctrine — interpretation of lineage, not replacement.
"""
from __future__ import annotations

from typing import FrozenSet

ACCOUNTING_INVARIANTS: FrozenSet[str] = frozenset(
    {
        "proposals_derived_from_financial_events",
        "proposals_never_mutate_lineage",
        "posted_proposals_immutable",
        "reversals_create_new_proposals",
        "no_authoritative_gl_balances",
        "account_semantic_not_coa_substitute",
        "posting_records_append_only",
        "idempotent_proposal_per_event",
    }
)

PROPOSAL_STATUS_FLOW: dict[str, frozenset[str]] = {
    "draft": frozenset({"approved", "voided"}),
    "approved": frozenset({"posted", "voided"}),
    "posted": frozenset({"superseded"}),
    "voided": frozenset(),
    "superseded": frozenset(),
}

REVERSAL_DOCTRINE: dict[str, str] = {
    "lineage": "Compensate via new financial_event with reversal_of_event_id — never UPDATE",
    "settlement": "Append-only links; reversals do not delete links",
    "accounting": "New journal_proposal with reversal_of_proposal_id; mirrors line directions",
}


def introspect_accounting_doctrine() -> dict:
    return {
        "invariants": sorted(ACCOUNTING_INVARIANTS),
        "proposal_status_flow": {k: sorted(v) for k, v in PROPOSAL_STATUS_FLOW.items()},
        "reversal_doctrine": REVERSAL_DOCTRINE,
        "authoritative": False,
    }
