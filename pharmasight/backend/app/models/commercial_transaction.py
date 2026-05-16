"""
Commercial transaction spine (constitutional state) — not yet wired to sales_invoices.

Append-only transition audit trail. Layer 2 state engine persistence.
"""
from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base
from app.domain.commercial_transaction_state import TransactionState

_TRANSACTION_STATE_VALUES = ", ".join(f"'{s.value}'" for s in TransactionState)


class CommercialTransaction(Base):
  __tablename__ = "commercial_transactions"

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
  constitutional_state = Column(String(40), nullable=False, default=TransactionState.DRAFT.value)
  frozen_resume_state = Column(String(40), nullable=True)
  sales_invoice_id = Column(
    UUID(as_uuid=True),
    ForeignKey("sales_invoices.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
  )
  created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

  transitions = relationship(
    "CommercialTransactionTransition",
    back_populates="transaction",
    cascade="all, delete-orphan",
    order_by="CommercialTransactionTransition.created_at",
  )

  __table_args__ = (
    CheckConstraint(
      f"constitutional_state IN ({_TRANSACTION_STATE_VALUES})",
      name="ck_commercial_transactions_constitutional_state",
    ),
  )


class CommercialTransactionTransition(Base):
  """Append-only audit of constitutional state changes."""

  __tablename__ = "commercial_transaction_transitions"

  id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  commercial_transaction_id = Column(
    UUID(as_uuid=True),
    ForeignKey("commercial_transactions.id", ondelete="CASCADE"),
    nullable=False,
    index=True,
  )
  from_state = Column(String(40), nullable=False)
  to_state = Column(String(40), nullable=False)
  actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
  basis = Column(Text, nullable=True)
  supersedes_transition_id = Column(
    UUID(as_uuid=True),
    ForeignKey("commercial_transaction_transitions.id", ondelete="SET NULL"),
    nullable=True,
  )
  created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

  transaction = relationship("CommercialTransaction", back_populates="transitions")

  __table_args__ = (
    CheckConstraint(
      f"from_state IN ({_TRANSACTION_STATE_VALUES})",
      name="ck_commercial_transaction_transitions_from_state",
    ),
    CheckConstraint(
      f"to_state IN ({_TRANSACTION_STATE_VALUES})",
      name="ck_commercial_transaction_transitions_to_state",
    ),
  )
