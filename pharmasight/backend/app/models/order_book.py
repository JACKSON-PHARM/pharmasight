"""
Daily Order Book models
"""
from sqlalchemy import Column, String, Numeric, Text, Integer, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class DailyOrderBook(Base):
    """
    Daily Order Book Entry
    
    Tracks items that need to be reordered at branch level.
    Can be auto-generated from stock thresholds or manually added.
    Items are unique per (branch, item, entry_date).
    """
    __tablename__ = "daily_order_book"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    entry_date = Column(Date, nullable=False, server_default=func.current_date())  # Unique per (branch, item, entry_date)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    quantity_needed = Column(Numeric(20, 4), nullable=False)  # In base units
    unit_name = Column(String(50), nullable=False)
    reason = Column(String(100), nullable=False)  # AUTO_THRESHOLD, MANUAL_SALE, MANUAL_QUOTATION, MANUAL_ADD
    source_reference_type = Column(String(50), nullable=True)  # sales_invoice, quotation
    source_reference_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    priority = Column(Integer, default=5)  # 1-10, higher = more urgent
    status = Column(String(50), default="PENDING")  # PENDING, ORDERED, CANCELLED
    purchase_order_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    item = relationship("Item")
    supplier = relationship("Supplier")
    purchase_order = relationship("PurchaseOrder")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        {"comment": "Daily order book entries at branch level. Tracks items needing reordering."},
    )


class OrderBookHistory(Base):
    """
    Order Book History
    
    Archive of completed or cancelled order book entries.
    """
    __tablename__ = "order_book_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    quantity_needed = Column(Numeric(20, 4), nullable=False)
    unit_name = Column(String(50), nullable=False)
    reason = Column(String(100), nullable=False)
    source_reference_type = Column(String(50), nullable=True)
    source_reference_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    priority = Column(Integer, default=5)
    status = Column(String(50), nullable=False)  # ORDERED, CANCELLED
    purchase_order_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)  # Original creation time
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)  # When status changed
    archived_at = Column(TIMESTAMP(timezone=True), server_default=func.now())  # When moved to history

    # Relationships
    company = relationship("Company")
    branch = relationship("Branch")
    item = relationship("Item")
    supplier = relationship("Supplier")
    purchase_order = relationship("PurchaseOrder")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        {"comment": "Historical archive of order book entries that were ordered or cancelled."},
    )
