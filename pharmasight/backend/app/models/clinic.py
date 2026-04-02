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
)
from sqlalchemy.dialects.postgresql import UUID
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
