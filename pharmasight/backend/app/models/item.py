"""
Item and Unit models
"""
from sqlalchemy import Column, String, Boolean, Numeric, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class Item(Base):
    """Item (SKU) model"""
    __tablename__ = "items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(255))  # Item description (was generic_name)
    sku = Column(String(100))  # Item code
    barcode = Column(String(100))
    category = Column(String(100))
    base_unit = Column(String(50), nullable=False)  # = wholesale_unit (reference unit; stock in base = wholesale qty)
    # VAT: vat_category + vat_rate only
    vat_category = Column(String(20), default="ZERO_RATED")  # ZERO_RATED | STANDARD_RATED
    vat_rate = Column(Numeric(5, 2), default=0)  # 0 for zero-rated, 16 for standard-rated
    is_active = Column(Boolean, default=True)
    # 3-tier units: supplier / wholesale / retail + conversion rates
    supplier_unit = Column(String(50), default="piece")
    wholesale_unit = Column(String(50), default="piece")  # Base/reference unit
    retail_unit = Column(String(50), default="piece")
    pack_size = Column(Integer, nullable=False, default=1)  # Wholesale-to-retail: 1 wholesale = pack_size retail
    wholesale_units_per_supplier = Column(Numeric(20, 4), nullable=False, default=1)  # Wholesale-to-supplier: 1 supplier = N wholesale
    can_break_bulk = Column(Boolean, nullable=False, default=True)
    # Tracking flags
    track_expiry = Column(Boolean, default=False)  # Whether item requires expiry date tracking
    is_controlled = Column(Boolean, default=False)  # Whether item is a controlled substance
    is_cold_chain = Column(Boolean, default=False)  # Whether item requires cold chain storage
    # Default parameters — used only when item has no inventory_ledger / purchase history
    default_cost_per_base = Column(Numeric(20, 4), nullable=True)  # Cost per base unit fallback
    default_supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="items")
    default_supplier = relationship("Supplier", foreign_keys=[default_supplier_id])
    units = relationship("ItemUnit", back_populates="item", cascade="all, delete-orphan")
    pricing = relationship("ItemPricing", back_populates="item", uselist=False, cascade="all, delete-orphan")


class ItemUnit(Base):
    """Item unit conversion (breaking bulk)"""
    __tablename__ = "item_units"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    unit_name = Column(String(50), nullable=False)  # box, carton, tablet, etc.
    multiplier_to_base = Column(Numeric(20, 4), nullable=False)  # e.g., 1 box = 100 tablets
    is_default = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    item = relationship("Item", back_populates="units")

    __table_args__ = (
        {"comment": "Breaking bulk configuration. Defines how packs convert to base units."},
    )


class ItemPricing(Base):
    """Item-specific pricing rules with 3-tier pricing support"""
    __tablename__ = "item_pricing"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, unique=True)
    markup_percent = Column(Numeric(10, 2))
    min_margin_percent = Column(Numeric(10, 2))
    rounding_rule = Column(String(50))  # nearest_1, nearest_5, nearest_10
    
    # NOTE: 3-tier pricing fields (supplier_unit, wholesale_unit, retail_unit, etc.) 
    # are now on the items table, NOT item_pricing table.
    # This table only stores markup_percent, min_margin_percent, and rounding_rule.
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    item = relationship("Item", back_populates="pricing")


class CompanyPricingDefault(Base):
    """Company-wide pricing defaults"""
    __tablename__ = "company_pricing_defaults"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)
    default_markup_percent = Column(Numeric(10, 2), default=30.00)
    rounding_rule = Column(String(50), default="nearest_1")
    min_margin_percent = Column(Numeric(10, 2), default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

