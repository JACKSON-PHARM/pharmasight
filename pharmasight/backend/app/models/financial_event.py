"""
Financial events — immutable economic lineage (E3/E4). Not accounting postings.
"""
from sqlalchemy import Column, String, Numeric, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class FinancialEvent(Base):
    __tablename__ = "financial_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    operational_domain = Column(String(40), nullable=False)
    event_type = Column(String(80), nullable=False)
    classification = Column(String(20), nullable=False)
    event_schema_version = Column(Integer, nullable=False, default=1)
    occurred_at = Column(TIMESTAMP(timezone=True), nullable=False)
    emitted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    amount = Column(Numeric(20, 4), nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES")
    economic_direction = Column(String(32), nullable=False)
    source_entity_type = Column(String(80), nullable=False)
    source_entity_id = Column(UUID(as_uuid=True), nullable=False)
    source_reference = Column(String(255), nullable=True)
    idempotency_key = Column(String(255), nullable=False)
    reversal_of_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=True
    )
    caused_by_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=True
    )
    payload_json = Column(JSONB, nullable=False, default=dict)
    governance_metadata_json = Column(JSONB, nullable=False, default=dict)
    operational_status = Column(String(32), nullable=False, default="emitted")
    emission_channel = Column(String(32), nullable=False, default="original")
    correlation_group = Column(String(255), nullable=True)
    replay_source_failure_id = Column(
        UUID(as_uuid=True),
        ForeignKey("financial_event_emission_failures.id", ondelete="SET NULL"),
        nullable=True,
    )


class FinancialEventEmissionFailure(Base):
    __tablename__ = "financial_event_emission_failures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    operational_domain = Column(String(40), nullable=False)
    event_type = Column(String(80), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    source_entity_type = Column(String(80), nullable=False)
    source_entity_id = Column(UUID(as_uuid=True), nullable=False)
    source_reference = Column(String(255), nullable=True)
    occurred_at = Column(TIMESTAMP(timezone=True), nullable=False)
    amount = Column(Numeric(20, 4), nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES")
    economic_direction = Column(String(32), nullable=False)
    classification = Column(String(20), nullable=False)
    event_schema_version = Column(Integer, nullable=False, default=1)
    payload_json = Column(JSONB, nullable=False, default=dict)
    governance_metadata_json = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    last_replay_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_replay_result = Column(String(32), nullable=True)
    resolved_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="SET NULL"), nullable=True
    )


class FinancialEventSettlementLink(Base):
    __tablename__ = "financial_event_settlement_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    settlement_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=False
    )
    settles_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="RESTRICT"), nullable=False
    )
    amount_settled = Column(Numeric(20, 4), nullable=False)
    settlement_semantic = Column(String(64), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class FinancialEventReplayLog(Base):
    __tablename__ = "financial_event_replay_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    failure_id = Column(
        UUID(as_uuid=True),
        ForeignKey("financial_event_emission_failures.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key = Column(String(255), nullable=False)
    replay_result = Column(String(32), nullable=False)
    financial_event_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_events.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    detail_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
