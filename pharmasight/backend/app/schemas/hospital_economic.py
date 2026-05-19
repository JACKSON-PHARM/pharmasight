"""Hospital Economic Kernel API schemas (H1)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PFJResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    branch_id: UUID
    patient_id: UUID
    status: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    intake_payment_mode_hint: Optional[str] = None
    intake_insurance_scheme_hint: Optional[str] = None


class CareChargeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pfj_id: UUID
    encounter_id: Optional[UUID] = None
    charge_kind: str
    accrual_status: str
    clinical_trigger: str
    description: str
    amount_exclusive: Decimal
    vat_amount: Decimal
    amount_inclusive: Decimal
    accrued_at: datetime
    sales_invoice_id: Optional[UUID] = None
    bridge_only: bool = False


class PFJTimelineResponse(BaseModel):
    pfj_id: UUID
    events: List[dict[str, Any]]


class CoverageProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pfj_id: UUID
    coverage_role: str
    obligor_route: str
    insurance_provider_id: Optional[UUID] = None
    employer_name: Optional[str] = None
    member_id: Optional[str] = None
    policy_number: Optional[str] = None
    insurer_coverage_percent: Decimal
    patient_copay_percent: Optional[Decimal] = None
    patient_copay_fixed: Optional[Decimal] = None


class CoverageProfileUpsert(BaseModel):
    obligor_route: str
    insurance_provider_id: Optional[UUID] = None
    employer_name: Optional[str] = None
    member_id: Optional[str] = None
    policy_number: Optional[str] = None
    insurer_coverage_percent: Optional[Decimal] = None
    patient_copay_percent: Optional[Decimal] = None
    patient_copay_fixed: Optional[Decimal] = None


class LiabilityLineResponse(BaseModel):
    obligor_type: str
    amount_inclusive: Decimal
    line_kind: str
    insurance_provider_id: Optional[UUID] = None
    employer_ref: Optional[str] = None


class LiabilityAllocationResponse(BaseModel):
    run_id: UUID
    care_charge_id: UUID
    version: int
    allocation_reason: str
    gross_amount_inclusive: Decimal
    lines: List[LiabilityLineResponse]


class LiabilityReallocateRequest(BaseModel):
    slices: List[LiabilityLineResponse]
    reason: str = "manual"


class PFJLiabilitySummaryResponse(BaseModel):
    pfj_id: UUID
    obligor_totals: dict[str, Decimal]
    note: str = "Derived from active allocation lines — not a stored balance."
