"""Schemas for company-level pricing settings (defaults, margin behavior, discount rules)."""
from decimal import Decimal
from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


BELOW_MARGIN_BEHAVIORS = ("allow_warn", "require_override", "block")


class PricingSettingsBase(BaseModel):
    """Pricing settings base: defaults and behavior."""
    default_min_margin_retail_pct: Optional[float] = Field(None, ge=0, le=100)
    default_min_margin_wholesale_pct: Optional[float] = Field(None, ge=0, le=100)
    below_margin_behavior: str = Field(default="allow_warn", description="allow_warn | require_override | block")
    allow_line_discounts: bool = Field(default=True)
    max_discount_pct_without_override: Optional[float] = Field(None, ge=0, le=100)
    promotions_can_go_below_margin: bool = Field(default=True)


class PricingSettingsUpdate(BaseModel):
    """Update pricing settings (all fields optional for PATCH)."""
    default_min_margin_retail_pct: Optional[float] = Field(None, ge=0, le=100)
    default_min_margin_wholesale_pct: Optional[float] = Field(None, ge=0, le=100)
    below_margin_behavior: Optional[str] = Field(None, description="allow_warn | require_override | block")
    allow_line_discounts: Optional[bool] = None
    max_discount_pct_without_override: Optional[float] = Field(None, ge=0, le=100)
    promotions_can_go_below_margin: Optional[bool] = None


class PricingSettingsResponse(PricingSettingsBase):
    """Pricing settings response."""
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
