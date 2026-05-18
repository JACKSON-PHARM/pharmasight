"""M1 authoritative general ledger models."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(20), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True)
    control_role = Column(String(50), nullable=True)
    is_control_account = Column(Boolean, nullable=False, default=False)
    normal_balance = Column(String(10), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    parent = relationship("ChartOfAccount", remote_side=[id])


class FiscalPeriod(Base):
    __tablename__ = "fiscal_periods"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(40), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="OPEN")
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    closed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    close_notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    company = relationship("Company")


class GlJournalEntry(Base):
    __tablename__ = "gl_journal_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    fiscal_period_id = Column(UUID(as_uuid=True), ForeignKey("fiscal_periods.id", ondelete="RESTRICT"), nullable=False)
    journal_number = Column(String(40), nullable=False)
    posting_date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="POSTED")
    source_type = Column(String(50), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    posting_kind = Column(String(50), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    reversal_of_entry_id = Column(
        UUID(as_uuid=True), ForeignKey("gl_journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    posted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    posted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    currency_code = Column(String(3), nullable=False, default="KES")
    metadata_json = Column(JSONB, nullable=False, server_default="{}")

    company = relationship("Company")
    branch = relationship("Branch")
    fiscal_period = relationship("FiscalPeriod")
    lines = relationship("GlJournalLine", back_populates="journal_entry", cascade="all, delete-orphan")


class GlJournalLine(Base):
    __tablename__ = "gl_journal_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_entry_id = Column(
        UUID(as_uuid=True), ForeignKey("gl_journal_entries.id", ondelete="CASCADE"), nullable=False
    )
    line_order = Column(Integer, nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    debit = Column(Numeric(20, 4), nullable=False, default=0)
    credit = Column(Numeric(20, 4), nullable=False, default=0)
    description = Column(Text, nullable=True)

    journal_entry = relationship("GlJournalEntry", back_populates="lines")
    account = relationship("ChartOfAccount")
    branch = relationship("Branch")


class GlPostingFailure(Base):
    __tablename__ = "gl_posting_failures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    source_type = Column(String(50), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    posting_kind = Column(String(50), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    error_message = Column(Text, nullable=False)
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
