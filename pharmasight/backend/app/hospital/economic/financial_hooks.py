"""
Emit financial_events for hospital care accrual (feeds existing E3 kernel).
"""
from __future__ import annotations

import logging
from datetime import timezone
from decimal import Decimal
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.finance.events.branch_policy import resolve_policy_pack_for_branch
from app.finance.events.emitter import EmitFinancialEventRequest, EmitResult, emit_financial_event
from app.finance.events.policies import event_enabled_for_pack
from app.hospital.economic.correlation import correlation_group_for_pfj
from app.models.hospital_economic import CareCharge, LiabilityAllocationLine, LiabilityAllocationRun

logger = logging.getLogger(__name__)


def _safe_emit(db: Session, request: EmitFinancialEventRequest) -> Tuple[EmitResult, Optional[UUID]]:
    try:
        return emit_financial_event(db, request)
    except Exception:
        logger.exception(
            "hospital care_value emit failed charge_id=%s event_type=%s",
            request.source_entity_id,
            request.event_type,
        )
        return EmitResult.FAILED, None


def on_care_charge_accrued(db: Session, charge: CareCharge) -> None:
    """Non-fatal: care value accrual evidence for PFJ timeline / future recognition."""
    pack = resolve_policy_pack_for_branch(
        db, company_id=charge.company_id, branch_id=charge.branch_id, sales_type=None
    )
    if not event_enabled_for_pack(pack, "care_value_accrued"):
        return
    occurred = charge.accrued_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    amount = Decimal(str(charge.amount_inclusive or 0))
    if amount <= 0:
        return
    _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="care_value_accrued",
            company_id=charge.company_id,
            branch_id=charge.branch_id,
            source_entity_id=charge.id,
            occurred_at=occurred,
            amount=amount,
            source_reference=(charge.description or "")[:255] or None,
            correlation_group=correlation_group_for_pfj(charge.pfj_id),
            payload={
                "pfj_id": str(charge.pfj_id),
                "encounter_id": str(charge.encounter_id) if charge.encounter_id else None,
                "charge_kind": charge.charge_kind,
                "clinical_trigger": charge.clinical_trigger,
                "amount_exclusive": str(charge.amount_exclusive),
                "vat_amount": str(charge.vat_amount),
                "bridge_invoice_id": str(charge.sales_invoice_id) if charge.sales_invoice_id else None,
            },
            governance_metadata={
                "emitter": "hospital.charge_engine",
                "policy_pack": pack.pack_id,
                "accrual_layer": "care_value",
            },
        ),
    )


def on_care_charge_reversed(db: Session, charge: CareCharge, *, reversal_event_id: UUID) -> None:
    pack = resolve_policy_pack_for_branch(
        db, company_id=charge.company_id, branch_id=charge.branch_id, sales_type=None
    )
    if not event_enabled_for_pack(pack, "care_value_reversed"):
        return
    occurred = charge.reversed_at or charge.accrued_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    amount = Decimal(str(charge.amount_inclusive or 0))
    if amount <= 0:
        return
    _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="care_value_reversed",
            company_id=charge.company_id,
            branch_id=charge.branch_id,
            source_entity_id=charge.id,
            occurred_at=occurred,
            amount=amount,
            correlation_group=correlation_group_for_pfj(charge.pfj_id),
            reversal_of_event_id=reversal_event_id,
            payload={
                "pfj_id": str(charge.pfj_id),
                "reversal_of_charge_id": str(charge.reversal_of_charge_id) if charge.reversal_of_charge_id else None,
            },
            governance_metadata={"emitter": "hospital.charge_engine", "policy_pack": pack.pack_id},
        ),
    )


def on_liability_allocated(db: Session, run: LiabilityAllocationRun, *, charge: CareCharge) -> None:
    """Liability split evidence — not receivable recognition (H4)."""
    pack = resolve_policy_pack_for_branch(
        db, company_id=charge.company_id, branch_id=charge.branch_id, sales_type=None
    )
    if not event_enabled_for_pack(pack, "liability_allocated"):
        return
    occurred = run.created_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    amount = Decimal(str(run.gross_amount_inclusive or 0))
    if amount <= 0:
        return
    splits = []
    for line in run.lines:
        splits.append(
            {
                "obligor": line.obligor_type,
                "amount": str(line.amount_inclusive),
                "line_kind": line.line_kind,
            }
        )
    _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type="liability_allocated",
            company_id=charge.company_id,
            branch_id=charge.branch_id,
            source_entity_id=run.id,
            occurred_at=occurred,
            amount=amount,
            source_reference=f"charge:{charge.id}:v{run.version}",
            correlation_group=correlation_group_for_pfj(charge.pfj_id),
            payload={
                "pfj_id": str(charge.pfj_id),
                "care_charge_id": str(charge.id),
                "allocation_version": run.version,
                "allocation_reason": run.allocation_reason,
                "splits": splits,
            },
            governance_metadata={
                "emitter": "hospital.liability_engine",
                "policy_pack": pack.pack_id,
                "accrual_layer": "liability",
            },
        ),
    )


def on_obligor_receivable_recognized(
    db: Session,
    *,
    charge: CareCharge,
    line: LiabilityAllocationLine,
    obligor_type: str,
    amount: Decimal,
) -> Optional[UUID]:
    """H4: Recognize receivable for obligated slice (not treasury). Returns event id."""
    pack = resolve_policy_pack_for_branch(
        db, company_id=charge.company_id, branch_id=charge.branch_id, sales_type=None
    )
    if obligor_type == "patient":
        event_type = "patient_receivable_recognized"
    elif obligor_type == "insurer":
        event_type = "insurer_receivable_recognized"
    else:
        event_type = "patient_receivable_recognized"
    if not event_enabled_for_pack(pack, event_type):
        return None
    occurred = charge.accrued_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    result, event_id = _safe_emit(
        db,
        EmitFinancialEventRequest(
            event_type=event_type,
            company_id=charge.company_id,
            branch_id=charge.branch_id,
            source_entity_id=line.id,
            occurred_at=occurred,
            amount=amount,
            correlation_group=correlation_group_for_pfj(charge.pfj_id),
            payload={
                "pfj_id": str(charge.pfj_id),
                "care_charge_id": str(charge.id),
                "obligor_type": obligor_type,
                "allocation_line_id": str(line.id),
            },
            governance_metadata={
                "emitter": "hospital.recognition_engine",
                "policy_pack": pack.pack_id,
                "accrual_layer": "recognition",
            },
        ),
    )
    if result == EmitResult.CREATED:
        return event_id
    return event_id
