"""
Inventory Ledger model - Single source of truth for stock
"""
from sqlalchemy import Column, String, Integer, Numeric, Date, ForeignKey, CheckConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class InventoryLedger(Base):
    """
    Inventory Ledger - Append-only record of all stock movements
    
    This is the SINGLE SOURCE OF TRUTH for inventory.
    Never update or delete. Always append.
    """
    __tablename__ = "inventory_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    batch_number = Column(String(200))
    expiry_date = Column(Date)
    transaction_type = Column(String(50), nullable=False)  # PURCHASE, SALE, ADJUSTMENT, TRANSFER, OPENING_BALANCE
    reference_type = Column(String(50))  # supplier_invoice (was purchase_invoice), sales_invoice, adjustment, grn
    reference_id = Column(UUID(as_uuid=True))
    quantity_delta = Column(Numeric(20, 4), nullable=False)  # Positive = add, Negative = remove (base units; fractional for retail e.g. -0.2)
    unit_cost = Column(Numeric(20, 4), nullable=False)  # Cost per base unit
    total_cost = Column(Numeric(20, 4), nullable=False)  # quantity_delta * unit_cost
    created_by = Column(UUID(as_uuid=True), nullable=False)  # User ID
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    notes = Column(String(2000), nullable=True)  # Optional comment/details (e.g. source, reason for adjustment)

    # Enhanced batch tracking fields
    batch_cost = Column(Numeric(20, 4), nullable=True)  # Cost for this specific batch (for FIFO/LIFO)
    remaining_quantity = Column(Integer, nullable=True)  # Remaining quantity in this batch (for tracking)
    is_batch_tracked = Column(Boolean, default=True)  # Whether this entry is batch-tracked
    parent_batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_ledger.id"), nullable=True)  # For batch splits
    split_sequence = Column(Integer, default=0)  # 0=main batch, 1,2,3... for splits within same transaction

    # Constraints
    __table_args__ = (
        CheckConstraint("quantity_delta != 0", name="quantity_delta_not_zero"),
        {"comment": "Append-only inventory ledger. Never update or delete. All stock = SUM(quantity_delta) in base units."},
    )

    # Relationships
    item = relationship("Item")
    branch = relationship("Branch")
    company = relationship("Company")
    parent_batch = relationship("InventoryLedger", remote_side=[id], foreign_keys=[parent_batch_id])

