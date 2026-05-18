"""
Settlement graph semantics (E5.5 / E6) — append-only economic relationships, not reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.financial_event import FinancialEvent, FinancialEventSettlementLink

SETTLEMENT_RULES: dict[str, str | bool] = {
    "links_are_append_only": True,
    "links_are_immutable": True,
    "cycles_allowed": False,
    "prevent_cycles_before_insert": True,
    "one_payment_many_accruals": True,
    "one_accrual_many_payments": True,
    "cross_branch_settlement_allowed": False,
    "orphan_settlement_links_allowed": False,
    "reversals_reverse_events_not_links": True,
    "settlement_semantics_required": True,
}


@dataclass(frozen=True)
class SettlementGraphFinding:
    code: str
    severity: str
    message: str
    settlement_event_id: Optional[UUID] = None
    settles_event_id: Optional[UUID] = None


def would_create_settlement_cycle(
    db: Session,
    *,
    company_id: UUID,
    settlement_event_id: UUID,
    settles_event_id: UUID,
) -> bool:
    """
    Preventative check (E6.5): True if inserting this link would create a forbidden cycle.

    Currently enforces: direct mutual cycle (A settles B while B settles A).
    """
    if settlement_event_id == settles_event_id:
        return True
    reverse = (
        db.query(FinancialEventSettlementLink)
        .filter(
            FinancialEventSettlementLink.company_id == company_id,
            FinancialEventSettlementLink.settlement_event_id == settles_event_id,
            FinancialEventSettlementLink.settles_event_id == settlement_event_id,
        )
        .first()
    )
    return reverse is not None


def verify_settlement_graph(
    db: Session,
    *,
    company_id: UUID,
    branch_id: Optional[UUID] = None,
    limit: int = 2000,
) -> List[SettlementGraphFinding]:
    """
    Read-only settlement graph health check.

    Detects: cross-branch links, orphan accrual references, simple cycles.
    """
    findings: List[SettlementGraphFinding] = []
    q = db.query(FinancialEventSettlementLink).filter(
        FinancialEventSettlementLink.company_id == company_id
    )
    links = q.limit(limit).all()
    if not links:
        return findings

    event_ids: Set[UUID] = set()
    for link in links:
        event_ids.add(link.settlement_event_id)
        event_ids.add(link.settles_event_id)

    events = {
        e.id: e
        for e in db.query(FinancialEvent).filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.id.in_(event_ids),
        ).all()
    }

    for link in links:
        settlement = events.get(link.settlement_event_id)
        accrual = events.get(link.settles_event_id)
        if settlement is None or accrual is None:
            findings.append(
                SettlementGraphFinding(
                    code="orphan_settlement_link",
                    severity="warning",
                    message="Settlement link references missing financial_event",
                    settlement_event_id=link.settlement_event_id,
                    settles_event_id=link.settles_event_id,
                )
            )
            continue
        if branch_id and settlement.branch_id != branch_id:
            continue
        if settlement.branch_id != accrual.branch_id:
            findings.append(
                SettlementGraphFinding(
                    code="cross_branch_settlement",
                    severity="error",
                    message="Settlement link crosses branch_id (forbidden)",
                    settlement_event_id=link.settlement_event_id,
                    settles_event_id=link.settles_event_id,
                )
            )
        if link.amount_settled is not None and Decimal(str(link.amount_settled)) <= 0:
            findings.append(
                SettlementGraphFinding(
                    code="invalid_settlement_amount",
                    severity="error",
                    message="Settlement amount must be positive",
                    settlement_event_id=link.settlement_event_id,
                    settles_event_id=link.settles_event_id,
                )
            )

    # Simple 2-node cycle: A settles B and B settles A
    pair_settles: dict[tuple[UUID, UUID], bool] = {}
    for link in links:
        pair_settles[(link.settlement_event_id, link.settles_event_id)] = True
    for link in links:
        if pair_settles.get((link.settles_event_id, link.settlement_event_id)):
            findings.append(
                SettlementGraphFinding(
                    code="settlement_cycle_detected",
                    severity="error",
                    message="Mutual settlement link cycle detected",
                    settlement_event_id=link.settlement_event_id,
                    settles_event_id=link.settles_event_id,
                )
            )

    return findings


def introspect_settlement_rules() -> dict:
    return dict(SETTLEMENT_RULES)
