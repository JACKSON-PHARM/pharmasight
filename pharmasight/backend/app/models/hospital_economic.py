"""
Hospital Economic Kernel — PFJ and care charges (H1).

Operational authority for accrued care value. Feeds financial_events; does not replace
sales_invoices (transitional bridge only).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class PatientFinancialJourney(Base):
    __tablename__ = "patient_financial_journeys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="open")
    opened_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    intake_payment_mode_hint = Column(Text, nullable=True)
    intake_insurance_scheme_hint = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    patient = relationship("Patient", foreign_keys=[patient_id])
    branch = relationship("Branch")
    charges = relationship("CareCharge", back_populates="pfj", foreign_keys="CareCharge.pfj_id")
    coverage_profiles = relationship(
        "PfjCoverageProfile", back_populates="pfj", foreign_keys="PfjCoverageProfile.pfj_id"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open','accruing','pending_discharge','financial_closed','archived')",
            name="ck_pfj_status",
        ),
    )


class CareCharge(Base):
    __tablename__ = "care_charges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    pfj_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_financial_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encounter_id = Column(UUID(as_uuid=True), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True)
    charge_kind = Column(String(40), nullable=False)
    accrual_status = Column(String(20), nullable=False, default="accrued")
    clinical_trigger = Column(String(30), nullable=False, default="performed")
    source_entity_type = Column(String(80), nullable=False)
    source_entity_id = Column(UUID(as_uuid=True), nullable=False)
    description = Column(Text, nullable=False, default="")
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    clinical_service_id = Column(
        UUID(as_uuid=True), ForeignKey("clinical_services.id", ondelete="SET NULL"), nullable=True
    )
    quantity = Column(Numeric(20, 4), nullable=False, default=1)
    unit_name = Column(String(50), nullable=True)
    amount_exclusive = Column(Numeric(20, 4), nullable=False, default=0)
    vat_amount = Column(Numeric(20, 4), nullable=False, default=0)
    amount_inclusive = Column(Numeric(20, 4), nullable=False, default=0)
    currency_code = Column(String(3), nullable=False, default="KES")
    accrued_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    reversed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reversal_of_charge_id = Column(UUID(as_uuid=True), ForeignKey("care_charges.id", ondelete="SET NULL"), nullable=True)
    sales_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="SET NULL"), nullable=True)
    sales_invoice_item_id = Column(
        UUID(as_uuid=True), ForeignKey("sales_invoice_items.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    pfj = relationship("PatientFinancialJourney", back_populates="charges", foreign_keys=[pfj_id])
    encounter = relationship("Encounter", foreign_keys=[encounter_id])
    allocation_runs = relationship(
        "LiabilityAllocationRun",
        back_populates="care_charge",
        foreign_keys="LiabilityAllocationRun.care_charge_id",
    )

    __table_args__ = (
        CheckConstraint(
            "charge_kind IN ('consultation','lab','pharmacy','procedure','accommodation','radiology','other')",
            name="ck_care_charges_kind",
        ),
        CheckConstraint(
            "accrual_status IN ('provisional','accrued','reversed')",
            name="ck_care_charges_accrual_status",
        ),
        CheckConstraint(
            "clinical_trigger IN ('ordered','performed','resulted','dispensed','completed','scheduled')",
            name="ck_care_charges_clinical_trigger",
        ),
    )


class PfjCoverageProfile(Base):
    __tablename__ = "pfj_coverage_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    pfj_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_financial_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    coverage_role = Column(String(20), nullable=False, default="primary")
    obligor_route = Column(String(20), nullable=False, default="self_pay")
    insurance_provider_id = Column(
        UUID(as_uuid=True), ForeignKey("insurance_providers.id", ondelete="SET NULL"), nullable=True
    )
    employer_name = Column(Text, nullable=True)
    member_id = Column(Text, nullable=True)
    policy_number = Column(Text, nullable=True)
    insurer_coverage_percent = Column(Numeric(8, 4), nullable=False, default=80)
    patient_copay_percent = Column(Numeric(8, 4), nullable=True)
    patient_copay_fixed = Column(Numeric(20, 4), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    pfj = relationship("PatientFinancialJourney", back_populates="coverage_profiles", foreign_keys=[pfj_id])
    insurance_provider = relationship("InsuranceProvider", foreign_keys=[insurance_provider_id])

    __table_args__ = (
        CheckConstraint("coverage_role IN ('primary','secondary')", name="ck_pfj_coverage_role"),
        CheckConstraint(
            "obligor_route IN ('self_pay','insurance','employer','mixed')", name="ck_pfj_obligor_route"
        ),
    )


class LiabilityAllocationRun(Base):
    __tablename__ = "liability_allocation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    pfj_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_financial_journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    care_charge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("care_charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)
    allocation_reason = Column(String(40), nullable=False, default="initial")
    status = Column(String(20), nullable=False, default="active")
    gross_amount_inclusive = Column(Numeric(20, 4), nullable=False, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    superseded_at = Column(TIMESTAMP(timezone=True), nullable=True)
    superseded_by_run_id = Column(
        UUID(as_uuid=True), ForeignKey("liability_allocation_runs.id", ondelete="SET NULL"), nullable=True
    )

    care_charge = relationship("CareCharge", back_populates="allocation_runs", foreign_keys=[care_charge_id])
    lines = relationship(
        "LiabilityAllocationLine",
        back_populates="run",
        foreign_keys="LiabilityAllocationLine.run_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "allocation_reason IN ('initial','coverage_change','denial_reallocation','manual','self_pay_default')",
            name="ck_liability_run_reason",
        ),
        CheckConstraint("status IN ('active','superseded')", name="ck_liability_run_status"),
    )


class LiabilityAllocationLine(Base):
    __tablename__ = "liability_allocation_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("liability_allocation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    obligor_type = Column(String(20), nullable=False)
    insurance_provider_id = Column(
        UUID(as_uuid=True), ForeignKey("insurance_providers.id", ondelete="SET NULL"), nullable=True
    )
    employer_ref = Column(Text, nullable=True)
    amount_inclusive = Column(Numeric(20, 4), nullable=False, default=0)
    line_kind = Column(String(30), nullable=False, default="obligated")
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("LiabilityAllocationRun", back_populates="lines", foreign_keys=[run_id])

    __table_args__ = (
        CheckConstraint(
            "obligor_type IN ('patient','insurer','employer','guarantor')", name="ck_liability_line_obligor"
        ),
        CheckConstraint(
            "line_kind IN ('obligated','pending_authorization','denied')", name="ck_liability_line_kind"
        ),
    )


class CareAuthorization(Base):
    __tablename__ = "care_authorizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    pfj_id = Column(UUID(as_uuid=True), ForeignKey("patient_financial_journeys.id", ondelete="CASCADE"), nullable=False)
    care_charge_id = Column(UUID(as_uuid=True), ForeignKey("care_charges.id", ondelete="SET NULL"), nullable=True)
    insurance_provider_id = Column(
        UUID(as_uuid=True), ForeignKey("insurance_providers.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String(30), nullable=False, default="requested")
    reference_number = Column(String(100), nullable=True)
    requested_amount = Column(Numeric(20, 4), nullable=False, default=0)
    approved_amount = Column(Numeric(20, 4), nullable=False, default=0)
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class HospitalRecognitionRecord(Base):
    __tablename__ = "hospital_recognition_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    pfj_id = Column(UUID(as_uuid=True), ForeignKey("patient_financial_journeys.id", ondelete="CASCADE"), nullable=False)
    care_charge_id = Column(UUID(as_uuid=True), ForeignKey("care_charges.id", ondelete="CASCADE"), nullable=False)
    allocation_line_id = Column(
        UUID(as_uuid=True), ForeignKey("liability_allocation_lines.id", ondelete="CASCADE"), nullable=False
    )
    obligor_type = Column(String(20), nullable=False)
    recognized_amount = Column(Numeric(20, 4), nullable=False)
    financial_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="SET NULL"), nullable=True
    )
    recognized_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("allocation_line_id", "obligor_type", name="uq_hospital_recognition_line"),)


class InsuranceClaimLine(Base):
    __tablename__ = "insurance_claim_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    insurance_claim_id = Column(
        UUID(as_uuid=True), ForeignKey("insurance_claims.id", ondelete="CASCADE"), nullable=False
    )
    care_charge_id = Column(UUID(as_uuid=True), ForeignKey("care_charges.id", ondelete="CASCADE"), nullable=False)
    amount_inclusive = Column(Numeric(20, 4), nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("insurance_claim_id", "care_charge_id", name="uq_claim_line_charge"),)


class PfjDischargeSettlement(Base):
    __tablename__ = "pfj_discharge_settlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    pfj_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_financial_journeys.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    patient_residual = Column(Numeric(20, 4), nullable=False, default=0)
    insurer_outstanding = Column(Numeric(20, 4), nullable=False, default=0)
    notes = Column(Text, nullable=True)
    closed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
