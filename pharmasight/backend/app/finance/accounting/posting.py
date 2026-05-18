"""
E7 posting orchestration — approve and commit interpretation (never mutates lineage).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.accounting.doctrine import PROPOSAL_STATUS_FLOW
from app.finance.accounting.guards import block_lineage_model_mutation
from app.finance.accounting.proposer import generate_journal_proposal_from_event
from app.finance.authority.eligibility import assess_posting_eligibility
from app.models.journal_proposal import AccountingPostingRecord, JournalProposal


@dataclass(frozen=True)
class PostingOutcome:
    success: bool
    message: str
    proposal_id: UUID


def _get_proposal(db: Session, company_id: UUID, proposal_id: UUID) -> Optional[JournalProposal]:
    return (
        db.query(JournalProposal)
        .filter(JournalProposal.id == proposal_id, JournalProposal.company_id == company_id)
        .first()
    )


def approve_journal_proposal(
    db: Session,
    *,
    company_id: UUID,
    proposal_id: UUID,
    actor_user_id: UUID,
) -> PostingOutcome:
    block_lineage_model_mutation(None)
    proposal = _get_proposal(db, company_id, proposal_id)
    if not proposal:
        return PostingOutcome(False, "not_found", proposal_id)
    if proposal.status != "draft":
        return PostingOutcome(False, f"invalid_status:{proposal.status}", proposal_id)
    if "approved" not in PROPOSAL_STATUS_FLOW.get("draft", frozenset()):
        return PostingOutcome(False, "transition_forbidden", proposal_id)

    eligibility = assess_posting_eligibility(
        db,
        company_id=company_id,
        financial_event_id=proposal.source_financial_event_id,
        user_id=actor_user_id,
        branch_id=proposal.branch_id,
        for_post=True,
    )
    if not eligibility.eligible:
        return PostingOutcome(False, f"ineligible:{','.join(eligibility.reasons)}", proposal_id)

    proposal.status = "approved"
    proposal.approved_by = actor_user_id
    proposal.approved_at = datetime.now(timezone.utc)
    db.commit()
    return PostingOutcome(True, "approved", proposal_id)


def post_journal_proposal(
    db: Session,
    *,
    company_id: UUID,
    proposal_id: UUID,
    actor_user_id: UUID,
) -> PostingOutcome:
    block_lineage_model_mutation(None)
    proposal = _get_proposal(db, company_id, proposal_id)
    if not proposal:
        return PostingOutcome(False, "not_found", proposal_id)
    if proposal.status != "approved":
        return PostingOutcome(False, f"must_be_approved:{proposal.status}", proposal_id)

    eligibility = assess_posting_eligibility(
        db,
        company_id=company_id,
        financial_event_id=proposal.source_financial_event_id,
        user_id=actor_user_id,
        branch_id=proposal.branch_id,
        for_post=True,
    )
    if not eligibility.eligible:
        return PostingOutcome(False, f"ineligible:{','.join(eligibility.reasons)}", proposal_id)

    existing_post = (
        db.query(AccountingPostingRecord)
        .filter(AccountingPostingRecord.journal_proposal_id == proposal.id)
        .first()
    )
    if existing_post:
        return PostingOutcome(False, "already_posted", proposal_id)

    now = datetime.now(timezone.utc)
    proposal.status = "posted"
    proposal.posted_by = actor_user_id
    proposal.posted_at = now
    db.add(
        AccountingPostingRecord(
            company_id=company_id,
            journal_proposal_id=proposal.id,
            posted_by=actor_user_id,
            posted_at=now,
            posting_semantic="interpretation_committed",
            detail_json={
                "authoritative": False,
                "lineage_untouched": True,
                "policy_pack_id": proposal.policy_pack_id,
            },
        )
    )
    db.commit()
    return PostingOutcome(True, "posted", proposal_id)


def reverse_journal_proposal(
    db: Session,
    *,
    company_id: UUID,
    proposal_id: UUID,
    actor_user_id: UUID,
) -> PostingOutcome:
    """Create compensating proposal — never edit posted proposal."""
    block_lineage_model_mutation(None)
    original = _get_proposal(db, company_id, proposal_id)
    if not original:
        return PostingOutcome(False, "not_found", proposal_id)
    if original.status != "posted":
        return PostingOutcome(False, "only_posted_reversible", proposal_id)

    outcome = generate_journal_proposal_from_event(
        db,
        company_id=company_id,
        financial_event_id=original.source_financial_event_id,
        actor_user_id=actor_user_id,
        policy_pack_id=original.policy_pack_id,
        reversal_of_proposal_id=original.id,
    )
    if not outcome.created or not outcome.proposal_id:
        return PostingOutcome(False, outcome.message, proposal_id)

    original.status = "superseded"
    db.commit()
    return PostingOutcome(True, f"reversal_proposal:{outcome.proposal_id}", outcome.proposal_id)
