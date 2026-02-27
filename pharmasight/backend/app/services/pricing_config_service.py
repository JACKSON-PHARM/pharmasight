"""
Pricing config service: load global pricing settings and item-level overrides,
and validate line price against margin/floor/discount rules.

Used by sales flow (Phase 2) and settings UI (Phase 3). Phase 1: no callers yet;
existing margin checks remain in PricingService + sales API.
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Item, PricingSettings
from app.services.pricing_service import PricingService


# Behavior when selling below minimum margin (from pricing_settings.below_margin_behavior)
ALLOW_WARN = "allow_warn"
REQUIRE_OVERRIDE = "require_override"
BLOCK = "block"


def get_global_pricing_config(db: Session, company_id: UUID) -> Dict[str, Any]:
    """
    Load company-level pricing settings. Returns a dict with safe defaults
    when no row exists (e.g. before migration or for new companies).
    """
    row = db.query(PricingSettings).filter(
        PricingSettings.company_id == company_id
    ).first()
    if not row:
        return {
            "default_min_margin_retail_pct": None,
            "default_min_margin_wholesale_pct": None,
            "below_margin_behavior": ALLOW_WARN,
            "allow_line_discounts": True,
            "max_discount_pct_without_override": None,
            "promotions_can_go_below_margin": True,
        }
    return {
        "default_min_margin_retail_pct": float(row.default_min_margin_retail_pct) if row.default_min_margin_retail_pct is not None else None,
        "default_min_margin_wholesale_pct": float(row.default_min_margin_wholesale_pct) if row.default_min_margin_wholesale_pct is not None else None,
        "below_margin_behavior": (row.below_margin_behavior or ALLOW_WARN).strip(),
        "allow_line_discounts": bool(row.allow_line_discounts),
        "max_discount_pct_without_override": float(row.max_discount_pct_without_override) if row.max_discount_pct_without_override is not None else None,
        "promotions_can_go_below_margin": bool(row.promotions_can_go_below_margin),
    }


def get_effective_item_overrides(
    db: Session,
    item_id: UUID,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Item-level overrides: floor price and promo (if within date range).
    as_of: date to check promo window (default today).
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return {
            "floor_price_retail": None,
            "promo_price_retail": None,
            "promo_active": False,
            "promo_start_date": None,
            "promo_end_date": None,
        }
    check_date = as_of or date.today()
    promo_start = item.promo_start_date
    promo_end = item.promo_end_date
    promo_active = (
        item.promo_price_retail is not None
        and promo_start is not None
        and promo_end is not None
        and promo_start <= check_date <= promo_end
    )
    return {
        "floor_price_retail": float(item.floor_price_retail) if item.floor_price_retail is not None else None,
        "promo_price_retail": float(item.promo_price_retail) if item.promo_price_retail is not None else None,
        "promo_active": promo_active,
        "promo_start_date": item.promo_start_date,
        "promo_end_date": item.promo_end_date,
    }


def validate_line_price(
    db: Session,
    company_id: UUID,
    item_id: UUID,
    unit_price_exclusive: Decimal,
    cost_per_sale_unit: Decimal,
    user_has_sell_below_margin: bool,
    *,
    is_promo_price: bool = False,
    line_discount_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Validate a line's selling price against margin, floor, and discount rules.
    Returns dict: allowed (bool), status (str), message (str), effective_min_margin (Decimal).

    - allowed: True if the sale can proceed (possibly with warning or override).
    - status: "ok" | "warn" | "require_override" | "block".
    - When status is "block", allowed is False and caller must reject.
    - When status is "require_override", allowed is True only if user_has_sell_below_margin.
    - When status is "warn", allowed is True; UI can show warning.
    - When status is "ok", no issue.

    Does not change existing behavior: uses existing get_min_margin_percent for margin;
    applies floor and config behavior only when settings exist.
    """
    config = get_global_pricing_config(db, company_id)
    overrides = get_effective_item_overrides(db, item_id)
    min_margin = PricingService.get_min_margin_percent(db, item_id, company_id)

    # Optional: use company-level default min margin from pricing_settings when set
    # (today we keep using tier/item logic via get_min_margin_percent; no override here)

    effective_min_margin = min_margin
    messages = []

    # 1) Floor price (item-level)
    floor = overrides.get("floor_price_retail")
    if floor is not None and unit_price_exclusive < Decimal(str(floor)):
        return {
            "allowed": False,
            "status": "block",
            "message": f"Price {unit_price_exclusive} is below item floor price {floor}.",
            "effective_min_margin": effective_min_margin,
            "messages": ["Below floor price"],
        }

    # 2) Margin check (existing logic: min_margin from tier/item)
    if cost_per_sale_unit <= 0:
        return {
            "allowed": True,
            "status": "ok",
            "message": "",
            "effective_min_margin": effective_min_margin,
            "messages": [],
        }
    margin_pct = (unit_price_exclusive - cost_per_sale_unit) / cost_per_sale_unit * Decimal("100")
    below_margin = margin_pct < effective_min_margin
    behavior = config.get("below_margin_behavior") or ALLOW_WARN

    if is_promo_price and config.get("promotions_can_go_below_margin"):
        # Promo allowed to go below margin; treat as ok for margin purpose
        below_margin = False

    if below_margin:
        if user_has_sell_below_margin:
            return {
                "allowed": True,
                "status": "warn",
                "message": f"Below minimum margin ({float(effective_min_margin):.1f}%); override applied.",
                "effective_min_margin": effective_min_margin,
                "messages": ["Sold below margin with permission"],
            }
        if behavior == BLOCK:
            return {
                "allowed": False,
                "status": "block",
                "message": f"Price below minimum margin ({float(effective_min_margin):.1f}%). Not allowed.",
                "effective_min_margin": effective_min_margin,
                "messages": ["Below margin; blocking"],
            }
        if behavior == REQUIRE_OVERRIDE:
            return {
                "allowed": False,
                "status": "require_override",
                "message": f"Price below minimum margin ({float(effective_min_margin):.1f}%). Manager override (PIN) required.",
                "effective_min_margin": effective_min_margin,
                "messages": ["Manager override required"],
            }
        # allow_warn
        return {
            "allowed": True,
            "status": "warn",
            "message": f"Price below recommended margin ({float(effective_min_margin):.1f}%).",
            "effective_min_margin": effective_min_margin,
            "messages": ["Below margin; warning only"],
        }

    # 3) Line discount cap (when configured)
    max_discount = config.get("max_discount_pct_without_override")
    if (
        not config.get("allow_line_discounts")
        and line_discount_pct is not None
        and line_discount_pct > 0
    ):
        return {
            "allowed": False,
            "status": "block",
            "message": "Line discounts are not allowed.",
            "effective_min_margin": effective_min_margin,
            "messages": ["Line discounts disabled"],
        }
    if (
        max_discount is not None
        and line_discount_pct is not None
        and line_discount_pct > max_discount
        and not user_has_sell_below_margin
    ):
        return {
            "allowed": False,
            "status": "require_override",
            "message": f"Discount {line_discount_pct}% exceeds max {max_discount}% without manager override.",
            "effective_min_margin": effective_min_margin,
            "messages": ["Discount exceeds limit"],
        }

    return {
        "allowed": True,
        "status": "ok",
        "message": "",
        "effective_min_margin": effective_min_margin,
        "messages": [],
    }
