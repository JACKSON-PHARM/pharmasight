-- Migration 053: Enforce unique (company_id, lower(name)) and (company_id, lower(sku)) on items so duplicate names/codes cannot be inserted (e.g. double-submit or race).
-- Application already rejects duplicates case-insensitively; these indexes ensure DB-level consistency and prevent races.

-- One active item per company per name (case-insensitive).
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_company_name_lower_unique
    ON items (company_id, lower(name))
    WHERE is_active = true;

-- One active item per company per SKU/code when SKU is set (case-insensitive).
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_company_sku_lower_unique
    ON items (company_id, lower(sku))
    WHERE is_active = true AND sku IS NOT NULL AND sku != '';

COMMENT ON INDEX idx_items_company_name_lower_unique IS 'One active item per company per name (case-insensitive). Prevents duplicate items from double-submit or concurrent create.';
COMMENT ON INDEX idx_items_company_sku_lower_unique IS 'One active item per company per SKU/code when set (case-insensitive). Prevents duplicate item codes.';
