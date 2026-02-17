-- Migration 027: Item product category, pricing tier, and three-tier margin system
-- 1. Item classification: product_category (Pharmaceutical/Cosmetics/Equipment/Service)
-- 2. Item pricing tier: pricing_tier (drives default margin: Chronic 15%, Standard 30%, High-margin 40-100%)
-- 3. Company margin tier defaults (admin-configurable per tier)
-- 4. Permission: allow selling below min margin (role-based)

-- Items: product category and pricing tier
ALTER TABLE items ADD COLUMN IF NOT EXISTS product_category VARCHAR(50) NULL;
ALTER TABLE items ADD COLUMN IF NOT EXISTS pricing_tier VARCHAR(50) NULL;

COMMENT ON COLUMN items.product_category IS 'Product type: PHARMACEUTICAL, COSMETICS, EQUIPMENT, SERVICE. Used for display and default pricing tier.';
COMMENT ON COLUMN items.pricing_tier IS 'Margin tier: CHRONIC_MEDICATION (15%), STANDARD (30%), BEAUTY_COSMETICS, NUTRITION_SUPPLEMENTS, INJECTABLES, COLD_CHAIN, SPECIAL_PAIN. If NULL, derived from product_category.';

-- Company margin tier defaults (three-tier system)
CREATE TABLE IF NOT EXISTS company_margin_tiers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    tier_name VARCHAR(50) NOT NULL,
    default_margin_percent NUMERIC(10,2) NOT NULL,
    min_margin_percent NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, tier_name)
);

COMMENT ON TABLE company_margin_tiers IS 'Per-company default and minimum margin by pricing tier. Used when item has no item_pricing.markup_percent override.';

CREATE INDEX IF NOT EXISTS idx_company_margin_tiers_company ON company_margin_tiers(company_id);

-- Seed default margin tiers for existing companies (run once per company via trigger or app startup)
-- We seed global defaults here; app can copy to each company on first use or we insert per company in migration
DO $$
DECLARE
    cid UUID;
BEGIN
    FOR cid IN SELECT id FROM companies
    LOOP
        INSERT INTO company_margin_tiers (company_id, tier_name, default_margin_percent, min_margin_percent)
        VALUES
            (cid, 'CHRONIC_MEDICATION', 15.00, 10.00),
            (cid, 'STANDARD', 30.00, 20.00),
            (cid, 'BEAUTY_COSMETICS', 75.00, 50.00),
            (cid, 'NUTRITION_SUPPLEMENTS', 60.00, 40.00),
            (cid, 'INJECTABLES', 45.00, 30.00),
            (cid, 'COLD_CHAIN', 40.00, 30.00),
            (cid, 'SPECIAL_PAIN', 55.00, 40.00),
            (cid, 'EQUIPMENT', 35.00, 25.00),
            (cid, 'SERVICE', 50.00, 30.00)
        ON CONFLICT (company_id, tier_name) DO NOTHING;
    END LOOP;
END $$;

-- Permission: allow selling below minimum margin (user-restricted)
INSERT INTO permissions (name, module, action, description) VALUES
('sales.sell_below_min_margin', 'Sales', 'sell_below_min_margin', 'Allow selling below item/category minimum margin')
ON CONFLICT (name) DO NOTHING;

-- Grant sell_below_min_margin to admin and Super Admin roles
DO $$
DECLARE
    perm_id UUID;
    r RECORD;
BEGIN
    SELECT id INTO perm_id FROM permissions WHERE name = 'sales.sell_below_min_margin' LIMIT 1;
    IF perm_id IS NOT NULL THEN
        FOR r IN SELECT id FROM user_roles WHERE LOWER(role_name) IN ('super admin', 'admin')
        LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT r.id, perm_id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = r.id AND rp.permission_id = perm_id AND rp.branch_id IS NULL
            );
        END LOOP;
    END IF;
END $$;
