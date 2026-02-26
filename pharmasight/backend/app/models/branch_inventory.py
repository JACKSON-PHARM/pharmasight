"""
Branch Inventory models - Branch orders, transfers, receipts.
Reuses: inventory_ledger (TRANSFER), SnapshotService, InventoryService.
"""
from sqlalchemy import Column, String, Numeric, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class BranchOrder(Base):
    """Order from ordering branch to supplying branch. Locked after batching."""
    __tablename__ = "branch_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    ordering_branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    supplying_branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    order_number = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")  # DRAFT, BATCHED
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    lines = relationship("BranchOrderLine", back_populates="order", cascade="all, delete-orphan")
    transfers = relationship("BranchTransfer", back_populates="order", foreign_keys="BranchTransfer.branch_order_id")
    ordering_branch = relationship("Branch", foreign_keys=[ordering_branch_id])
    supplying_branch = relationship("Branch", foreign_keys=[supplying_branch_id])


class BranchOrderLine(Base):
    """Line item on a branch order; fulfilled_qty updated by transfer lines."""
    __tablename__ = "branch_order_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_order_id = Column(UUID(as_uuid=True), ForeignKey("branch_orders.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    fulfilled_qty = Column(Numeric(20, 4), nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    order = relationship("BranchOrder", back_populates="lines")
    item = relationship("Item")


class BranchTransfer(Base):
    """Transfer of stock from supplying to receiving branch; FEFO deduction at completion."""
    __tablename__ = "branch_transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    supplying_branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    receiving_branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    branch_order_id = Column(UUID(as_uuid=True), ForeignKey("branch_orders.id", ondelete="SET NULL"), nullable=True)
    transfer_number = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")  # DRAFT, COMPLETED
    request_audit = Column(JSONB, nullable=True)  # Snapshot of requested (item_id, quantity_base) before FEFO replacement
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    lines = relationship("BranchTransferLine", back_populates="transfer", cascade="all, delete-orphan")
    order = relationship("BranchOrder", back_populates="transfers", foreign_keys=[branch_order_id])
    supplying_branch = relationship("Branch", foreign_keys=[supplying_branch_id])
    receiving_branch = relationship("Branch", foreign_keys=[receiving_branch_id])
    receipt = relationship("BranchReceipt", back_populates="transfer", uselist=False, cascade="all, delete-orphan")


class BranchTransferLine(Base):
    """Batch-level transfer line; unit_cost from inventory batch at transfer."""
    __tablename__ = "branch_transfer_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_transfer_id = Column(UUID(as_uuid=True), ForeignKey("branch_transfers.id", ondelete="CASCADE"), nullable=False)
    branch_order_line_id = Column(UUID(as_uuid=True), ForeignKey("branch_order_lines.id", ondelete="SET NULL"), nullable=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(String(200), nullable=True)
    expiry_date = Column(Date, nullable=True)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_cost = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    transfer = relationship("BranchTransfer", back_populates="lines")
    item = relationship("Item")
    order_line = relationship("BranchOrderLine", foreign_keys=[branch_order_line_id])


class BranchReceipt(Base):
    """Receipt confirmation for a branch transfer; one receipt per transfer."""
    __tablename__ = "branch_receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    receiving_branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    branch_transfer_id = Column(UUID(as_uuid=True), ForeignKey("branch_transfers.id", ondelete="CASCADE"), nullable=False)
    receipt_number = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="PENDING")  # PENDING, RECEIVED
    received_at = Column(TIMESTAMP(timezone=True), nullable=True)
    received_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    transfer = relationship("BranchTransfer", back_populates="receipt")
    lines = relationship("BranchReceiptLine", back_populates="receipt", cascade="all, delete-orphan")
    receiving_branch = relationship("Branch", foreign_keys=[receiving_branch_id])


class BranchReceiptLine(Base):
    """Batch-level receipt line; batch_number, expiry_date, unit_cost preserved from transfer."""
    __tablename__ = "branch_receipt_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_receipt_id = Column(UUID(as_uuid=True), ForeignKey("branch_receipts.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(String(200), nullable=True)
    expiry_date = Column(Date, nullable=True)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_cost = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    receipt = relationship("BranchReceipt", back_populates="lines")
    item = relationship("Item")
