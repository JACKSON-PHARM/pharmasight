"""OPD / Clinic models (company-scoped, single shared database)."""
import uuid

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    CheckConstraint,
    Boolean,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    phone = Column(Text, nullable=True)
    gender = Column(Text, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    id_number = Column(Text, nullable=True)
    residence = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company")


class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(30), nullable=False, default="waiting")
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=True)
    initial_destination = Column(String(30), nullable=True)
    intake_payment_mode = Column(Text, nullable=True)
    intake_insurance_scheme = Column(Text, nullable=True)
    sales_invoice_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    patient = relationship("Patient")
    branch = relationship("Branch")
    sales_invoice = relationship("SalesInvoice", foreign_keys=[sales_invoice_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting','in_consultation','completed')",
            name="ck_encounters_status",
        ),
        CheckConstraint(
            "initial_destination IS NULL OR initial_destination IN ('triage','consultation','pharmacy','lab','radiology','procedure','referral')",
            name="ck_encounters_initial_destination",
        ),
    )


class EncounterNote(Base):
    __tablename__ = "encounter_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encounter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notes = Column(Text, nullable=True)
    diagnosis = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    encounter = relationship("Encounter")


class ClinicOrder(Base):
    __tablename__ = "clinic_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encounter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_type = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="requested")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    encounter = relationship("Encounter")
    items = relationship(
        "ClinicOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "order_type IN ('prescription','lab','procedure')",
            name="ck_clinic_orders_type",
        ),
        CheckConstraint(
            "status IN ('requested','in_progress','completed')",
            name="ck_clinic_orders_status",
        ),
    )


class ClinicOrderItem(Base):
    __tablename__ = "clinic_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinic_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference_type = Column(String(20), nullable=False)
    reference_id = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False, default=1)
    notes = Column(Text, nullable=True)

    order = relationship("ClinicOrder", back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "reference_type IN ('item','service')",
            name="ck_clinic_order_items_ref_type",
        ),
    )


class EncounterTriage(Base):
    """
    Triage snapshot for an encounter (separate from consultation notes).
    One triage record per encounter (upserted as needed).
    """

    __tablename__ = "encounter_triage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encounter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    payment_mode = Column(Text, nullable=True)
    insurance_scheme = Column(Text, nullable=True)
    chief_complaint = Column(Text, nullable=True)
    allergies = Column(Text, nullable=True)
    symptoms = Column(Text, nullable=True)
    triage_notes = Column(Text, nullable=True)
    vitals = Column(JSONB, nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    encounter = relationship("Encounter")
    patient = relationship("Patient")


class ClinicalService(Base):
    __tablename__ = "clinical_services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)
    code = Column(Text, nullable=True)
    department = Column(Text, nullable=True)
    allowed_departments = Column(JSONB, nullable=True)
    strict_department_only = Column(Boolean, nullable=False, default=False)
    description = Column(Text, nullable=True)
    fee = Column(Numeric(20, 4), nullable=False, default=0)
    billing_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    billing_item = relationship("Item", foreign_keys=[billing_item_id])
    components = relationship("ClinicalServiceComponent", back_populates="service", cascade="all, delete-orphan")


class ClinicalServiceComponent(Base):
    __tablename__ = "clinical_service_components"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinical_services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_unit_name = Column(Text, nullable=True)
    quantity_per_service = Column(Numeric(20, 4), nullable=False, default=1)
    is_optional = Column(Boolean, nullable=False, default=False)
    deduction_policy = Column(String(20), nullable=False, default="immediate")
    accumulator_threshold_qty = Column(Numeric(20, 4), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    service = relationship("ClinicalService", back_populates="components")
    item = relationship("Item")

    __table_args__ = (
        CheckConstraint("quantity_per_service > 0", name="ck_service_component_qty_positive"),
        CheckConstraint(
            "deduction_policy IN ('immediate','accumulator')",
            name="ck_service_component_policy",
        ),
        CheckConstraint(
            "accumulator_threshold_qty IS NULL OR accumulator_threshold_qty > 0",
            name="ck_service_component_threshold_positive",
        ),
        UniqueConstraint("service_id", "item_id", name="uq_service_component_service_item"),
    )


class ClinicalServiceAccumulator(Base):
    __tablename__ = "clinical_service_accumulators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_component_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinical_service_components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    accumulated_qty_base = Column(Numeric(20, 4), nullable=False, default=0)
    last_deducted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    service_component = relationship("ClinicalServiceComponent")

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "branch_id",
            "service_component_id",
            name="uq_service_accumulator_company_branch_component",
        ),
    )


class EncounterServiceExecution(Base):
    __tablename__ = "encounter_service_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encounter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinical_services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity = Column(Numeric(20, 4), nullable=False, default=1)
    billed_amount = Column(Numeric(20, 4), nullable=False, default=0)
    notes = Column(Text, nullable=True)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    encounter = relationship("Encounter")
    service = relationship("ClinicalService")
    lines = relationship("EncounterServiceExecutionLine", back_populates="execution", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_service_execution_qty_positive"),
    )


class EncounterServiceExecutionLine(Base):
    __tablename__ = "encounter_service_execution_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(
        UUID(as_uuid=True),
        ForeignKey("encounter_service_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_component_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinical_service_components.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy = Column(String(20), nullable=False, default="immediate")
    selected = Column(Boolean, nullable=False, default=True)
    requested_qty = Column(Numeric(20, 4), nullable=False, default=0)
    deducted_qty = Column(Numeric(20, 4), nullable=False, default=0)
    item_unit_name = Column(Text, nullable=True)
    requested_qty_base = Column(Numeric(20, 4), nullable=False, default=0)
    deducted_qty_base = Column(Numeric(20, 4), nullable=False, default=0)
    accumulator_before_base = Column(Numeric(20, 4), nullable=True)
    accumulator_after_base = Column(Numeric(20, 4), nullable=True)

    execution = relationship("EncounterServiceExecution", back_populates="lines")
    item = relationship("Item")
    service_component = relationship("ClinicalServiceComponent")

    __table_args__ = (
        CheckConstraint("policy IN ('immediate','accumulator')", name="ck_service_exec_line_policy"),
    )


class DepartmentStore(Base):
    __tablename__ = "department_stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_department_store_company_branch_code"),
    )


class DepartmentStoreStock(Base):
    __tablename__ = "department_store_stock"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("department_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity_base = Column(Numeric(20, 4), nullable=False, default=0)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    store = relationship("DepartmentStore")
    item = relationship("Item")

    __table_args__ = (
        UniqueConstraint("store_id", "item_id", name="uq_department_store_stock_store_item"),
    )


class DepartmentStoreMovement(Base):
    __tablename__ = "department_store_movements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("department_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    movement_type = Column(String(30), nullable=False)
    quantity_delta_base = Column(Numeric(20, 4), nullable=False)
    reference_type = Column(Text, nullable=True)
    reference_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    store = relationship("DepartmentStore")
    item = relationship("Item")

    __table_args__ = (
        CheckConstraint("quantity_delta_base != 0", name="ck_department_store_movement_delta_not_zero"),
        CheckConstraint(
            "movement_type IN ('ISSUE_IN','CONSUME_OUT','ADJUSTMENT','RECONCILE','RETURN_TO_PHARMACY')",
            name="ck_department_store_movement_type",
        ),
    )
