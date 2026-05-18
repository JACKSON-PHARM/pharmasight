"""
Settlement lineage links between financial events (E4) — append-only, not reconciliation.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.finance.doctrine.settlement import SETTLEMENT_RULES, would_create_settlement_cycle
from app.models.financial_event import FinancialEvent, FinancialEventSettlementLink

logger = logging.getLogger("pharmasight.finance.events")

SETTLEMENT_CUSTOMER_PAYMENT = "customer_payment_settles_receivable"
SETTLEMENT_SUPPLIER_PAYMENT = "supplier_payment_settles_payable"
SETTLEMENT_INSURANCE = "insurance_settlement_settles_claim"

SETTLEMENT_PAIRS: dict[str, str] = {
    "cash_received": "receivable_accrued",
    "cash_paid": "payable_recognized",
    "insurance_settlement_received": "insurance_claim_recognized",
}


def find_accrual_event_for_source(
    db: Session,
    *,
    company_id: UUID,
    accrual_event_type: str,
    source_entity_type: str,
    source_entity_id: UUID,
) -> Optional[FinancialEvent]:
    return (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.event_type == accrual_event_type,
            FinancialEvent.source_entity_type == source_entity_type,
            FinancialEvent.source_entity_id == source_entity_id,
        )
        .order_by(FinancialEvent.emitted_at.asc())
        .first()
    )


def record_settlement_link(
    db: Session,
    *,
    company_id: UUID,
    settlement_event_id: UUID,
    settles_event_id: UUID,
    amount_settled: Decimal,
    settlement_semantic: str,
    idempotency_key: str,
) -> bool:
    """Append settlement link. Returns True if created, False if duplicate."""
    if not SETTLEMENT_RULES.get("cross_branch_settlement_allowed", False):
        settlement_ev = (
            db.query(FinancialEvent)
            .filter(FinancialEvent.id == settlement_event_id, FinancialEvent.company_id == company_id)
            .first()
        )
        accrual_ev = (
            db.query(FinancialEvent)
            .filter(FinancialEvent.id == settles_event_id, FinancialEvent.company_id == company_id)
            .first()
        )
        if settlement_ev and accrual_ev and settlement_ev.branch_id != accrual_ev.branch_id:
            logger.warning(
                "settlement link rejected: cross_branch settlement_event=%s settles=%s",
                settlement_event_id,
                settles_event_id,
            )
            return False
    if SETTLEMENT_RULES.get("prevent_cycles_before_insert", True):
        if would_create_settlement_cycle(
            db,
            company_id=company_id,
            settlement_event_id=settlement_event_id,
            settles_event_id=settles_event_id,
        ):
            logger.warning(
                "settlement link rejected: would_create_cycle settlement=%s settles=%s",
                settlement_event_id,
                settles_event_id,
            )
            return False
    try:
        db.add(
            FinancialEventSettlementLink(
                company_id=company_id,
                settlement_event_id=settlement_event_id,
                settles_event_id=settles_event_id,
                amount_settled=abs(Decimal(str(amount_settled))),
                settlement_semantic=settlement_semantic,
                idempotency_key=idempotency_key,
            )
        )
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    except Exception:
        db.rollback()
        logger.debug("settlement link failed", exc_info=True)
        return False


def link_settlement_to_accruals(
    db: Session,
    *,
    company_id: UUID,
    settlement_event: FinancialEvent,
    accrual_event_type: str,
    allocations: List[tuple[UUID, str, Decimal]],
    settlement_semantic: str,
) -> None:
    """
    allocations: list of (source_entity_id, source_entity_type, amount)
    """
    for source_id, source_type, amount in allocations:
        accrual = find_accrual_event_for_source(
            db,
            company_id=company_id,
            accrual_event_type=accrual_event_type,
            source_entity_type=source_type,
            source_entity_id=source_id,
        )
        if not accrual:
            continue
        idem = f"settlement:{settlement_event.id}:settles:{accrual.id}"
        record_settlement_link(
            db,
            company_id=company_id,
            settlement_event_id=settlement_event.id,
            settles_event_id=accrual.id,
            amount_settled=amount,
            settlement_semantic=settlement_semantic,
            idempotency_key=idem,
        )


def resolve_primary_caused_by_event_id(
    db: Session,
    *,
    company_id: UUID,
    accrual_event_type: str,
    allocations: List[tuple[UUID, str, Decimal]],
) -> Optional[UUID]:
    """Pick first matching accrual event for caused_by linkage at emit time (immutable)."""
    for source_id, source_type, _amount in allocations:
        accrual = find_accrual_event_for_source(
            db,
            company_id=company_id,
            accrual_event_type=accrual_event_type,
            source_entity_type=source_type,
            source_entity_id=source_id,
        )
        if accrual:
            return accrual.id
    return None


def fetch_settlement_links_for_event(
    db: Session, *, company_id: UUID, event_id: UUID
) -> dict:
    as_settlement = (
        db.query(FinancialEventSettlementLink)
        .filter(
            FinancialEventSettlementLink.company_id == company_id,
            FinancialEventSettlementLink.settlement_event_id == event_id,
        )
        .all()
    )
    as_settled = (
        db.query(FinancialEventSettlementLink)
        .filter(
            FinancialEventSettlementLink.company_id == company_id,
            FinancialEventSettlementLink.settles_event_id == event_id,
        )
        .all()
    )
    return {"settles": as_settlement, "settled_by": as_settled}
