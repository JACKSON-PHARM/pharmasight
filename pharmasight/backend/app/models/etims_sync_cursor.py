"""Persist OSCU lastReqDt cursor per branch + category."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import CHAR, TIMESTAMP

from app.database import Base


class EtimsSyncCursor(Base):
    """
    OSCU spec v2.0: TIS must persist the last successful retrieval date-time (lastReqDt, CHAR(14))
    and send it on the next request for the same kind of data.
    """

    __tablename__ = "etims_sync_cursor"
    __table_args__ = (UniqueConstraint("branch_id", "category", name="uq_etims_sync_cursor_branch_category"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(60), nullable=False)
    last_req_dt = Column(CHAR(14), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    company = relationship("Company")
    branch = relationship("Branch")

