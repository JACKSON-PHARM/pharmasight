"""
E7 accounting orchestration models — journal proposals (interpretation layer only).

Not a general ledger. No authoritative balances. Does not mutate financial_events.
"""
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid

from app.database import Base


class JournalProposal(Base):
    __tablename__ = "journal_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    proposal_number = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="draft")
    policy_pack_id = Column(String(40), nullable=False, default="STANDARD_KENYA")
    source_financial_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=False
    )
    reversal_of_proposal_id = Column(
        UUID(as_uuid=True), ForeignKey("journal_proposals.id", ondelete="SET NULL"), nullable=True
    )
    commercial_transaction_id = Column(
        UUID(as_uuid=True), ForeignKey("commercial_transactions.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key = Column(String(255), nullable=False)
    proposal_schema_version = Column(Integer, nullable=False, default=1)
    currency_code = Column(String(3), nullable=False, default="KES")
    total_amount = Column(Numeric(20, 4), nullable=False)
    occurred_at = Column(TIMESTAMP(timezone=True), nullable=False)
    governance_metadata_json = Column(JSONB, nullable=False, server_default="{}")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    posted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    posted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    lines = relationship("JournalProposalLine", back_populates="proposal", cascade="all, delete-orphan")
    evidence_links = relationship("JournalProposalEvidence", back_populates="proposal", cascade="all, delete-orphan")
    posting_record = relationship("AccountingPostingRecord", back_populates="proposal", uselist=False)


class JournalProposalLine(Base):
    __tablename__ = "journal_proposal_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_proposal_id = Column(
        UUID(as_uuid=True), ForeignKey("journal_proposals.id", ondelete="CASCADE"), nullable=False
    )
    line_order = Column(Integer, nullable=False)
    account_semantic = Column(String(80), nullable=False)
    line_direction = Column(String(10), nullable=False)
    amount = Column(Numeric(20, 4), nullable=False)
    description = Column(Text)

    proposal = relationship("JournalProposal", back_populates="lines")


class JournalProposalEvidence(Base):
    __tablename__ = "journal_proposal_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_proposal_id = Column(
        UUID(as_uuid=True), ForeignKey("journal_proposals.id", ondelete="CASCADE"), nullable=False
    )
    financial_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=False
    )
    link_semantic = Column(String(50), nullable=False, default="primary_source")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    proposal = relationship("JournalProposal", back_populates="evidence_links")


class AccountingPostingRecord(Base):
    __tablename__ = "accounting_posting_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    journal_proposal_id = Column(
        UUID(as_uuid=True), ForeignKey("journal_proposals.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    posted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    posted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    posting_semantic = Column(String(50), nullable=False, default="interpretation_committed")
    detail_json = Column(JSONB, nullable=False, server_default="{}")

    proposal = relationship("JournalProposal", back_populates="posting_record")
