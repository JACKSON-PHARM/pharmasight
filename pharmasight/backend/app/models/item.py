"""
Item and Unit models
"""
from sqlalchemy import Column, String, Boolean, Numeric, ForeignKey
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
    generic_name = Column(String(255))
    sku = Column(String(100))
    barcode = Column(String(100))
    category = Column(String(100))
    base_unit = Column(String(50), nullable=False)  # tablet, ml, gram, etc.
    default_cost = Column(Numeric(20, 4), default=0)
    # VAT Classification (Kenya Pharmacy Context)
    # Most medicines are zero-rated (0%), some items/services are standard-rated (16%)
    is_vatable = Column(Boolean, default=True)
    vat_rate = Column(Numeric(5, 2), default=0)  # 0 for zero-rated, 16 for standard-rated
    vat_code = Column(String(50))  # ZERO_RATED | STANDARD | EXEMPT
    price_includes_vat = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="items")
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
    """Item-specific pricing rules"""
    __tablename__ = "item_pricing"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, unique=True)
    markup_percent = Column(Numeric(10, 2))
    min_margin_percent = Column(Numeric(10, 2))
    rounding_rule = Column(String(50))  # nearest_1, nearest_5, nearest_10
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

