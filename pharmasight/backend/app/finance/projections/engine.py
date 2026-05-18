"""
Projection execution engine (E5 / E6) — read-only derived views with contract envelope.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.finance.doctrine.projection import ProjectionContract, wrap_projection_payload
from app.finance.doctrine.settlement import verify_settlement_graph
from app.finance.doctrine.temporal import resolve_temporal_filter
from app.finance.events.integrity import verify_company_lineage
from app.finance.projections.registry import get_projection_spec
from app.models.financial_event import FinancialEvent


def execute_projection(
    db: Session,
    *,
    projection_id: str,
    company_id: UUID,
    branch_id: Optional[UUID] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
) -> Dict[str, Any]:
    spec = get_projection_spec(projection_id)
    since_dt, until_dt = resolve_temporal_filter(
        temporal_basis=spec.temporal_basis,
        since=since,
        until=until,
    )

    if projection_id == "branch_cash_movement":
        payload = _branch_cash_movement(db, company_id, branch_id, since_dt, until_dt, spec)
    elif projection_id == "ar_recognized_vs_collected":
        payload = _ar_recognized_vs_collected(db, company_id, branch_id, since_dt, until_dt, spec)
    elif projection_id == "insurance_claim_exposure":
        payload = _insurance_claim_exposure(db, company_id, branch_id, since_dt, until_dt, spec)
    elif projection_id == "lineage_integrity_summary":
        payload = _lineage_integrity_summary(db, company_id, branch_id, since, spec)
    elif projection_id == "treasury_routing_snapshot":
        payload = _treasury_routing_snapshot(db, company_id, branch_id, since_dt, until_dt, spec)
    elif projection_id == "settlement_graph_health":
        payload = _settlement_graph_health(db, company_id, branch_id, spec)
    else:
        raise KeyError(projection_id)

    return wrap_projection_payload(spec, payload)


def _base_event_query(
    db: Session,
    company_id: UUID,
    branch_id: Optional[UUID],
    since_dt: Optional[datetime],
    until_dt: datetime,
    *,
    temporal_basis: str = "occurred_at",
):
    q = db.query(FinancialEvent).filter(FinancialEvent.company_id == company_id)
    if branch_id:
        q = q.filter(FinancialEvent.branch_id == branch_id)
    time_col = FinancialEvent.emitted_at if temporal_basis == "emitted_at" else FinancialEvent.occurred_at
    if since_dt:
        q = q.filter(time_col >= since_dt)
    q = q.filter(time_col <= until_dt)
    return q


def _branch_cash_movement(
    db, company_id, branch_id, since_dt, until_dt, spec: ProjectionContract
) -> Dict[str, Any]:
    inflow_types = tuple(t for t in spec.lineage_event_types if "received" in t or "collected" in t)
    outflow_types = tuple(t for t in spec.lineage_event_types if t in ("cash_paid", "expense_recognized"))
    q = _base_event_query(db, company_id, branch_id, since_dt, until_dt, temporal_basis=spec.temporal_basis)
    rows = q.filter(FinancialEvent.event_type.in_(inflow_types + outflow_types)).all()
    inflow = sum(
        Decimal(str(r.amount))
        for r in rows
        if r.event_type in inflow_types and r.economic_direction == "inflow"
    )
    outflow = sum(
        Decimal(str(r.amount))
        for r in rows
        if r.event_type in outflow_types or r.economic_direction == "outflow"
    )
    return {
        "projection_id": spec.projection_id,
        "derived": True,
        "authoritative": False,
        "period_inflow": str(inflow),
        "period_outflow": str(outflow),
        "period_net_movement": str(inflow - outflow),
        "event_count": len(rows),
        "disclaimer": "Period movement stream only — not a stored routing balance.",
    }


def _ar_recognized_vs_collected(
    db, company_id, branch_id, since_dt, until_dt, spec: ProjectionContract
) -> Dict[str, Any]:
    q = _base_event_query(db, company_id, branch_id, since_dt, until_dt, temporal_basis=spec.temporal_basis)
    accrued = (
        q.filter(FinancialEvent.event_type == "receivable_accrued")
        .with_entities(func.coalesce(func.sum(FinancialEvent.amount), 0))
        .scalar()
    )
    collected = (
        _base_event_query(db, company_id, branch_id, since_dt, until_dt, temporal_basis=spec.temporal_basis)
        .filter(FinancialEvent.event_type == "cash_received")
        .with_entities(func.coalesce(func.sum(FinancialEvent.amount), 0))
        .scalar()
    )
    return {
        "projection_id": spec.projection_id,
        "derived": True,
        "authoritative": False,
        "recognized_accrual": str(accrued or 0),
        "collected_inflow": str(collected or 0),
        "disclaimer": "Rebuildable from immutable events.",
    }


def _insurance_claim_exposure(
    db, company_id, branch_id, since_dt, until_dt, spec: ProjectionContract
) -> Dict[str, Any]:
    q = _base_event_query(db, company_id, branch_id, since_dt, until_dt, temporal_basis=spec.temporal_basis)
    recognized = (
        q.filter(FinancialEvent.event_type == "insurance_claim_recognized")
        .with_entities(func.coalesce(func.sum(FinancialEvent.amount), 0))
        .scalar()
    )
    settled = (
        _base_event_query(db, company_id, branch_id, since_dt, until_dt, temporal_basis=spec.temporal_basis)
        .filter(FinancialEvent.event_type == "insurance_settlement_received")
        .with_entities(func.coalesce(func.sum(FinancialEvent.amount), 0))
        .scalar()
    )
    return {
        "projection_id": spec.projection_id,
        "derived": True,
        "authoritative": False,
        "claim_accrual": str(recognized or 0),
        "settlement_inflow": str(settled or 0),
        "disclaimer": "Claim lifecycle lineage — not insurance accounting.",
    }


def _lineage_integrity_summary(
    db, company_id, branch_id, since, spec: ProjectionContract
) -> Dict[str, Any]:
    since_dt = (
        datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc) if since else None
    )
    findings = verify_company_lineage(
        db, company_id=company_id, branch_id=branch_id, since=since_dt, limit=500
    )
    by_kind: Dict[str, int] = {}
    for f in findings:
        by_kind[f.code] = by_kind.get(f.code, 0) + 1
    return {
        "projection_id": spec.projection_id,
        "derived": True,
        "authoritative": False,
        "finding_count": len(findings),
        "findings_by_type": by_kind,
        "disclaimer": "Operational tables remain source of truth.",
    }


def _treasury_routing_snapshot(
    db, company_id, branch_id, since_dt, until_dt, spec: ProjectionContract
) -> Dict[str, Any]:
    from app.models.cashbook_account import CashbookAccount

    accounts = (
        db.query(CashbookAccount)
        .filter(CashbookAccount.company_id == company_id, CashbookAccount.is_active.is_(True))
        .all()
    )
    if branch_id:
        accounts = [a for a in accounts if a.branch_id is None or a.branch_id == branch_id]

    inflow_types = (
        "cash_received",
        "retail_cash_collected",
        "insurance_settlement_received",
    )
    q = _base_event_query(db, company_id, branch_id, since_dt, until_dt, temporal_basis=spec.temporal_basis)
    rows = q.filter(
        FinancialEvent.event_type.in_(inflow_types + ("cash_paid", "expense_recognized"))
    ).all()

    routing_movement: Dict[str, Decimal] = {}
    for acct in accounts:
        routing_movement[acct.routing_type] = routing_movement.get(acct.routing_type, Decimal("0"))

    for r in rows:
        mode = (r.payload_json or {}).get("payment_mode") or (r.payload_json or {}).get("method") or "cash"
        channel = (
            "mpesa"
            if str(mode).lower() == "mpesa"
            else "bank"
            if str(mode).lower() == "bank"
            else "till"
        )
        amt = Decimal(str(r.amount))
        if r.economic_direction == "inflow":
            routing_movement[channel] = routing_movement.get(channel, Decimal("0")) + amt
        elif r.economic_direction == "outflow":
            routing_movement[channel] = routing_movement.get(channel, Decimal("0")) - amt

    return {
        "projection_id": spec.projection_id,
        "derived": True,
        "authoritative": False,
        "routing_period_movement": {k: str(v) for k, v in routing_movement.items()},
        "routing_bucket_count": len(accounts),
        "disclaimer": "Treasury channel movement — not cumulative position.",
    }


def _settlement_graph_health(db, company_id, branch_id, spec: ProjectionContract) -> Dict[str, Any]:
    findings = verify_settlement_graph(db, company_id=company_id, branch_id=branch_id)
    errors = [f for f in findings if f.severity == "error"]
    return {
        "projection_id": spec.projection_id,
        "derived": True,
        "authoritative": False,
        "finding_count": len(findings),
        "error_count": len(errors),
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "message": f.message,
                "settlement_event_id": str(f.settlement_event_id) if f.settlement_event_id else None,
                "settles_event_id": str(f.settles_event_id) if f.settles_event_id else None,
            }
            for f in findings
        ],
        "disclaimer": "Settlement links are append-only; reversals compensate events not links.",
    }
