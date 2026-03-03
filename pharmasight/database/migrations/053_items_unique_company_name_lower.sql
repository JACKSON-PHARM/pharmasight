-- Migration 053: Enforce unique (company_id, lower(name)) and (company_id, lower(sku)) on items so duplicate names/codes cannot be inserted (e.g. double-submit or race).
-- Application already rejects duplicates case-insensitively; these indexes ensure DB-level consistency and prevent races.

-- Data cleanup: deactivate duplicate active items so the unique indexes can be created (keeps newest per company_id, lower(name) and per company_id, lower(sku)).
UPDATE items SET is_active = false
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY company_id, lower(name) ORDER BY created_at DESC) AS rn
        FROM items WHERE is_active = true
    ) x WHERE rn > 1
    UNION
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY company_id, lower(sku) ORDER BY created_at DESC) AS rn
        FROM items WHERE is_active = true AND sku IS NOT NULL AND sku != ''
    ) x WHERE rn > 1
);

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
