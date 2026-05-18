"""
Branch Financial Confidence Index — gates progressive operational authority.

Scores are derived from governance signals; projections remain non-authoritative until
branch maturity reaches projection-trusted (explicit doctrine, not automatic).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.finance.reconciliation.treasury_movement import reconcile_treasury_movement
from app.models.financial_event import FinancialEventEmissionFailure


AUTHORITY_LEVELS = (
    "reconciliation_only",
    "shadow",
    "projection_assisted",
    "projection_trusted",
)

AUTHORITY_LEVEL_LABELS = {
    "reconciliation_only": "Reconciliation only",
    "shadow": "Shadow governance",
    "projection_assisted": "Projection assisted",
    "projection_trusted": "Projection trusted",
}

AUTHORITY_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "reconciliation_only": {
        "legacy_cashbook_primary": True,
        "projection_operational_reports": False,
        "projection_decision_guidance": False,
        "intelligence_surfaces_primary": False,
    },
    "shadow": {
        "legacy_cashbook_primary": True,
        "projection_operational_reports": False,
        "projection_decision_guidance": True,
        "intelligence_surfaces_primary": True,
    },
    "projection_assisted": {
        "legacy_cashbook_primary": False,
        "projection_operational_reports": True,
        "projection_decision_guidance": True,
        "intelligence_surfaces_primary": True,
    },
    "projection_trusted": {
        "legacy_cashbook_primary": False,
        "projection_operational_reports": True,
        "projection_decision_guidance": True,
        "intelligence_surfaces_primary": True,
    },
}


@dataclass(frozen=True)
class ConfidenceSignal:
    signal_id: str
    label: str
    score: float
    max_score: float
    value: Any
    explanation: str


def _level_from_score(score: float) -> str:
    if score >= 85:
        return "projection_trusted"
    if score >= 65:
        return "projection_assisted"
    if score >= 40:
        return "shadow"
    return "reconciliation_only"


def _replay_backlog_count(db: Session, *, company_id: UUID, branch_id: UUID) -> int:
    return (
        db.query(func.count(FinancialEventEmissionFailure.id))
        .filter(
            FinancialEventEmissionFailure.company_id == company_id,
            FinancialEventEmissionFailure.branch_id == branch_id,
            FinancialEventEmissionFailure.resolved_at.is_(None),
        )
        .scalar()
        or 0
    )


def assess_branch_financial_confidence(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    since: date,
    until: date,
) -> Dict[str, Any]:
    recon = reconcile_treasury_movement(
        db, company_id=company_id, branch_id=branch_id, since=since, until=until
    )
    comparison = recon.get("comparison") or {}
    legitimacy = recon.get("legitimacy_summary") or {}
    cashbook_count = int(comparison.get("cashbook_entry_count") or 0)
    lineage_count = int(comparison.get("lineage_event_count") or 0)
    matched = int(comparison.get("matched_entry_count") or 0)
    totals_aligned = bool(comparison.get("totals_aligned"))
    coverage_ratio = comparison.get("coverage_ratio")
    if coverage_ratio is None and cashbook_count:
        coverage_ratio = round(lineage_count / cashbook_count, 4)

    drift_count = int(comparison.get("drift_count") or 0)
    replay_backlog = _replay_backlog_count(db, company_id=company_id, branch_id=branch_id)
    active_bypass = int(legitimacy.get("active_operational_bypass") or 0)
    historical = int(legitimacy.get("historical_legacy_record") or 0)
    backfill_eligible = int(legitimacy.get("backfill_eligible") or 0)

    signals: List[ConfidenceSignal] = []

    cov = float(coverage_ratio or 0) if cashbook_count else (1.0 if lineage_count else 0.0)
    cov_score = min(30.0, cov * 30.0)
    signals.append(
        ConfidenceSignal(
            "lineage_coverage",
            "Lineage coverage",
            cov_score,
            30.0,
            coverage_ratio,
            "Share of cashbook-period activity reflected in governed cash-movement lineage.",
        )
    )

    match_rate = (matched / cashbook_count) if cashbook_count else 1.0
    match_score = min(20.0, match_rate * 20.0)
    drift_by_type = comparison.get("drift_by_type") or {}
    signals.append(
        ConfidenceSignal(
            "cashbook_match_rate",
            "Treasury match rate",
            match_score,
            20.0,
            {
                "rate": round(match_rate, 4),
                "matched_rows": matched,
                "cashbook_rows": cashbook_count,
                "pct": round(match_rate * 100, 1) if cashbook_count else None,
            },
            "Strict pairwise match: each legacy cashbook row must align to a governed lineage event "
            "(same source, amount, direction, and date). Timing or amount differences count as drift, "
            "even when lineage events exist for the period.",
        )
    )

    replay_penalty = min(20.0, replay_backlog * 4.0)
    replay_score = max(0.0, 20.0 - replay_penalty)
    signals.append(
        ConfidenceSignal(
            "replay_stability",
            "Replay stability",
            replay_score,
            20.0,
            replay_backlog,
            "Unresolved emission failures reduce trust; replay restores determinism.",
        )
    )

    drift_rate = (drift_count / cashbook_count) if cashbook_count else 0.0
    drift_penalty = min(15.0, drift_rate * 15.0)
    drift_score = max(0.0, 15.0 - drift_penalty)
    signals.append(
        ConfidenceSignal(
            "drift_frequency",
            "Drift frequency",
            drift_score,
            15.0,
            round(drift_rate, 4),
            "Reconciliation drift items relative to cashbook rows in period.",
        )
    )

    bypass_penalty = min(10.0, active_bypass * 5.0)
    bypass_score = max(0.0, 10.0 - bypass_penalty)
    signals.append(
        ConfidenceSignal(
            "operational_bypasses",
            "Active bypasses",
            bypass_score,
            10.0,
            active_bypass,
            "Active operational bypasses indicate live workflows skipping lineage.",
        )
    )

    totals_score = 5.0 if totals_aligned else 0.0
    signals.append(
        ConfidenceSignal(
            "treasury_totals_alignment",
            "Treasury totals alignment",
            totals_score,
            5.0,
            totals_aligned,
            "Legacy cashbook period totals align with lineage cash-movement projection.",
        )
    )

    total_score = round(sum(s.score for s in signals), 1)
    authority_level = _level_from_score(total_score)

    return {
        "phase": "operational_intelligence_confidence",
        "branch_id": str(branch_id),
        "since": str(since),
        "until": str(until),
        "confidence_score": total_score,
        "authority_level": authority_level,
        "authority_level_label": AUTHORITY_LEVEL_LABELS[authority_level],
        "authority_capabilities": AUTHORITY_CAPABILITIES[authority_level],
        "doctrine": {
            "projections_remain_non_authoritative": True,
            "progressive_authority": True,
            "cashbook_compatibility_until_trusted": authority_level
            not in ("projection_assisted", "projection_trusted"),
            "explainability_required": True,
        },
        "signals": [
            {
                "signal_id": s.signal_id,
                "label": s.label,
                "score": s.score,
                "max_score": s.max_score,
                "value": s.value,
                "explanation": s.explanation,
            }
            for s in signals
        ],
        "governance_snapshot": {
            "cashbook_entry_count": cashbook_count,
            "lineage_event_count": lineage_count,
            "matched_entry_count": matched,
            "drift_item_count": drift_count,
            "replay_backlog": replay_backlog,
            "legitimacy_summary": legitimacy,
            "historical_legacy_count": historical,
            "backfill_eligible_count": backfill_eligible,
            "totals_aligned": totals_aligned,
            "drift_by_type": drift_by_type,
        },
        "traceability": {
            "treasury_reconciliation": "GET /api/finance/reconciliation/treasury-movement",
            "replay_failures": "GET /api/finance/events/failures",
        },
    }


def default_confidence_period(*, until: Optional[date] = None) -> tuple[date, date]:
    end = until or date.today()
    start = end.replace(day=1)
    if start > end:
        start = end - timedelta(days=30)
    return start, end
