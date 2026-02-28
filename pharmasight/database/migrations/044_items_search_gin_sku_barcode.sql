-- =====================================================
-- 044: GIN trigram indexes on items.sku and items.barcode
-- Speeds up ILIKE search on SKU/barcode (name already has idx_items_name_trgm in 024).
-- Enables sub-500ms item search when customers search by code or barcode.
-- Rollback: DROP INDEX IF EXISTS idx_items_sku_trgm; DROP INDEX IF EXISTS idx_items_barcode_trgm;
-- =====================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- GIN index on sku for fast ILIKE (e.g. search "nilacid" or "NIL")
CREATE INDEX IF NOT EXISTS idx_items_sku_trgm ON items USING gin(sku gin_trgm_ops) WHERE is_active = true AND sku IS NOT NULL;

-- GIN index on barcode for fast ILIKE
CREATE INDEX IF NOT EXISTS idx_items_barcode_trgm ON items USING gin(barcode gin_trgm_ops) WHERE is_active = true AND barcode IS NOT NULL;

COMMENT ON INDEX idx_items_sku_trgm IS 'Item search: fast ILIKE on sku for typeahead';
COMMENT ON INDEX idx_items_barcode_trgm IS 'Item search: fast ILIKE on barcode for typeahead';
