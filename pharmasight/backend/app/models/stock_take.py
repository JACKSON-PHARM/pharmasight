"""
Stock Take models for multi-user stock take sessions
"""
from sqlalchemy import Column, String, Boolean, ForeignKey, Text, Integer, CheckConstraint, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class StockTakeSession(Base):
    """
    Stock Take Session model
    
    Represents a stock take session where multiple users can count items.
    Only one active session per branch at a time.
    """
    __tablename__ = "stock_take_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    session_code = Column(String(10), unique=True, nullable=False)  # e.g., "ST-MAR25A"
    status = Column(String(50), nullable=False, default='DRAFT')  # DRAFT, ACTIVE, PAUSED, COMPLETED, CANCELLED
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    allowed_counters = Column(ARRAY(UUID(as_uuid=True)), default=[], nullable=False)  # Array of user IDs
    assigned_shelves = Column(JSONB, default={}, nullable=False)  # Map of user_id -> shelf_locations
    is_multi_user = Column(Boolean, default=True, nullable=False)
    notes = Column(Text)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    counts = relationship("StockTakeCount", back_populates="session", cascade="all, delete-orphan")
    locks = relationship("StockTakeCounterLock", back_populates="session", cascade="all, delete-orphan")
    adjustments = relationship("StockTakeAdjustment", back_populates="session", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'COMPLETED', 'CANCELLED')",
            name="valid_status"
        ),
    )


class StockTakeCount(Base):
    """
    Stock Take Count model
    
    Stores individual counts entered by counters.
    Multiple counters can count the same item.
    """
    __tablename__ = "stock_take_counts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("stock_take_sessions.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    counted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    shelf_location = Column(String(100), nullable=True)
    counted_quantity = Column(Integer, nullable=False)  # In base units
    system_quantity = Column(Integer, nullable=False)  # System stock at time of count (base units)
    variance = Column(Integer, nullable=False)  # counted_quantity - system_quantity
    notes = Column(Text)
    counted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("StockTakeSession", back_populates="counts")
    item = relationship("Item")
    counter = relationship("User", foreign_keys=[counted_by])

    __table_args__ = (
        {"comment": "Individual counts entered by counters. Multiple counters can count same item."},
    )


class StockTakeCounterLock(Base):
    """
    Stock Take Counter Lock model
    
    Prevents duplicate counting by locking items during counting.
    Auto-expires after 5 minutes.
    """
    __tablename__ = "stock_take_counter_locks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("stock_take_sessions.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    counter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    locked_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)

    # Relationships
    session = relationship("StockTakeSession", back_populates="locks")
    item = relationship("Item")
    counter = relationship("User", foreign_keys=[counter_id])

    __table_args__ = (
        {"comment": "Locks items during counting to prevent duplicate counting. Auto-expires after 5 minutes."},
    )


class StockTakeAdjustment(Base):
    """
    Stock Take Adjustment model
    
    Final adjustments applied to inventory after stock take completion.
    """
    __tablename__ = "stock_take_adjustments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("stock_take_sessions.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    adjustment_quantity = Column(Integer, nullable=False)  # Can be positive or negative (base units)
    reason = Column(Text)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("StockTakeSession", back_populates="adjustments")
    item = relationship("Item")
    approver = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        {"comment": "Final adjustments applied to inventory after stock take completion."},
    )
