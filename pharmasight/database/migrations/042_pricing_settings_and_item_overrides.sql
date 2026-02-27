-- Migration 042: Pricing & margin defaults + discount rules (company) and item-level overrides
-- Additive only. Safe defaults preserve current behavior until UI/config is used.
-- Does NOT change sales, FEFO, or existing margin logic until explicitly wired.

-- 1. Company-level pricing/margin/discount settings (one row per company)
CREATE TABLE IF NOT EXISTS pricing_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    default_min_margin_retail_pct NUMERIC(10, 2) NULL,
    default_min_margin_wholesale_pct NUMERIC(10, 2) NULL,
    below_margin_behavior VARCHAR(50) NOT NULL DEFAULT 'allow_warn',
    allow_line_discounts BOOLEAN NOT NULL DEFAULT true,
    max_discount_pct_without_override NUMERIC(10, 2) NULL,
    promotions_can_go_below_margin BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id)
);

CREATE INDEX IF NOT EXISTS idx_pricing_settings_company ON pricing_settings(company_id);
COMMENT ON TABLE pricing_settings IS 'Company-level: default min margins, behavior when below margin, discount/promo rules. NULL defaults = use existing company_margin_tiers/item_pricing.';

-- 2. Item-level: floor price and simple promo (single window per item)
ALTER TABLE items ADD COLUMN IF NOT EXISTS floor_price_retail NUMERIC(20, 4) NULL;
ALTER TABLE items ADD COLUMN IF NOT EXISTS promo_price_retail NUMERIC(20, 4) NULL;
ALTER TABLE items ADD COLUMN IF NOT EXISTS promo_start_date DATE NULL;
ALTER TABLE items ADD COLUMN IF NOT EXISTS promo_end_date DATE NULL;
COMMENT ON COLUMN items.floor_price_retail IS 'Minimum allowed selling price (retail). Enforced per company behavior.';
COMMENT ON COLUMN items.promo_price_retail IS 'Temporary promo price (retail). Used when today between promo_start_date and promo_end_date.';

-- 3. Seed one pricing_settings row per company with safe defaults (no change to current behavior)
INSERT INTO pricing_settings (
    company_id,
    below_margin_behavior,
    allow_line_discounts,
    promotions_can_go_below_margin
)
SELECT id, 'allow_warn', true, true
FROM companies
ON CONFLICT (company_id) DO NOTHING;

-- 4. Permissions for Phase 3 (Settings UI and item overrides)
INSERT INTO permissions (name, module, action, description) VALUES
('settings.manage_pricing', 'Settings', 'manage_pricing', 'Edit global pricing & margin defaults and discount rules'),
('items.manage_pricing', 'Items', 'manage_pricing', 'Edit item-level margin overrides, floor price, and promo')
ON CONFLICT (name) DO NOTHING;
