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
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Encounters ---
class EncounterCreate(BaseModel):
    patient_id: UUID
    branch_id: UUID


class EncounterStatusUpdate(BaseModel):
    status: Literal["waiting", "in_consultation", "completed"]


class EncounterResponse(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    patient_id: UUID
    status: str
    sales_invoice_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

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
