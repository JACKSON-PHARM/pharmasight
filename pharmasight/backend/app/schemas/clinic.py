from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# --- Patients ---
class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    id_number: Optional[str] = None
    residence: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def name_non_empty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("Name fields cannot be empty")
        return s

    @field_validator("phone")
    @classmethod
    def phone_sanitized(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        raw = str(v).strip()
        if not raw:
            return None
        # Keep digits and leading + for international-style numbers
        cleaned = re.sub(r"[^\d+]", "", raw)
        if not cleaned or cleaned == "+":
            return None
        return cleaned[:32]


class PatientResponse(BaseModel):
    id: UUID
    company_id: UUID
    first_name: str
    last_name: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    id_number: Optional[str] = None
    residence: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    id_number: Optional[str] = None
    residence: Optional[str] = None


# --- Encounters ---
class EncounterCreate(BaseModel):
    patient_id: UUID
    branch_id: UUID
    scheduled_for: Optional[datetime] = None
    initial_destination: Optional[Literal["triage", "consultation", "pharmacy", "lab", "radiology", "procedure", "referral"]] = None
    payment_mode: Optional[str] = None
    insurance_scheme: Optional[str] = None


class EncounterStatusUpdate(BaseModel):
    status: Literal["waiting", "in_consultation", "completed"]


class EncounterResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    patient_id: UUID
    status: str
    scheduled_for: Optional[datetime] = None
    initial_destination: Optional[str] = None
    intake_payment_mode: Optional[str] = None
    intake_insurance_scheme: Optional[str] = None
    sales_invoice_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    # Convenience: include patient summary to avoid N+1 fetches on the UI (queue screens).
    patient: Optional[PatientResponse] = None

    class Config:
        from_attributes = True


# --- Triage ---
class EncounterTriageUpsert(BaseModel):
    payment_mode: Optional[str] = None  # e.g. cash | insurance | other
    insurance_scheme: Optional[str] = None
    chief_complaint: Optional[str] = None
    allergies: Optional[str] = None
    symptoms: Optional[str] = None
    triage_notes: Optional[str] = None
    vitals: Optional[dict] = None


class EncounterTriageResponse(BaseModel):
    id: UUID
    encounter_id: UUID
    company_id: UUID
    branch_id: UUID
    patient_id: UUID
    payment_mode: Optional[str] = None
    insurance_scheme: Optional[str] = None
    chief_complaint: Optional[str] = None
    allergies: Optional[str] = None
    symptoms: Optional[str] = None
    triage_notes: Optional[str] = None
    vitals: Optional[dict] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Notes ---
class EncounterNoteCreate(BaseModel):
    notes: Optional[str] = None
    diagnosis: Optional[str] = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        n = (self.notes or "").strip()
        d = (self.diagnosis or "").strip()
        if not n and not d:
            raise ValueError("Provide notes and/or diagnosis")
        return self


class EncounterNoteResponse(BaseModel):
    id: UUID
    encounter_id: UUID
    notes: Optional[str] = None
    diagnosis: Optional[str] = None
    created_by: UUID
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Clinic orders ---
class ClinicOrderItemCreate(BaseModel):
    reference_type: Literal["item", "service"]
    reference_id: UUID
    quantity: Decimal = Field(default=Decimal("1"))
    notes: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError("quantity must be greater than 0")
        return v


class ClinicOrderCreate(BaseModel):
    order_type: Literal["prescription", "lab", "procedure"]
    items: List[ClinicOrderItemCreate] = Field(..., min_length=1)


class ClinicOrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    reference_type: str
    reference_id: UUID
    quantity: Decimal
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ClinicOrderResponse(BaseModel):
    id: UUID
    company_id: UUID
    encounter_id: UUID
    order_type: str
    status: str
    created_at: Optional[datetime] = None
    items: List[ClinicOrderItemResponse] = []

    class Config:
        from_attributes = True


# --- Clinical services catalog ---
class ClinicalServiceComponentCreate(BaseModel):
    item_id: UUID
    item_unit_name: Optional[str] = None
    quantity_per_service: Decimal = Field(default=Decimal("1"))
    is_optional: bool = False
    deduction_policy: Literal["immediate", "accumulator"] = "immediate"
    accumulator_threshold_qty: Optional[Decimal] = None
    sort_order: int = 0
    notes: Optional[str] = None

    @field_validator("quantity_per_service")
    @classmethod
    def component_qty_positive(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError("quantity_per_service must be greater than 0")
        return v

    @model_validator(mode="after")
    def accumulator_requires_threshold(self):
        if self.deduction_policy == "accumulator" and (self.accumulator_threshold_qty is None or self.accumulator_threshold_qty <= 0):
            raise ValueError("accumulator_threshold_qty is required and must be > 0 for accumulator policy")
        return self


class ClinicalServiceCreate(BaseModel):
    name: str
    code: Optional[str] = None
    department: Optional[str] = None
    allowed_departments: List[str] = Field(default_factory=list)
    strict_department_only: bool = False
    description: Optional[str] = None
    fee: Decimal = Field(default=Decimal("0"))
    is_active: bool = True
    components: List[ClinicalServiceComponentCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def service_name_non_empty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("name is required")
        return s

    @field_validator("fee")
    @classmethod
    def service_fee_non_negative(cls, v: Decimal) -> Decimal:
        if v is None or v < 0:
            raise ValueError("fee must be >= 0")
        return v


class ClinicalServiceUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    department: Optional[str] = None
    allowed_departments: Optional[List[str]] = None
    strict_department_only: Optional[bool] = None
    description: Optional[str] = None
    fee: Optional[Decimal] = None
    is_active: Optional[bool] = None
    components: Optional[List[ClinicalServiceComponentCreate]] = None


class ClinicalServiceComponentResponse(BaseModel):
    id: UUID
    service_id: UUID
    item_id: UUID
    item_unit_name: Optional[str] = None
    quantity_per_service: Decimal
    is_optional: bool
    deduction_policy: str
    accumulator_threshold_qty: Optional[Decimal] = None
    sort_order: int
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ClinicalServiceResponse(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: Optional[str] = None
    department: Optional[str] = None
    allowed_departments: List[str] = []
    strict_department_only: bool = False
    description: Optional[str] = None
    fee: Decimal
    billing_item_id: Optional[UUID] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    components: List[ClinicalServiceComponentResponse] = []

    class Config:
        from_attributes = True


class ServiceExecutionComponentInput(BaseModel):
    service_component_id: UUID
    selected: bool = True
    quantity_override: Optional[Decimal] = None

    @field_validator("quantity_override")
    @classmethod
    def quantity_override_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("quantity_override must be > 0")
        return v


class ServiceExecutionRequest(BaseModel):
    service_id: UUID
    quantity: Decimal = Field(default=Decimal("1"))
    execution_department: Optional[str] = None
    department_store_id: Optional[UUID] = None
    notes: Optional[str] = None
    components: List[ServiceExecutionComponentInput] = Field(default_factory=list)

    @field_validator("quantity")
    @classmethod
    def execution_quantity_positive(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError("quantity must be > 0")
        return v


class ServiceExecutionLineResponse(BaseModel):
    id: UUID
    item_id: UUID
    policy: str
    selected: bool
    requested_qty: Decimal
    deducted_qty: Decimal
    item_unit_name: Optional[str] = None
    requested_qty_base: Decimal
    deducted_qty_base: Decimal
    accumulator_before_base: Optional[Decimal] = None
    accumulator_after_base: Optional[Decimal] = None

    class Config:
        from_attributes = True


class ServiceExecutionResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    encounter_id: UUID
    service_id: UUID
    quantity: Decimal
    billed_amount: Decimal
    notes: Optional[str] = None
    performed_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    lines: List[ServiceExecutionLineResponse] = []

    class Config:
        from_attributes = True


class DepartmentStoreCreate(BaseModel):
    branch_id: UUID
    code: str
    name: str
    is_active: bool = True


class DepartmentStoreResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    code: str
    name: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DepartmentStoreSeedDefaultsRequest(BaseModel):
    branch_id: UUID


class DepartmentStoreSeedDefaultsResponse(BaseModel):
    """Idempotent: only inserts stores whose codes are not already present on the branch."""

    created: List[DepartmentStoreResponse] = Field(default_factory=list)
    skipped_codes: List[str] = Field(default_factory=list)


class DepartmentStoreIssueLine(BaseModel):
    item_id: UUID
    quantity: Decimal
    unit_name: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def issue_qty_positive(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError("quantity must be > 0")
        return v


class DepartmentStoreIssueRequest(BaseModel):
    lines: List[DepartmentStoreIssueLine] = Field(..., min_length=1)


class DepartmentStoreReconcileLine(BaseModel):
    item_id: UUID
    quantity_delta: Decimal
    unit_name: Optional[str] = None
    reason: Optional[str] = None

    @field_validator("quantity_delta")
    @classmethod
    def reconcile_delta_non_zero(cls, v: Decimal) -> Decimal:
        if v is None or v == 0:
            raise ValueError("quantity_delta must not be zero")
        return v


class DepartmentStoreReconcileRequest(BaseModel):
    lines: List[DepartmentStoreReconcileLine] = Field(..., min_length=1)


class DepartmentStoreReturnLine(BaseModel):
    item_id: UUID
    quantity: Decimal
    unit_name: Optional[str] = None
    reason: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def return_qty_positive(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError("quantity must be > 0")
        return v


class DepartmentStoreReturnRequest(BaseModel):
    lines: List[DepartmentStoreReturnLine] = Field(..., min_length=1)
