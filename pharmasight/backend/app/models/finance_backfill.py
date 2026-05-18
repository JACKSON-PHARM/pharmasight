"""Audit trail for controlled financial event backfill runs (E5)."""
from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid

from app.database import Base


class FinanceBackfillRun(Base):
    __tablename__ = "finance_backfill_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True)
    correlation_group = Column(String(255), nullable=False)
    policy_pack_id = Column(String(40), nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    event_types_filter = Column(JSONB, nullable=True)
    status = Column(String(20), nullable=False, default="running")
    events_created = Column(Integer, nullable=False, default=0)
    events_duplicate = Column(Integer, nullable=False, default=0)
    events_failed = Column(Integer, nullable=False, default=0)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    detail_json = Column(JSONB, nullable=False, server_default="{}")

    company = relationship("Company")
    branch = relationship("Branch")
