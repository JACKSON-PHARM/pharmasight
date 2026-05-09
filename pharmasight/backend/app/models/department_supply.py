"""
Same-branch department supply workflow (pharmacy stock -> department mini-store).
Analogous to branch_orders / branch_transfers / branch_receipts.
"""
import uuid
from sqlalchemy import Column, String, Numeric, ForeignKey, UniqueConstraint, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP, Date

from app.database import Base


class DepartmentSupplyOrder(Base):
    __tablename__ = "department_supply_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    department_store_id = Column(UUID(as_uuid=True), ForeignKey("department_stores.id", ondelete="CASCADE"), nullable=False)
    order_number = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    lines = relationship("DepartmentSupplyOrderLine", back_populates="order", cascade="all, delete-orphan")
    transfers = relationship("DepartmentSupplyTransfer", back_populates="order")


class DepartmentSupplyOrderLine(Base):
    __tablename__ = "department_supply_order_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_supply_order_id = Column(
        UUID(as_uuid=True), ForeignKey("department_supply_orders.id", ondelete="CASCADE"), nullable=False
    )
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    fulfilled_qty = Column(Numeric(20, 4), nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    order = relationship("DepartmentSupplyOrder", back_populates="lines")


class DepartmentSupplyTransfer(Base):
    __tablename__ = "department_supply_transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    department_store_id = Column(UUID(as_uuid=True), ForeignKey("department_stores.id", ondelete="CASCADE"), nullable=False)
    department_supply_order_id = Column(UUID(as_uuid=True), ForeignKey("department_supply_orders.id", ondelete="SET NULL"), nullable=True)
    transfer_number = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")
    request_audit = Column(JSONB, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    lines = relationship("DepartmentSupplyTransferLine", back_populates="transfer", cascade="all, delete-orphan")
    order = relationship("DepartmentSupplyOrder", back_populates="transfers")
    receipt = relationship("DepartmentSupplyReceipt", back_populates="transfer", uselist=False, cascade="all, delete-orphan")


class DepartmentSupplyTransferLine(Base):
    __tablename__ = "department_supply_transfer_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_supply_transfer_id = Column(
        UUID(as_uuid=True), ForeignKey("department_supply_transfers.id", ondelete="CASCADE"), nullable=False
    )
    department_supply_order_line_id = Column(
        UUID(as_uuid=True), ForeignKey("department_supply_order_lines.id", ondelete="SET NULL"), nullable=True
    )
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(String(200), nullable=True)
    expiry_date = Column(Date, nullable=True)
    unit_name = Column(String(50), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_cost = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    transfer = relationship("DepartmentSupplyTransfer", back_populates="lines")


class DepartmentSupplyReceipt(Base):
    __tablename__ = "department_supply_receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    department_store_id = Column(UUID(as_uuid=True), ForeignKey("department_stores.id", ondelete="CASCADE"), nullable=False)
    department_supply_transfer_id = Column(
        UUID(as_uuid=True), ForeignKey("department_supply_transfers.id", ondelete="CASCADE"), nullable=False
    )
    receipt_number = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="PENDING")
    received_at = Column(TIMESTAMP(timezone=True), nullable=True)
    received_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    transfer = relationship("DepartmentSupplyTransfer", back_populates="receipt")
    lines = relationship("DepartmentSupplyReceiptLine", back_populates="receipt", cascade="all, delete-orphan")


class DepartmentSupplyReceiptLine(Base):
    __tablename__ = "department_supply_receipt_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_supply_receipt_id = Column(
        UUID(as_uuid=True), ForeignKey("department_supply_receipts.id", ondelete="CASCADE"), nullable=False
    )
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(String(200), nullable=True)
    expiry_date = Column(Date, nullable=True)
    quantity = Column(Numeric(20, 4), nullable=False)
    unit_cost = Column(Numeric(20, 4), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    receipt = relationship("DepartmentSupplyReceipt", back_populates="lines")
