"""
Snapshot models for search performance.
Precomputed inventory_balances, item_branch_purchase_snapshot, item_branch_search_snapshot.
Updated in same transaction as ledger writes.
"""
import uuid
from sqlalchemy import Boolean, Column, Date, Integer, Numeric, String, ForeignKey, UniqueConstraint
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


class ItemBranchSnapshot(Base):
    """
    Unified item search snapshot: one row per (item_id, branch_id). Consolidates
    inventory state, pricing inputs, effective_selling_price, and activity metadata.
    Updated in same transaction as ledger and legacy snapshot writes.
    """
    __tablename__ = "item_branch_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    pack_size = Column(Integer, nullable=False, default=1)
    base_unit = Column(String(50), nullable=True)
    sku = Column(String(100), nullable=True)
    vat_rate = Column(Numeric(5, 2), nullable=True)
    vat_category = Column(String(20), nullable=True)
    current_stock = Column(Numeric(20, 4), nullable=False, default=0)
    average_cost = Column(Numeric(20, 4), nullable=True)
    last_purchase_price = Column(Numeric(20, 4), nullable=True)
    selling_price = Column(Numeric(20, 4), nullable=True)
    margin_percent = Column(Numeric(10, 2), nullable=True)
    next_expiry_date = Column(Date, nullable=True)
    search_text = Column(String, nullable=False, default="")
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    # From item_branch_purchase_snapshot
    last_purchase_date = Column(TIMESTAMP(timezone=True), nullable=True)
    last_supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    # From item_branch_search_snapshot
    last_order_date = Column(Date, nullable=True)
    last_sale_date = Column(Date, nullable=True)
    last_order_book_date = Column(TIMESTAMP(timezone=True), nullable=True)
    last_quotation_date = Column(Date, nullable=True)
    # Pricing inputs (set by refresh)
    default_item_margin = Column(Numeric(10, 2), nullable=True)
    branch_margin = Column(Numeric(10, 2), nullable=True)
    company_margin = Column(Numeric(10, 2), nullable=True)
    floor_price = Column(Numeric(20, 4), nullable=True)
    minimum_margin = Column(Numeric(10, 2), nullable=True)
    promotion_price = Column(Numeric(20, 4), nullable=True)
    promotion_start = Column(TIMESTAMP(timezone=True), nullable=True)
    promotion_end = Column(TIMESTAMP(timezone=True), nullable=True)
    promotion_active = Column(Boolean, default=False, nullable=True)
    # Computed selling price and source
    effective_selling_price = Column(Numeric(20, 4), nullable=True)
    price_source = Column(String(50), nullable=True)
    # Denormalized from items so search can avoid Item join (POS <100ms at 1.5M rows)
    retail_unit = Column(String(50), nullable=True, default="piece")
    supplier_unit = Column(String(50), nullable=True, default="piece")
    wholesale_unit = Column(String(50), nullable=True, default="piece")
    wholesale_units_per_supplier = Column(Numeric(20, 4), nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("item_id", "branch_id", name="item_branch_snapshot_item_id_branch_id_key"),
        {"comment": "Unified item search snapshot. Single-SELECT when branch_id provided."},
    )
    __mapper_args__ = {"eager_defaults": True}


class SnapshotRefreshQueue(Base):
    """
    Deduplicated queue for bulk POS snapshot refresh. Processed in background.
    item_id NULL = refresh all items in branch; otherwise refresh that (item_id, branch_id).
    claimed_at: set when worker starts branch-wide job so chunked commits can release lock.
    reason: optional debug label (e.g. company_margin_change, promotion_update).
    """
    __tablename__ = "snapshot_refresh_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    claimed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reason = Column(String(255), nullable=True)
