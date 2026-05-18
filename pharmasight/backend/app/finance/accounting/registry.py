"""
E7 proposal templates — semantic account mapping per financial event type.

account_semantic is interpretation vocabulary, NOT chart_of_accounts.id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ProposalLineTemplate:
    account_semantic: str
    line_direction: str
    amount_factor: float = 1.0
    description: str = ""


@dataclass(frozen=True)
class EventProposalTemplate:
    event_type: str
    policy_pack_id: str
    lines: Tuple[ProposalLineTemplate, ...]


# Standard Kenya retail/wholesale interpretation pack
STANDARD_KENYA_TEMPLATES: dict[str, EventProposalTemplate] = {
    "receivable_accrued": EventProposalTemplate(
        event_type="receivable_accrued",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("accounts_receivable", "debit", description="Customer receivable"),
            ProposalLineTemplate("revenue", "credit", description="Revenue recognition"),
        ),
    ),
    "cash_received": EventProposalTemplate(
        event_type="cash_received",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("cash", "debit", description="Cash receipt"),
            ProposalLineTemplate("accounts_receivable", "credit", description="AR settlement"),
        ),
    ),
    "retail_cash_collected": EventProposalTemplate(
        event_type="retail_cash_collected",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("cash", "debit", description="Retail cash"),
            ProposalLineTemplate("revenue", "credit", description="Retail revenue"),
        ),
    ),
    "payable_recognized": EventProposalTemplate(
        event_type="payable_recognized",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("inventory_or_expense", "debit", description="Purchase recognition"),
            ProposalLineTemplate("accounts_payable", "credit", description="Supplier payable"),
        ),
    ),
    "cash_paid": EventProposalTemplate(
        event_type="cash_paid",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("accounts_payable", "debit", description="AP settlement"),
            ProposalLineTemplate("cash", "credit", description="Cash disbursement"),
        ),
    ),
    "expense_recognized": EventProposalTemplate(
        event_type="expense_recognized",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("operating_expense", "debit", description="Expense"),
            ProposalLineTemplate("cash", "credit", description="Cash out"),
        ),
    ),
    "insurance_claim_recognized": EventProposalTemplate(
        event_type="insurance_claim_recognized",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("insurance_receivable", "debit", description="Insurer receivable"),
            ProposalLineTemplate("revenue", "credit", description="Insurance-funded revenue"),
        ),
    ),
    "insurance_settlement_received": EventProposalTemplate(
        event_type="insurance_settlement_received",
        policy_pack_id="STANDARD_KENYA",
        lines=(
            ProposalLineTemplate("cash", "debit", description="Insurer settlement"),
            ProposalLineTemplate("insurance_receivable", "credit", description="Clear insurer AR"),
        ),
    ),
}


def get_proposal_template(event_type: str, *, policy_pack_id: str = "STANDARD_KENYA") -> EventProposalTemplate:
    key = event_type
    tpl = STANDARD_KENYA_TEMPLATES.get(key)
    if tpl is None:
        raise KeyError(f"No accounting proposal template for event_type={event_type}")
    if tpl.policy_pack_id != policy_pack_id:
        raise KeyError(f"Policy pack {policy_pack_id} not defined for {event_type}")
    return tpl


def list_supported_event_types() -> List[str]:
    return sorted(STANDARD_KENYA_TEMPLATES.keys())
