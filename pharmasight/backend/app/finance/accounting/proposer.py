"""
E7 journal proposal generation — derived from immutable financial_events only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.finance.accounting.guards import block_lineage_model_mutation
from app.finance.accounting.registry import get_proposal_template
from app.finance.authority.eligibility import assess_posting_eligibility
from app.finance.events.settlement import fetch_settlement_links_for_event
from app.models.commercial_transaction import CommercialTransaction
from app.models.financial_event import FinancialEvent
from app.models.journal_proposal import JournalProposal, JournalProposalEvidence, JournalProposalLine

logger = logging.getLogger("pharmasight.finance.accounting")


@dataclass(frozen=True)
class ProposalOutcome:
    created: bool
    proposal_id: Optional[UUID]
    message: str


def _next_proposal_number(db: Session, company_id: UUID) -> str:
    n = (
        db.query(JournalProposal)
        .filter(JournalProposal.company_id == company_id)
        .count()
    )
    return f"JP-{n + 1:06d}"


def generate_journal_proposal_from_event(
    db: Session,
    *,
    company_id: UUID,
    financial_event_id: UUID,
    actor_user_id: UUID,
    policy_pack_id: str = "STANDARD_KENYA",
    reversal_of_proposal_id: Optional[UUID] = None,
) -> ProposalOutcome:
    block_lineage_model_mutation(None)

    eligibility = assess_posting_eligibility(
        db, company_id=company_id, financial_event_id=financial_event_id, user_id=actor_user_id
    )
    if not eligibility.eligible:
        return ProposalOutcome(False, None, f"ineligible: {','.join(eligibility.reasons)}")

    event = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.id == financial_event_id, FinancialEvent.company_id == company_id)
        .first()
    )
    if not event:
        return ProposalOutcome(False, None, "event_not_found")

    idem = f"proposal:{event.id}:{policy_pack_id}"
    if reversal_of_proposal_id:
        idem = f"proposal_reversal:{reversal_of_proposal_id}:{event.id}"

    existing = (
        db.query(JournalProposal)
        .filter(JournalProposal.company_id == company_id, JournalProposal.idempotency_key == idem)
        .first()
    )
    if existing:
        return ProposalOutcome(False, existing.id, "duplicate_proposal")

    try:
        tpl = get_proposal_template(event.event_type, policy_pack_id=policy_pack_id)
    except KeyError as e:
        return ProposalOutcome(False, None, str(e))

    amount = Decimal(str(event.amount or 0))
    if amount <= 0:
        return ProposalOutcome(False, None, "non_positive_event_amount")

    commercial_tx_id = None
    if event.source_entity_type == "sales_invoice":
        ctx = (
            db.query(CommercialTransaction)
            .filter(
                CommercialTransaction.company_id == company_id,
                CommercialTransaction.sales_invoice_id == event.source_entity_id,
            )
            .first()
        )
        if ctx:
            commercial_tx_id = ctx.id

    proposal = JournalProposal(
        company_id=company_id,
        branch_id=event.branch_id,
        proposal_number=_next_proposal_number(db, company_id),
        status="draft",
        policy_pack_id=policy_pack_id,
        source_financial_event_id=event.id,
        reversal_of_proposal_id=reversal_of_proposal_id,
        commercial_transaction_id=commercial_tx_id,
        idempotency_key=idem,
        currency_code=event.currency_code or "KES",
        total_amount=amount,
        occurred_at=event.occurred_at,
        governance_metadata_json={
            "event_type": event.event_type,
            "source_entity_type": event.source_entity_type,
            "source_entity_id": str(event.source_entity_id),
            "correlation_group": event.correlation_group,
            "emission_channel": event.emission_channel,
            "derived": True,
            "authoritative": False,
        },
        created_by=actor_user_id,
    )
    db.add(proposal)
    db.flush()

    for idx, line_tpl in enumerate(tpl.lines, start=1):
        line_amount = amount * Decimal(str(line_tpl.amount_factor))
        direction = line_tpl.line_direction
        if reversal_of_proposal_id:
            direction = "credit" if direction == "debit" else "debit"
        db.add(
            JournalProposalLine(
                journal_proposal_id=proposal.id,
                line_order=idx,
                account_semantic=line_tpl.account_semantic,
                line_direction=direction,
                amount=line_amount,
                description=line_tpl.description,
            )
        )

    db.add(
        JournalProposalEvidence(
            journal_proposal_id=proposal.id,
            financial_event_id=event.id,
            link_semantic="primary_source",
        )
    )

    links = fetch_settlement_links_for_event(db, company_id=company_id, event_id=event.id)
    for link_row in links.get("settled_by", []):
        db.add(
            JournalProposalEvidence(
                journal_proposal_id=proposal.id,
                financial_event_id=link_row.settlement_event_id,
                link_semantic="settlement_context",
            )
        )

    try:
        db.commit()
        db.refresh(proposal)
        return ProposalOutcome(True, proposal.id, "created")
    except IntegrityError:
        db.rollback()
        dup = (
            db.query(JournalProposal)
            .filter(JournalProposal.company_id == company_id, JournalProposal.idempotency_key == idem)
            .first()
        )
        return ProposalOutcome(False, dup.id if dup else None, "duplicate_proposal")
