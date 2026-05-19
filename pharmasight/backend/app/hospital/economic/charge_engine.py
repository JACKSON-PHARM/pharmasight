"""
Care charge engine — immutable accrued care value (H1).

Accrual follows clinical completion triggers; does not create AR or mutate invoices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.hospital.economic.financial_hooks import on_care_charge_accrued
from app.hospital.economic.pfj_service import ensure_pfj_for_encounter
from app.models.clinic import Encounter, Patient
from app.models.hospital_economic import CareCharge
from app.models.sale import SalesInvoice, SalesInvoiceItem


@dataclass(frozen=True)
class AccrueChargeRequest:
    company_id: UUID
    branch_id: UUID
    pfj_id: UUID
    encounter_id: Optional[UUID]
    charge_kind: str
    clinical_trigger: str
    source_entity_type: str
    source_entity_id: UUID
    description: str
    amount_exclusive: Decimal
    vat_amount: Decimal
    amount_inclusive: Decimal
    quantity: Decimal = Decimal("1")
    unit_name: Optional[str] = None
    item_id: Optional[UUID] = None
    clinical_service_id: Optional[UUID] = None
    sales_invoice_id: Optional[UUID] = None
    sales_invoice_item_id: Optional[UUID] = None
    metadata: Optional[dict] = None


def _find_active_charge(
    db: Session, *, company_id: UUID, source_entity_type: str, source_entity_id: UUID
) -> Optional[CareCharge]:
    return (
        db.query(CareCharge)
        .filter(
            CareCharge.company_id == company_id,
            CareCharge.source_entity_type == source_entity_type,
            CareCharge.source_entity_id == source_entity_id,
            CareCharge.accrual_status == "accrued",
            CareCharge.reversed_at.is_(None),
        )
        .first()
    )


def accrue_charge(db: Session, req: AccrueChargeRequest) -> CareCharge:
    existing = _find_active_charge(
        db,
        company_id=req.company_id,
        source_entity_type=req.source_entity_type,
        source_entity_id=req.source_entity_id,
    )
    if existing:
        try:
            from app.hospital.economic.liability_engine import allocate_charge_liability

            allocate_charge_liability(db, existing.id, reason="initial")
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "hospital kernel: liability backfill for existing charge %s", existing.id
            )
        return existing

    charge = CareCharge(
        company_id=req.company_id,
        branch_id=req.branch_id,
        pfj_id=req.pfj_id,
        encounter_id=req.encounter_id,
        charge_kind=req.charge_kind,
        accrual_status="accrued",
        clinical_trigger=req.clinical_trigger,
        source_entity_type=req.source_entity_type,
        source_entity_id=req.source_entity_id,
        description=(req.description or "").strip() or req.charge_kind,
        item_id=req.item_id,
        clinical_service_id=req.clinical_service_id,
        quantity=req.quantity,
        unit_name=req.unit_name,
        amount_exclusive=req.amount_exclusive,
        vat_amount=req.vat_amount,
        amount_inclusive=req.amount_inclusive,
        sales_invoice_id=req.sales_invoice_id,
        sales_invoice_item_id=req.sales_invoice_item_id,
        metadata_json=req.metadata or {},
        accrued_at=datetime.now(timezone.utc),
    )
    db.add(charge)
    db.flush()
    on_care_charge_accrued(db, charge)
    try:
        from app.hospital.economic.liability_engine import allocate_charge_liability

        allocate_charge_liability(db, charge.id, reason="initial")
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "hospital kernel: liability allocation after accrue (non-fatal) charge_id=%s", charge.id
        )
    return charge


def bridge_consultation_from_encounter_invoice(
    db: Session,
    *,
    encounter: Encounter,
    patient: Patient,
    invoice: SalesInvoice,
) -> Optional[CareCharge]:
    """
    Mirror first consultation line on draft encounter invoice into care_charges.
    Invoice bridge only — PFJ/charge remain authoritative for hospital economics.
    """
    if not invoice.encounter_id or invoice.encounter_id != encounter.id:
        return None
    line = (
        db.query(SalesInvoiceItem)
        .filter(SalesInvoiceItem.sales_invoice_id == invoice.id)
        .order_by(SalesInvoiceItem.id.asc())
        .first()
    )
    if not line:
        return None
    pfj = ensure_pfj_for_encounter(db, encounter=encounter, patient=patient)
    source_id = line.id
    return accrue_charge(
        db,
        AccrueChargeRequest(
            company_id=encounter.company_id,
            branch_id=encounter.branch_id,
            pfj_id=pfj.id,
            encounter_id=encounter.id,
            charge_kind="consultation",
            clinical_trigger="performed",
            source_entity_type="sales_invoice_item",
            source_entity_id=source_id,
            description=line.item_name or "Consultation",
            amount_exclusive=Decimal(str(line.line_total_exclusive or 0)),
            vat_amount=Decimal(str(line.vat_amount or 0)),
            amount_inclusive=Decimal(str(line.line_total_inclusive or 0)),
            quantity=Decimal(str(line.quantity or 1)),
            unit_name=line.unit_name,
            item_id=line.item_id,
            sales_invoice_id=invoice.id,
            sales_invoice_item_id=line.id,
            metadata={"bridge": "encounter_draft_invoice"},
        ),
    )


def bridge_service_execution_charge(
    db: Session,
    *,
    encounter: Encounter,
    patient: Patient,
    execution_id: UUID,
    service_id: UUID,
    service_name: str,
    billed_amount: Decimal,
    invoice: SalesInvoice,
    invoice_line: Optional[SalesInvoiceItem] = None,
) -> CareCharge:
    pfj = ensure_pfj_for_encounter(db, encounter=encounter, patient=patient)
    exclusive = billed_amount
    if invoice_line:
        exclusive = Decimal(str(invoice_line.line_total_exclusive or billed_amount))
        vat = Decimal(str(invoice_line.vat_amount or 0))
        inclusive = Decimal(str(invoice_line.line_total_inclusive or billed_amount))
    else:
        vat = Decimal("0")
        inclusive = billed_amount
    return accrue_charge(
        db,
        AccrueChargeRequest(
            company_id=encounter.company_id,
            branch_id=encounter.branch_id,
            pfj_id=pfj.id,
            encounter_id=encounter.id,
            charge_kind="procedure",
            clinical_trigger="completed",
            source_entity_type="encounter_service_execution",
            source_entity_id=execution_id,
            description=service_name or "Clinical service",
            amount_exclusive=exclusive,
            vat_amount=vat,
            amount_inclusive=inclusive,
            clinical_service_id=service_id,
            sales_invoice_id=invoice.id,
            sales_invoice_item_id=invoice_line.id if invoice_line else None,
            metadata={"bridge": "service_execution"},
        ),
    )
