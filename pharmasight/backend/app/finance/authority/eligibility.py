"""
E6.7 posting eligibility — who may interpret lineage into accounting proposals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.authority.doctrine import (
    BLOCKING_COMMERCIAL_STATES,
    POSTING_ELIGIBLE_COMMERCIAL_STATES,
)
from app.finance.governance.permissions import resolves_finance_permission
from app.models.commercial_transaction import CommercialTransaction
from app.models.financial_event import FinancialEvent


@dataclass(frozen=True)
class PostingEligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]
    commercial_state: Optional[str]
    requires_permission: str


def _commercial_tx_for_event(db: Session, event: FinancialEvent) -> Optional[CommercialTransaction]:
    if event.source_entity_type != "sales_invoice":
        return None
    return (
        db.query(CommercialTransaction)
        .filter(
            CommercialTransaction.company_id == event.company_id,
            CommercialTransaction.sales_invoice_id == event.source_entity_id,
        )
        .first()
    )


def assess_posting_eligibility(
    db: Session,
    *,
    company_id: UUID,
    financial_event_id: UUID,
    user_id: UUID,
    branch_id: Optional[UUID] = None,
    for_post: bool = False,
) -> PostingEligibilityResult:
    """
    Determine if a financial_event may generate or post an accounting proposal.
    """
    reasons: List[str] = []
    perm = "finance.gl.post" if for_post else "finance.gl.view"
    if not resolves_finance_permission(db, user_id, perm, branch_id=branch_id):
        reasons.append(f"missing_permission:{perm}")

    event = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.id == financial_event_id, FinancialEvent.company_id == company_id)
        .first()
    )
    if not event:
        return PostingEligibilityResult(False, ("event_not_found",), None, perm)

    reversed_exists = (
        db.query(FinancialEvent.id)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.reversal_of_event_id == event.id,
        )
        .first()
    )
    if reversed_exists:
        reasons.append("lineage_reversed")

    if event.reversal_of_event_id:
        reasons.append("event_is_compensation")

    commercial_state: Optional[str] = None
    ctx = _commercial_tx_for_event(db, event)
    if ctx:
        commercial_state = str(ctx.constitutional_state)
        if commercial_state in BLOCKING_COMMERCIAL_STATES:
            reasons.append(f"commercial_state_blocked:{commercial_state}")
        elif commercial_state not in POSTING_ELIGIBLE_COMMERCIAL_STATES:
            reasons.append(f"commercial_state_not_eligible:{commercial_state}")
    # Non-invoice events (supplier, expense, insurance) — lineage-only eligibility
    else:
        commercial_state = None

    eligible = len(reasons) == 0
    return PostingEligibilityResult(
        eligible=eligible,
        reasons=tuple(reasons),
        commercial_state=commercial_state,
        requires_permission=perm,
    )
