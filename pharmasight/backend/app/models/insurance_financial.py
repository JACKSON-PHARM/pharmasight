"""
Insurance billing financial models:
- provider master
- invoice-linked claims/receivables
- settlements and allocations
- insurer ledger trail
"""
from sqlalchemy import Column, String, Numeric, Date, Text, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class InsuranceProvider(Base):
    __tablename__ = "insurance_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False)
    contact_person = Column(String(255))
    phone = Column(String(50))
    email = Column(String(255))
    address = Column(Text)
    terms_days = Column(Numeric(10, 0), nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_insurance_providers_company_name"),
        UniqueConstraint("company_id", "code", name="uq_insurance_providers_company_code"),
    )


class InsuranceClaim(Base):
    __tablename__ = "insurance_claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    insurance_provider_id = Column(UUID(as_uuid=True), ForeignKey("insurance_providers.id", ondelete="CASCADE"), nullable=False)
    sales_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False)
    claim_number = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="submitted")
    billed_amount = Column(Numeric(20, 4), nullable=False, default=0)
    approved_amount = Column(Numeric(20, 4), nullable=False, default=0)
    settled_amount = Column(Numeric(20, 4), nullable=False, default=0)
    outstanding_amount = Column(Numeric(20, 4), nullable=False, default=0)
    submitted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    due_date = Column(Date)
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    insurance_provider = relationship("InsuranceProvider")
    sales_invoice = relationship("SalesInvoice")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        UniqueConstraint("company_id", "claim_number", name="uq_insurance_claims_company_number"),
    )


class InsuranceSettlement(Base):
    __tablename__ = "insurance_settlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    insurance_provider_id = Column(UUID(as_uuid=True), ForeignKey("insurance_providers.id", ondelete="CASCADE"), nullable=False)
    settlement_number = Column(String(100), nullable=False)
    settlement_date = Column(Date, nullable=False)
    method = Column(String(50), nullable=False, default="bank")
    reference = Column(String(255))
    amount = Column(Numeric(20, 4), nullable=False)
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    insurance_provider = relationship("InsuranceProvider")
    creator = relationship("User", foreign_keys=[created_by])
    allocations = relationship(
        "InsuranceSettlementAllocation",
        back_populates="settlement",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "settlement_number", name="uq_insurance_settlements_company_number"),
    )


class InsuranceSettlementAllocation(Base):
    __tablename__ = "insurance_settlement_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    insurance_settlement_id = Column(UUID(as_uuid=True), ForeignKey("insurance_settlements.id", ondelete="CASCADE"), nullable=False)
    insurance_claim_id = Column(UUID(as_uuid=True), ForeignKey("insurance_claims.id", ondelete="CASCADE"), nullable=False)
    allocated_amount = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    settlement = relationship("InsuranceSettlement", back_populates="allocations")
    claim = relationship("InsuranceClaim")


class InsuranceLedgerEntry(Base):
    __tablename__ = "insurance_ledger_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    insurance_provider_id = Column(UUID(as_uuid=True), ForeignKey("insurance_providers.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    entry_type = Column(String(50), nullable=False)  # claim, settlement, adjustment
    reference_id = Column(UUID(as_uuid=True))
    debit = Column(Numeric(20, 4), nullable=False, default=0)   # insurer receivable created
    credit = Column(Numeric(20, 4), nullable=False, default=0)  # insurer settlement received
    running_balance = Column(Numeric(20, 4))
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    company = relationship("Company")
    branch = relationship("Branch")
    insurance_provider = relationship("InsuranceProvider")
