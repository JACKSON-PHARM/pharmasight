# Floor Price & Minimum Margin Implementation

## Summary
Clean implementation of floor price and margin rules without breaking production. All changes are backward-compatible.

## Changes Made

### 1. Floor Overrides Margin (Item-Level Exception)
**File:** `backend/app/services/pricing_config_service.py`

When an item has `floor_price_retail` set (e.g., 200 bob) and the sale price is ≥ floor:
- **Before:** Both floor and margin were enforced. Selling at 200 when cost=250 (negative margin) could be blocked.
- **After:** Margin check is **skipped**. The floor IS the pricing rule for that item; no margin enforcement.

When price < floor: still blocked (unchanged).

### 2. Promo Price Detection
**Files:** `pricing_config_service.py`, `sales.py`, `quotations.py`

- Added `is_line_price_at_promo()`: returns True when the line is selling at the item's active promo price (handles unit conversion: promo is per retail, line may be wholesale).
- Sales and quotations now pass `is_promo_price=True` to `validate_line_price` when the line matches the promo price.
- When `promotions_can_go_below_margin` is true in PricingSettings, promo prices can go below the margin rule.

### 3. PricingSettings.default_min_margin_retail_pct Wired
**File:** `backend/app/services/pricing_service.py`

`get_min_margin_percent` now checks `PricingSettings.default_min_margin_retail_pct` when falling back to company-level defaults (after item_pricing and margin_tier). Companies can set a simple "no sell below 15%" in Settings > Pricing.

### 4. Unified Validation Everywhere
**Files:** `sales.py`, `quotations.py`

All price validation paths now use `validate_line_price` (floor + margin + promo + discount rules):
- Sales: create invoice, add line, batch
- Quotations: convert to invoice

## Resolution Order (Unchanged)

1. **Item-level:** `ItemPricing.min_margin_percent`, `Item.floor_price_retail`
2. **Tier:** `CompanyMarginTier.min_margin_percent` (by item pricing_tier)
3. **Company:** `PricingSettings.default_min_margin_retail_pct` (when set), then `CompanyPricingDefault.min_margin_percent`

## Backward Compatibility

- No DB migrations required.
- Existing behavior when floor/promo not set: unchanged.
- PricingSettings.default_min_margin_retail_pct: NULL by default; existing companies unaffected until they configure it.
