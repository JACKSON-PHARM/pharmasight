"""Audit log for KRA eTIMS OSCU submissions."""

import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class EtimsSubmissionLog(Base):
    __tablename__ = "etims_submission_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sales_invoice_id = Column(UUID(as_uuid=True), ForeignKey("sales_invoices.id", ondelete="SET NULL"), nullable=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    request_payload_hash = Column(String(64), nullable=True)
    response_status = Column(String(40), nullable=True)
    http_status = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    sales_invoice = relationship("SalesInvoice", foreign_keys=[sales_invoice_id])
    company = relationship("Company")
    branch = relationship("Branch")
