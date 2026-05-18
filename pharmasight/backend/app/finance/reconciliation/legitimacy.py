"""
Drift legitimacy classification (Stage 2A.5) — explain missing lineage, never fake convergence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from app.finance.reconciliation.lineage_coverage import WorkflowLineageExpectation

LEGITIMACY_LABELS: Dict[str, str] = {
    "historical_legacy_record": "Historical legacy record",
    "backfill_eligible": "Backfill eligible",
    "active_operational_bypass": "Active operational bypass",
    "replay_pending": "Replay pending",
    "unsupported_workflow": "Unsupported workflow",
    "manual_adjustment": "Manual adjustment (review)",
    "semantic_mismatch": "Semantic mismatch",
    "matched_governed": "Governed match",
    "lineage_ahead_of_cashbook": "Lineage ahead of cashbook",
}


@dataclass(frozen=True)
class LegitimacyVerdict:
    category: str
    severity: str
    lineage_expected: bool
    is_active_bypass: bool
    is_historical: bool
    replay_eligible: bool
    recommended_action: str
    explanation: str

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "category_label": LEGITIMACY_LABELS.get(self.category, self.category),
            "severity": self.severity,
            "lineage_expected": self.lineage_expected,
            "is_active_bypass": self.is_active_bypass,
            "is_historical": self.is_historical,
            "replay_eligible": self.replay_eligible,
            "recommended_action": self.recommended_action,
            "explanation": self.explanation,
        }


def resolve_governance_context(
    *,
    company_first_emitted_at: Optional[datetime],
    branch_first_emitted_at: Optional[datetime],
    period_until: date,
) -> Dict[str, Any]:
    """When lineage governance effectively started for interpretation."""
    branch_start = branch_first_emitted_at.date() if branch_first_emitted_at else None
    company_start = company_first_emitted_at.date() if company_first_emitted_at else None
    governance_start = branch_start or company_start
    return {
        "governance_start_date": str(governance_start) if governance_start else None,
        "branch_first_event_at": str(branch_first_emitted_at) if branch_first_emitted_at else None,
        "company_first_event_at": str(company_first_emitted_at) if company_first_emitted_at else None,
        "kernel_phases": ["E3", "E5"],
        "notes": "Governance start inferred from first emitted financial_event; pre-start cashbook is transitional.",
    }


def classify_missing_lineage(
    *,
    expectation: Optional[WorkflowLineageExpectation],
    cashbook_date: date,
    cashbook_created_at: Optional[datetime],
    governance_start: Optional[date],
    has_unresolved_failure: bool,
    operational_record_exists: bool,
    operational_date: Optional[date],
    period_until: date,
) -> LegitimacyVerdict:
    if not expectation:
        return LegitimacyVerdict(
            category="unsupported_workflow",
            severity="warning",
            lineage_expected=False,
            is_active_bypass=False,
            is_historical=True,
            replay_eligible=False,
            recommended_action="Map workflow in lineage coverage matrix or exclude from treasury reconciliation.",
            explanation="Cashbook source type has no governed lineage expectation defined.",
        )

    if has_unresolved_failure:
        return LegitimacyVerdict(
            category="replay_pending",
            severity="warning",
            lineage_expected=expectation.lineage_mandatory,
            is_active_bypass=False,
            is_historical=False,
            replay_eligible=True,
            recommended_action="Open Replay & Integrity and replay emission failures for this source.",
            explanation="Emission failed previously; lineage may be materialized via replay.",
        )

    op_date = operational_date or cashbook_date
    recent_cutoff = period_until - timedelta(days=14)

    # Pre-governance: no events on branch yet, or operational/cashbook date before first emission
    if governance_start is None:
        return LegitimacyVerdict(
            category="historical_legacy_record",
            severity="info",
            lineage_expected=expectation.lineage_mandatory,
            is_active_bypass=False,
            is_historical=True,
            replay_eligible=expectation.replay_backfill_supported,
            recommended_action="Run controlled finance backfill for the period when ready to materialize lineage.",
            explanation="No financial events have been emitted for this branch yet; cashbook reflects pre-governance operational history.",
        )

    if cashbook_date < governance_start or (op_date and op_date < governance_start):
        return LegitimacyVerdict(
            category="historical_legacy_record",
            severity="info",
            lineage_expected=expectation.lineage_mandatory,
            is_active_bypass=False,
            is_historical=True,
            replay_eligible=expectation.replay_backfill_supported,
            recommended_action="Use Finance backfill to reconstruct lineage without changing operational records.",
            explanation="Record predates governed lineage emissions on this branch; drift is expected during migration.",
        )

    if not operational_record_exists:
        return LegitimacyVerdict(
            category="manual_adjustment",
            severity="warning",
            lineage_expected=expectation.lineage_mandatory,
            is_active_bypass=False,
            is_historical=True,
            replay_eligible=False,
            recommended_action="Investigate cashbook source linkage; operational document may have been removed.",
            explanation="Cashbook entry references a missing operational record.",
        )

    if expectation.replay_backfill_supported and op_date and op_date >= governance_start:
        # Post-governance but not materialized — backfill path, NOT legacy truth
        severity = "info"
        category = "backfill_eligible"
        action = "Run controlled backfill (Finance Operations) for this period and workflow."
        explanation = (
            "Operational record exists under governed workflow but lineage was not materialized; "
            "projection reflects emissions only — not cashbook compatibility totals."
        )
        if op_date >= recent_cutoff and expectation.hook_active:
            category = "active_operational_bypass"
            severity = "error"
            action = "Verify financial event hooks on this workflow; replay or backfill immediately."
            explanation = (
                "Recent operational activity without lineage emission — active bypass risk; "
                "legacy cashbook must not be treated as authoritative."
            )
        return LegitimacyVerdict(
            category=category,
            severity=severity,
            lineage_expected=True,
            is_active_bypass=(category == "active_operational_bypass"),
            is_historical=False,
            replay_eligible=True,
            recommended_action=action,
            explanation=explanation,
        )

    return LegitimacyVerdict(
        category="unsupported_workflow",
        severity="warning",
        lineage_expected=expectation.lineage_mandatory,
        is_active_bypass=False,
        is_historical=False,
        replay_eligible=False,
        recommended_action="Review workflow configuration.",
        explanation="Lineage expected but backfill not supported for this pathway.",
    )


def period_interpretation(
    *,
    cashbook_count: int,
    lineage_count: int,
    legitimacy_summary: Dict[str, int],
    totals_aligned: bool,
) -> str:
    if cashbook_count == 0 and lineage_count == 0:
        return "No cash movement in this period."

    hist = legitimacy_summary.get("historical_legacy_record", 0)
    backfill = legitimacy_summary.get("backfill_eligible", 0)
    bypass = legitimacy_summary.get("active_operational_bypass", 0)
    replay = legitimacy_summary.get("replay_pending", 0)

    parts = []
    if not totals_aligned:
        parts.append(
            "Period totals differ because legacy cashbook aggregates pre-governance and backfill-eligible "
            "movements, while the lineage projection includes only materialized financial events."
        )
    if hist + backfill >= max(1, int(cashbook_count * 0.5)):
        parts.append(
            f"Most cashbook rows ({hist + backfill} of {cashbook_count}) are not yet lineage-materialized — "
            "this is visibility into governed vs ungoverned pathways, not proof that projections are wrong."
        )
    if bypass:
        parts.append(f"{bypass} recent record(s) flagged as active operational bypass — prioritize remediation.")
    if replay:
        parts.append(f"{replay} item(s) awaiting replay from emission failures.")
    if totals_aligned and cashbook_count > 0:
        parts.append("Period totals align; entry-level drift may still exist (timing, classification).")

    return " ".join(parts) if parts else "Review drift items for workflow-specific actions."
