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

from app.models import Item, PricingSettings, BranchSetting
from app.services.pricing_service import PricingService
from app.services.item_units_helper import get_unit_multiplier_from_item


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
            "cost_outlier_threshold_pct": None,
        }
    return {
        "default_min_margin_retail_pct": float(row.default_min_margin_retail_pct) if row.default_min_margin_retail_pct is not None else None,
        "default_min_margin_wholesale_pct": float(row.default_min_margin_wholesale_pct) if row.default_min_margin_wholesale_pct is not None else None,
        "below_margin_behavior": (row.below_margin_behavior or ALLOW_WARN).strip(),
        "allow_line_discounts": bool(row.allow_line_discounts),
        "max_discount_pct_without_override": float(row.max_discount_pct_without_override) if row.max_discount_pct_without_override is not None else None,
        "promotions_can_go_below_margin": bool(row.promotions_can_go_below_margin),
        "cost_outlier_threshold_pct": float(row.cost_outlier_threshold_pct) if row.cost_outlier_threshold_pct is not None else None,
    }


def get_cost_outlier_threshold_pct(
    db: Session, company_id: UUID, branch_id: Optional[UUID] = None
) -> Decimal:
    """
    Return configured cost outlier threshold (%) or a safe default.
    Default is 200%% if not set (cost can deviate up to 2x before override is required).
    """
    # 1) Branch-level override when present
    if branch_id is not None:
        row = (
            db.query(BranchSetting.cost_outlier_threshold_pct)
            .filter(BranchSetting.branch_id == branch_id)
            .first()
        )
        if row and row[0] is not None:
            try:
                return Decimal(str(row[0]))
            except Exception:
                pass

    # 2) Company-level default from pricing_settings
    config = get_global_pricing_config(db, company_id)
    raw = config.get("cost_outlier_threshold_pct")
    if raw is not None:
        try:
            return Decimal(str(raw))
        except Exception:
            pass
    # 3) Fallback application default
    return Decimal("200")


def is_cost_outlier_vs_weighted_average(
    db: Session,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
    unit_cost_per_base: Decimal,
) -> Dict[str, Any]:
    """
    Compare a new unit cost (per base unit) against the branch weighted average cost.
    Returns dict: { is_outlier, baseline_cost, deviation_pct, threshold_pct }.
    When baseline is missing or zero, always returns is_outlier=False.
    """
    if unit_cost_per_base is None or unit_cost_per_base <= 0:
        return {
            "is_outlier": False,
            "baseline_cost": None,
            "deviation_pct": None,
            "threshold_pct": None,
        }

    # Lazy import to avoid circular dependency at module import time
    from app.services.canonical_pricing import CanonicalPricingService

    baseline = CanonicalPricingService.get_weighted_average_cost(
        db, item_id, branch_id, company_id
    )
    if baseline is None or baseline <= 0:
        return {
            "is_outlier": False,
            "baseline_cost": None,
            "deviation_pct": None,
            "threshold_pct": None,
        }
    threshold = get_cost_outlier_threshold_pct(db, company_id, branch_id)
    deviation_pct = (abs(unit_cost_per_base - baseline) / baseline) * Decimal("100")
    return {
        "is_outlier": deviation_pct > threshold,
        "baseline_cost": baseline,
        "deviation_pct": deviation_pct,
        "threshold_pct": threshold,
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


def is_line_price_at_promo(
    db: Session,
    item_id: UUID,
    unit_name: str,
    unit_price_exclusive: Decimal,
) -> bool:
    """
    True if the line is effectively selling at the item's active promo price.
    Handles unit conversion: promo_price_retail is per retail; unit_price may be in any tier.
    """
    overrides = get_effective_item_overrides(db, item_id)
    if not overrides.get("promo_active") or overrides.get("promo_price_retail") is None:
        return False
    promo_retail = Decimal(str(overrides["promo_price_retail"]))
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return False
    mult = get_unit_multiplier_from_item(item, unit_name or "")
    if mult is None or mult <= 0:
        return False
    # mult = units of base (retail) per sale unit. Price per retail = unit_price / mult.
    # (retail: mult=1; wholesale: mult=pack_size, so price/retail = price/mult)
    price_per_retail = unit_price_exclusive / mult
    tolerance = Decimal("0.01")
    return abs(price_per_retail - promo_retail) <= tolerance


def validate_line_price(
    db: Session,
    company_id: UUID,
    item_id: UUID,
    unit_price_exclusive: Decimal,
    cost_per_sale_unit: Decimal,
    user_has_sell_below_margin: bool,
    *,
    branch_id: Optional[UUID] = None,
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
    effective_min_margin = min_margin
    messages = []

    # 1) Floor price (item-level) — hard block when below
    floor = overrides.get("floor_price_retail")
    if floor is not None and unit_price_exclusive < Decimal(str(floor)):
        return {
            "allowed": False,
            "status": "block",
            "message": f"Price {unit_price_exclusive} is below item floor price {floor}.",
            "effective_min_margin": effective_min_margin,
            "messages": ["Below floor price"],
        }

    # 1b) Floor overrides margin — when item has floor_price_retail set and price >= floor,
    # the floor IS the pricing rule for that item (e.g. constant 200 bob); skip margin check.
    floor_overrides_margin = floor is not None and unit_price_exclusive >= Decimal(str(floor))

    # 1c) Branch-level minimum margin override (tightens, never relaxes)
    if branch_id is not None:
        row = (
            db.query(BranchSetting.min_margin_retail_pct_override)
            .filter(BranchSetting.branch_id == branch_id)
            .first()
        )
        if row and row[0] is not None:
            try:
                branch_min = Decimal(str(row[0]))
                if branch_min > effective_min_margin:
                    effective_min_margin = branch_min
            except Exception:
                pass

    # 2) Margin check (existing logic: min_margin from tier/item) — skipped when floor overrides
    if cost_per_sale_unit <= 0:
        return {
            "allowed": True,
            "status": "ok",
            "message": "",
            "effective_min_margin": effective_min_margin,
            "messages": [],
        }
    margin_pct = (unit_price_exclusive - cost_per_sale_unit) / cost_per_sale_unit * Decimal("100")
    below_margin = margin_pct < effective_min_margin and not floor_overrides_margin
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


def check_stock_adjustment_requires_confirmation(
    db: Session,
    item_id: UUID,
    company_id: UUID,
    unit_cost_per_base: Decimal,
) -> Dict[str, Any]:
    """
    For stock additions (manual adjustment or supplier invoice): determine if the user
    must re-enter the unit cost to confirm awareness. Used when:
    - Item has floor_price_retail (selling at floor price)
    - Margin when selling at floor would be below standard (especially critical)

    Returns: { requires_confirmation: bool, reason: str, floor_price: float|None,
               margin_below_standard: bool, expected_unit_cost: float }
    """
    overrides = get_effective_item_overrides(db, item_id)
    floor = overrides.get("floor_price_retail")
    if floor is None:
        return {
            "requires_confirmation": False,
            "reason": "",
            "floor_price": None,
            "margin_below_standard": False,
            "expected_unit_cost": float(unit_cost_per_base),
        }
    floor_dec = Decimal(str(floor))
    cost = unit_cost_per_base
    margin_below_standard = False
    if cost and cost > 0:
        margin_at_floor_pct = (floor_dec - cost) / cost * Decimal("100")
        min_margin = PricingService.get_min_margin_percent(db, item_id, company_id)
        if margin_at_floor_pct < min_margin:
            margin_below_standard = True

    return {
        "requires_confirmation": True,
        "reason": (
            "Item has a floor price. Margin may be below standard."
            if margin_below_standard
            else "Item is selling at floor price. Please confirm the cost is correct."
        ),
        "floor_price": float(floor),
        "margin_below_standard": margin_below_standard,
        "expected_unit_cost": float(unit_cost_per_base),
    }
