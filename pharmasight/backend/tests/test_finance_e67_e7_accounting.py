"""
E6.7 authority + E7 accounting orchestration tests (doctrine & templates).
"""
from app.finance.accounting.doctrine import ACCOUNTING_INVARIANTS, PROPOSAL_STATUS_FLOW
from app.finance.accounting.registry import (
    STANDARD_KENYA_TEMPLATES,
    get_proposal_template,
    list_supported_event_types,
)
from app.finance.authority.doctrine import (
    AUTHORITY_INVARIANTS,
    BLOCKING_COMMERCIAL_STATES,
    POSTING_ELIGIBLE_COMMERCIAL_STATES,
)
from app.finance.doctrine.orchestration_boundary import E7_FORBIDDEN_ON_LINEAGE
from app.domain.commercial_transaction_state import TransactionState


def test_authority_posting_eligible_states():
    assert TransactionState.BILLING_ACCEPTED.value in POSTING_ELIGIBLE_COMMERCIAL_STATES
    assert TransactionState.EXCEPTION_HOLD.value in BLOCKING_COMMERCIAL_STATES


def test_accounting_invariants_forbid_lineage_mutation():
    assert "proposals_never_mutate_lineage" in ACCOUNTING_INVARIANTS
    assert any("financial_events" in x for x in E7_FORBIDDEN_ON_LINEAGE)


def test_proposal_templates_balanced_pairs():
    for event_type in list_supported_event_types():
        tpl = get_proposal_template(event_type)
        debits = [l for l in tpl.lines if l.line_direction == "debit"]
        credits = [l for l in tpl.lines if l.line_direction == "credit"]
        assert len(debits) >= 1
        assert len(credits) >= 1


def test_proposal_status_flow_posted_immutable():
    assert "posted" in PROPOSAL_STATUS_FLOW["approved"]
    assert PROPOSAL_STATUS_FLOW["posted"] == frozenset({"superseded"})


def test_supported_event_types_count():
    assert "receivable_accrued" in STANDARD_KENYA_TEMPLATES
    assert "insurance_claim_recognized" in STANDARD_KENYA_TEMPLATES


def test_authority_invariants():
    assert "posting_never_mutates_lineage" in AUTHORITY_INVARIANTS
