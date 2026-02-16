"""
Snapshot models for search performance.
Precomputed inventory_balances, item_branch_purchase_snapshot, item_branch_search_snapshot.
Updated in same transaction as ledger writes.
"""
import uuid
from sqlalchemy import Column, Date, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from app.database import Base


class InventoryBalance(Base):
    """Precomputed current stock per (item_id, branch_id)."""
    __tablename__ = "inventory_balances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    current_stock = Column(Numeric(20, 4), nullable=False, default=0)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = ({"comment": "Precomputed current stock. Updated in same transaction as ledger writes."},)
    __mapper_args__ = {"eager_defaults": True}


class ItemBranchPurchaseSnapshot(Base):
    """Precomputed last purchase per (item_id, branch_id)."""
    __tablename__ = "item_branch_purchase_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    last_purchase_price = Column(Numeric(20, 4), nullable=True)
    last_purchase_date = Column(TIMESTAMP(timezone=True), nullable=True)
    last_supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = ({"comment": "Precomputed last purchase. Updated when PURCHASE ledger entries are written."},)
    __mapper_args__ = {"eager_defaults": True}


class ItemBranchSearchSnapshot(Base):
    """Precomputed last order/sale/order_book dates per (item_id, branch_id)."""
    __tablename__ = "item_branch_search_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    last_order_date = Column(Date, nullable=True)
    last_sale_date = Column(Date, nullable=True)
    last_order_book_date = Column(TIMESTAMP(timezone=True), nullable=True)
    last_quotation_date = Column(Date, nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("item_id", "branch_id", name="uq_item_branch_search_item_branch"),
        {"comment": "Precomputed last order/sale/order_book. Updated from PO, Sales, OrderBook writes."},
    )
    __mapper_args__ = {"eager_defaults": True}
