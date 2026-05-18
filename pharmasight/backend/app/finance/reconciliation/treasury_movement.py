"""
Stage 2A / 2A.5 — Treasury movement shadow reconciliation with coverage intelligence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.finance.projections.engine import execute_projection
from app.finance.reconciliation.legitimacy import (
    LEGITIMACY_LABELS,
    classify_missing_lineage,
    period_interpretation,
    resolve_governance_context,
)
from app.finance.reconciliation.lineage_coverage import (
    get_expectation_for_cashbook_source,
    introspect_lineage_coverage_matrix,
)
from app.finance.reconciliation.source_attribution import (
    attribution_for_entry,
    batch_resolve_attributions,
)
from app.models import CashbookEntry, FinancialEvent
from app.models.financial_event import FinancialEventEmissionFailure

AMOUNT_TOLERANCE = Decimal("0.01")

CASHBOOK_SOURCE_TO_ENTITY: Dict[str, str] = {
    "expense": "expense",
    "supplier_payment": "supplier_payment",
    "sale": "sales_invoice",
    "insurance_settlement": "insurance_settlement",
    "customer_payment": "customer_payment",
}

ENTITY_EXPECTED_EVENT_TYPES: Dict[str, Tuple[str, ...]] = {
    "expense": ("expense_recognized",),
    "supplier_payment": ("cash_paid",),
    "sales_invoice": ("retail_cash_collected", "cash_received"),
    "insurance_settlement": ("insurance_settlement_received",),
    "customer_payment": ("cash_received",),
}

LINEAGE_CASH_EVENT_TYPES = frozenset(
    {
        "cash_received",
        "retail_cash_collected",
        "insurance_settlement_received",
        "cash_paid",
        "expense_recognized",
    }
)

DRIFT_LABELS: Dict[str, str] = {
    "matched": "Matched",
    "timing_drift": "Timing difference",
    "classification_mismatch": "Classification mismatch",
    "amount_mismatch": "Amount mismatch",
    "missing_event_emission": "Missing lineage event",
    "orphan_lineage_record": "Lineage without cashbook entry",
    "replay_inconsistency": "Replay inconsistency",
    "settlement_timing_variance": "Settlement timing variance",
    "totals_mismatch": "Period totals differ",
}

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class DriftItem:
    drift_type: str
    severity: str
    message: str
    cashbook_entry_id: Optional[UUID] = None
    financial_event_id: Optional[UUID] = None
    source_type: Optional[str] = None
    source_id: Optional[UUID] = None
    cashbook_amount: Optional[str] = None
    lineage_amount: Optional[str] = None
    cashbook_date: Optional[str] = None
    lineage_date: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    attribution: Optional[Dict[str, Any]] = None
    legitimacy: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "drift_type": self.drift_type,
            "drift_label": DRIFT_LABELS.get(self.drift_type, self.drift_type),
            "severity": self.severity,
            "message": self.message,
            "cashbook_entry_id": str(self.cashbook_entry_id) if self.cashbook_entry_id else None,
            "financial_event_id": str(self.financial_event_id) if self.financial_event_id else None,
            "source_type": self.source_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "cashbook_amount": self.cashbook_amount,
            "lineage_amount": self.lineage_amount,
            "cashbook_date": self.cashbook_date,
            "lineage_date": self.lineage_date,
            "detail": self.detail or {},
            "attribution": self.attribution or {},
            "legitimacy": self.legitimacy or {},
        }


def _decimal(v) -> Decimal:
    return Decimal(str(v or 0))


def _parse_op_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _cashbook_direction_ok(cb_type: str, event: FinancialEvent) -> bool:
    if cb_type == "inflow":
        return event.economic_direction in ("inflow", "reduction")
    if cb_type == "outflow":
        return event.economic_direction in ("outflow", "accrual")
    return False


def _find_events_for_source(
    events_by_source: Dict[Tuple[str, UUID], List[FinancialEvent]],
    entity_type: str,
    source_id: UUID,
) -> List[FinancialEvent]:
    return events_by_source.get((entity_type, source_id), [])


def _pick_best_event(
    candidates: List[FinancialEvent],
    expected_types: Tuple[str, ...],
) -> Optional[FinancialEvent]:
    if not candidates:
        return None
    for et in expected_types:
        for ev in candidates:
            if ev.event_type == et and not ev.reversal_of_event_id:
                return ev
    for ev in candidates:
        if ev.event_type in LINEAGE_CASH_EVENT_TYPES and not ev.reversal_of_event_id:
            return ev
    return candidates[0]


def _legacy_cashbook_summary(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    start_date: date,
    end_date: date,
) -> Dict[str, Any]:
    base_filters = [
        CashbookEntry.company_id == company_id,
        CashbookEntry.branch_id == branch_id,
        CashbookEntry.date >= start_date,
        CashbookEntry.date <= end_date,
    ]
    total_inflow = (
        db.query(
            func.coalesce(
                func.sum(case((CashbookEntry.type == "inflow", CashbookEntry.amount), else_=Decimal("0"))),
                Decimal("0"),
            )
        )
        .filter(*base_filters)
        .scalar()
        or Decimal("0")
    )
    total_outflow = (
        db.query(
            func.coalesce(
                func.sum(case((CashbookEntry.type == "outflow", CashbookEntry.amount), else_=Decimal("0"))),
                Decimal("0"),
            )
        )
        .filter(*base_filters)
        .scalar()
        or Decimal("0")
    )
    entry_count = db.query(func.count(CashbookEntry.id)).filter(*base_filters).scalar() or 0
    return {
        "total_inflow": str(total_inflow),
        "total_outflow": str(total_outflow),
        "net_movement": str(total_inflow - total_outflow),
        "entry_count": int(entry_count),
        "source": "legacy_cashbook",
        "authoritative": False,
        "compatibility_layer": True,
        "observational_reference_only": True,
    }


def _load_unresolved_failures(
    db: Session,
    company_id: UUID,
    source_keys: Set[Tuple[str, UUID]],
) -> Set[Tuple[str, UUID]]:
    if not source_keys:
        return set()
    entity_types = {k[0] for k in source_keys}
    rows = (
        db.query(FinancialEventEmissionFailure)
        .filter(
            FinancialEventEmissionFailure.company_id == company_id,
            FinancialEventEmissionFailure.resolved_at.is_(None),
            FinancialEventEmissionFailure.source_entity_type.in_(list(entity_types)),
        )
        .all()
    )
    out: Set[Tuple[str, UUID]] = set()
    for r in rows:
        key = (r.source_entity_type, r.source_entity_id)
        if key in source_keys:
            out.add(key)
    return out


def _governance_timestamps(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    company_first = (
        db.query(func.min(FinancialEvent.emitted_at))
        .filter(FinancialEvent.company_id == company_id)
        .scalar()
    )
    branch_first = (
        db.query(func.min(FinancialEvent.emitted_at))
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.branch_id == branch_id,
        )
        .scalar()
    )
    return company_first, branch_first


def classify_cashbook_lineage_pair(
    entry: CashbookEntry,
    event: Optional[FinancialEvent],
    *,
    attribution: Dict[str, Any],
    governance_start: Optional[date],
    has_unresolved_failure: bool,
    period_until: date,
) -> DriftItem:
    entity = CASHBOOK_SOURCE_TO_ENTITY.get(entry.source_type, entry.source_type)
    expected_types = ENTITY_EXPECTED_EVENT_TYPES.get(entity, ())
    expectation = get_expectation_for_cashbook_source(entry.source_type)
    op_date = _parse_op_date(attribution.get("operational_date"))

    if event is None:
        verdict = classify_missing_lineage(
            expectation=expectation,
            cashbook_date=entry.date,
            cashbook_created_at=getattr(entry, "created_at", None),
            governance_start=governance_start,
            has_unresolved_failure=has_unresolved_failure,
            operational_record_exists=bool(attribution.get("record_exists")),
            operational_date=op_date,
            period_until=period_until,
        )
        return DriftItem(
            drift_type="missing_event_emission",
            severity=verdict.severity,
            message=verdict.explanation,
            cashbook_entry_id=entry.id,
            source_type=entry.source_type,
            source_id=entry.source_id,
            cashbook_amount=str(entry.amount),
            cashbook_date=str(entry.date),
            detail={
                "expected_entity_type": entity,
                "expected_event_types": list(expected_types),
                "recommended_action": verdict.recommended_action,
            },
            attribution=attribution,
            legitimacy=verdict.to_dict(),
        )

    if event.replay_source_failure_id or (event.emission_channel or "") == "replay":
        leg = {
            "category": "replay_pending",
            "category_label": LEGITIMACY_LABELS["replay_pending"],
            "severity": "warning",
            "lineage_expected": True,
            "is_active_bypass": False,
            "is_historical": False,
            "replay_eligible": True,
            "recommended_action": "Confirm replay outcome in Replay & Integrity.",
            "explanation": "Lineage exists via replay channel.",
        }
        return DriftItem(
            drift_type="replay_inconsistency",
            severity="warning",
            message="Lineage event was produced via replay; verify against operational source.",
            cashbook_entry_id=entry.id,
            financial_event_id=event.id,
            source_type=entry.source_type,
            source_id=entry.source_id,
            cashbook_amount=str(entry.amount),
            lineage_amount=str(event.amount),
            cashbook_date=str(entry.date),
            lineage_date=str(event.occurred_at.date()) if event.occurred_at else None,
            attribution=attribution,
            legitimacy=leg,
        )

    cb_amt = _decimal(entry.amount)
    ev_amt = _decimal(event.amount)
    ev_date = event.occurred_at.date() if event.occurred_at else None

    if abs(cb_amt - ev_amt) > AMOUNT_TOLERANCE:
        leg = {
            "category": "semantic_mismatch",
            "category_label": LEGITIMACY_LABELS["semantic_mismatch"],
            "severity": "error",
            "lineage_expected": True,
            "is_active_bypass": False,
            "is_historical": False,
            "replay_eligible": False,
            "recommended_action": "Investigate amount semantics between cashbook and lineage.",
            "explanation": "Governed lineage exists but amounts diverge.",
        }
        return DriftItem(
            drift_type="amount_mismatch",
            severity="error",
            message="Cashbook amount does not match lineage event amount.",
            cashbook_entry_id=entry.id,
            financial_event_id=event.id,
            source_type=entry.source_type,
            source_id=entry.source_id,
            cashbook_amount=str(cb_amt),
            lineage_amount=str(ev_amt),
            cashbook_date=str(entry.date),
            lineage_date=str(ev_date) if ev_date else None,
            attribution=attribution,
            legitimacy=leg,
        )

    if not _cashbook_direction_ok(entry.type, event):
        leg = {
            "category": "semantic_mismatch",
            "category_label": LEGITIMACY_LABELS["semantic_mismatch"],
            "severity": "error",
            "lineage_expected": True,
            "is_active_bypass": False,
            "is_historical": False,
            "replay_eligible": False,
            "recommended_action": "Review economic direction vs cashbook inflow/outflow mapping.",
            "explanation": "Classification semantics differ between compatibility cashbook and lineage.",
        }
        return DriftItem(
            drift_type="classification_mismatch",
            severity="error",
            message="Cashbook movement direction does not match lineage economic direction.",
            cashbook_entry_id=entry.id,
            financial_event_id=event.id,
            source_type=entry.source_type,
            source_id=entry.source_id,
            detail={"cashbook_type": entry.type, "economic_direction": event.economic_direction},
            attribution=attribution,
            legitimacy=leg,
        )

    if ev_date and entry.date != ev_date:
        if event.event_type == "cash_received":
            return DriftItem(
                drift_type="settlement_timing_variance",
                severity="warning",
                message="Customer payment date differs from lineage occurred_at (settlement timing).",
                cashbook_entry_id=entry.id,
                financial_event_id=event.id,
                source_type=entry.source_type,
                source_id=entry.source_id,
                cashbook_amount=str(cb_amt),
                lineage_amount=str(ev_amt),
                cashbook_date=str(entry.date),
                lineage_date=str(ev_date),
                attribution=attribution,
                legitimacy={
                    "category": "semantic_mismatch",
                    "category_label": "Settlement timing variance",
                    "severity": "warning",
                    "lineage_expected": True,
                    "is_active_bypass": False,
                    "is_historical": False,
                    "replay_eligible": False,
                    "recommended_action": "Acceptable if settlement semantics differ; document if material.",
                    "explanation": "Timing variance between operational cashbook date and lineage occurred_at.",
                },
            )
        return DriftItem(
            drift_type="timing_drift",
            severity="warning",
            message="Amounts match but operational date differs from lineage occurred_at date.",
            cashbook_entry_id=entry.id,
            financial_event_id=event.id,
            source_type=entry.source_type,
            source_id=entry.source_id,
            cashbook_amount=str(cb_amt),
            lineage_amount=str(ev_amt),
            cashbook_date=str(entry.date),
            lineage_date=str(ev_date),
            attribution=attribution,
            legitimacy={
                "category": "semantic_mismatch",
                "category_label": LEGITIMACY_LABELS["semantic_mismatch"],
                "severity": "warning",
                "lineage_expected": True,
                "is_active_bypass": False,
                "is_historical": False,
                "replay_eligible": False,
                "recommended_action": "Review date basis (operational date vs occurred_at).",
                "explanation": "Timing drift only — amounts align.",
            },
        )

    return DriftItem(
        drift_type="matched",
        severity="info",
        message="Cashbook entry aligns with lineage event.",
        cashbook_entry_id=entry.id,
        financial_event_id=event.id,
        source_type=entry.source_type,
        source_id=entry.source_id,
        cashbook_amount=str(cb_amt),
        lineage_amount=str(ev_amt),
        cashbook_date=str(entry.date),
        lineage_date=str(ev_date) if ev_date else None,
        attribution=attribution,
        legitimacy={
            "category": "matched_governed",
            "category_label": LEGITIMACY_LABELS["matched_governed"],
            "severity": "info",
            "lineage_expected": True,
            "is_active_bypass": False,
            "is_historical": False,
            "replay_eligible": False,
            "recommended_action": "No action.",
            "explanation": "Governed lineage matches compatibility cashbook for this movement.",
        },
    )


def _rollup_legitimacy(drift_items: List[DriftItem]) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for d in drift_items:
        leg = d.legitimacy or {}
        cat = leg.get("category")
        if cat:
            summary[cat] = summary.get(cat, 0) + 1
    return summary


def _sort_drift_items(items: List[DriftItem]) -> List[DriftItem]:
    return sorted(
        items,
        key=lambda d: (
            SEVERITY_ORDER.get(d.severity, 9),
            0 if d.legitimacy and d.legitimacy.get("is_active_bypass") else 1,
            d.drift_type,
        ),
    )


def reconcile_treasury_movement(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    since: date,
    until: date,
) -> Dict[str, Any]:
    legacy = _legacy_cashbook_summary(
        db, company_id=company_id, branch_id=branch_id, start_date=since, end_date=until
    )

    projection_raw = execute_projection(
        db,
        projection_id="branch_cash_movement",
        company_id=company_id,
        branch_id=branch_id,
        since=since,
        until=until,
    )
    projection = {
        "total_inflow": projection_raw.get("period_inflow", "0"),
        "total_outflow": projection_raw.get("period_outflow", "0"),
        "net_movement": projection_raw.get("period_net_movement", "0"),
        "event_count": projection_raw.get("event_count", 0),
        "source": "branch_cash_movement",
        "derived": True,
        "authoritative": False,
        "observational_reference_only": False,
        "freshness": projection_raw.get("freshness"),
        "contract": projection_raw.get("contract"),
        "disclaimer": projection_raw.get("disclaimer"),
    }

    company_first, branch_first = _governance_timestamps(db, company_id, branch_id)
    gov_ctx = resolve_governance_context(
        company_first_emitted_at=company_first,
        branch_first_emitted_at=branch_first,
        period_until=until,
    )
    governance_start = None
    if gov_ctx.get("governance_start_date"):
        governance_start = date.fromisoformat(gov_ctx["governance_start_date"])

    since_dt = datetime.combine(since, datetime.min.time())
    until_dt = datetime.combine(until, datetime.max.time())

    cashbook_rows = (
        db.query(CashbookEntry)
        .filter(
            CashbookEntry.company_id == company_id,
            CashbookEntry.branch_id == branch_id,
            CashbookEntry.date >= since,
            CashbookEntry.date <= until,
        )
        .order_by(CashbookEntry.date.asc())
        .all()
    )

    lineage_rows = (
        db.query(FinancialEvent)
        .filter(
            FinancialEvent.company_id == company_id,
            FinancialEvent.branch_id == branch_id,
            FinancialEvent.occurred_at >= since_dt,
            FinancialEvent.occurred_at <= until_dt,
            FinancialEvent.event_type.in_(tuple(LINEAGE_CASH_EVENT_TYPES)),
        )
        .all()
    )

    attribution_cache = batch_resolve_attributions(db, company_id=company_id, entries=cashbook_rows)

    source_keys = {
        (CASHBOOK_SOURCE_TO_ENTITY.get(e.source_type, e.source_type), e.source_id)
        for e in cashbook_rows
    }
    failure_keys = _load_unresolved_failures(db, company_id, source_keys)

    events_by_source: Dict[Tuple[str, UUID], List[FinancialEvent]] = {}
    for ev in lineage_rows:
        key = (ev.source_entity_type, ev.source_entity_id)
        events_by_source.setdefault(key, []).append(ev)

    matched_sources: set[Tuple[str, UUID]] = set()
    drift_items: List[DriftItem] = []

    for entry in cashbook_rows:
        entity = CASHBOOK_SOURCE_TO_ENTITY.get(entry.source_type, entry.source_type)
        attr = attribution_for_entry(entry, attribution_cache)
        candidates = _find_events_for_source(events_by_source, entity, entry.source_id)
        expected = ENTITY_EXPECTED_EVENT_TYPES.get(entity, ())
        event = _pick_best_event(candidates, expected)
        if event:
            matched_sources.add((entity, entry.source_id))
        item = classify_cashbook_lineage_pair(
            entry,
            event,
            attribution=attr,
            governance_start=governance_start,
            has_unresolved_failure=(entity, entry.source_id) in failure_keys,
            period_until=until,
        )
        if item.drift_type != "matched":
            drift_items.append(item)

    entity_to_cashbook_source = {v: k for k, v in CASHBOOK_SOURCE_TO_ENTITY.items()}
    cashbook_keys = {(e.source_type, e.source_id) for e in cashbook_rows}

    for ev in lineage_rows:
        if ev.reversal_of_event_id:
            continue
        key = (ev.source_entity_type, ev.source_entity_id)
        if key in matched_sources:
            continue
        cb_source = entity_to_cashbook_source.get(ev.source_entity_type)
        if not cb_source:
            continue
        if (cb_source, ev.source_entity_id) in cashbook_keys:
            continue
        drift_items.append(
            DriftItem(
                drift_type="orphan_lineage_record",
                severity="info",
                message="Lineage cash movement exists without a legacy cashbook entry (lineage may be ahead of compatibility layer).",
                financial_event_id=ev.id,
                source_type=cb_source,
                source_id=ev.source_entity_id,
                lineage_amount=str(ev.amount),
                lineage_date=str(ev.occurred_at.date()) if ev.occurred_at else None,
                detail={"event_type": ev.event_type},
                attribution={
                    "operational_module": "Lineage",
                    "workflow_label": ev.event_type.replace("_", " ").title(),
                    "document_reference": ev.source_reference,
                    "lineage_expected": True,
                },
                legitimacy={
                    "category": "lineage_ahead_of_cashbook",
                    "category_label": LEGITIMACY_LABELS["lineage_ahead_of_cashbook"],
                    "severity": "info",
                    "lineage_expected": True,
                    "is_active_bypass": False,
                    "is_historical": False,
                    "replay_eligible": False,
                    "recommended_action": "Optional: verify cashbook backfill for this source.",
                    "explanation": "Governed event exists; compatibility cashbook not required for authority.",
                },
            )
        )

    li = _decimal(legacy["total_inflow"])
    lo = _decimal(legacy["total_outflow"])
    pi = _decimal(projection["total_inflow"])
    po = _decimal(projection["total_outflow"])

    totals_delta = {
        "inflow_delta": str(li - pi),
        "outflow_delta": str(lo - po),
        "net_delta": str((li - lo) - (pi - po)),
    }
    totals_aligned = abs(li - pi) <= AMOUNT_TOLERANCE and abs(lo - po) <= AMOUNT_TOLERANCE

    legitimacy_summary = _rollup_legitimacy(drift_items)
    unmaterialized = legitimacy_summary.get("historical_legacy_record", 0) + legitimacy_summary.get(
        "backfill_eligible", 0
    )

    if not totals_aligned:
        totals_severity = "warning"
        totals_message = (
            "Legacy cashbook period totals differ from lineage projection — expected when most "
            "movements are not yet lineage-materialized."
        )
        if legitimacy_summary.get("active_operational_bypass", 0) > 0:
            totals_severity = "error"
            totals_message = (
                "Totals differ and active operational bypasses exist — prioritize hook/backfill remediation."
            )
        elif unmaterialized >= max(1, int(len(cashbook_rows) * 0.5)):
            totals_severity = "info"

        drift_items.append(
            DriftItem(
                drift_type="totals_mismatch",
                severity=totals_severity,
                message=totals_message,
                detail={
                    "legacy_inflow": legacy["total_inflow"],
                    "projection_inflow": projection["total_inflow"],
                    "legacy_outflow": legacy["total_outflow"],
                    "projection_outflow": projection["total_outflow"],
                    "ungoverned_cashbook_rows": unmaterialized,
                    **totals_delta,
                },
                legitimacy={
                    "category": "semantic_mismatch",
                    "category_label": "Period coverage gap",
                    "severity": totals_severity,
                    "lineage_expected": False,
                    "is_active_bypass": False,
                    "is_historical": unmaterialized > 0,
                    "replay_eligible": True,
                    "recommended_action": "Run controlled backfill for the period; do not treat cashbook as authoritative.",
                    "explanation": period_interpretation(
                        cashbook_count=len(cashbook_rows),
                        lineage_count=len(lineage_rows),
                        legitimacy_summary=legitimacy_summary,
                        totals_aligned=False,
                    ),
                },
            )
        )

    by_type: Dict[str, int] = {}
    for d in drift_items:
        by_type[d.drift_type] = by_type.get(d.drift_type, 0) + 1

    cashbook_drift_ids = {d.cashbook_entry_id for d in drift_items if d.cashbook_entry_id}
    matched_count = len(cashbook_rows) - len(cashbook_drift_ids)

    sorted_items = _sort_drift_items(drift_items)
    display_limit = 300

    coverage_ratio = (
        round(len(lineage_rows) / len(cashbook_rows), 4) if cashbook_rows else None
    )

    return {
        "phase": "2A.5_treasury_coverage_intelligence",
        "branch_id": str(branch_id),
        "since": str(since),
        "until": str(until),
        "governance": gov_ctx,
        "coverage_matrix": introspect_lineage_coverage_matrix(),
        "legacy_cashbook": legacy,
        "lineage_projection": projection,
        "comparison": {
            "totals_aligned": totals_aligned,
            "totals_delta": totals_delta,
            "matched_entry_count": max(0, matched_count),
            "cashbook_entry_count": len(cashbook_rows),
            "lineage_event_count": len(lineage_rows),
            "lineage_coverage_ratio": coverage_ratio,
            "drift_count": len(drift_items),
            "drift_by_type": by_type,
            "legitimacy_summary": legitimacy_summary,
            "active_bypass_count": legitimacy_summary.get("active_operational_bypass", 0),
            "backfill_eligible_count": legitimacy_summary.get("backfill_eligible", 0),
            "historical_legacy_count": legitimacy_summary.get("historical_legacy_record", 0),
            "period_interpretation": period_interpretation(
                cashbook_count=len(cashbook_rows),
                lineage_count=len(lineage_rows),
                legitimacy_summary=legitimacy_summary,
                totals_aligned=totals_aligned,
            ),
            "drift_display_limit": display_limit,
            "drift_truncated": len(sorted_items) > display_limit,
        },
        "drift_items": [d.to_dict() for d in sorted_items[:display_limit]],
        "policy": {
            "projection_first_reporting": True,
            "legacy_authoritative": False,
            "legacy_observational_reference_only": True,
            "reconciliation_is_validation_not_fallback": True,
            "explainable_drift_acceptable_during_migration": True,
            "active_bypass_is_critical_risk": True,
        },
    }
