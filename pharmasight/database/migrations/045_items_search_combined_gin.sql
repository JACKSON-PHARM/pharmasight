-- =====================================================
-- 045: Combined GIN trigram index for item search (name + sku + barcode)
-- One index scan instead of OR of three columns; dramatically reduces base_query time
-- for searches like "osteocare" (was ~1.3s, target <200ms).
-- Expression must match the filter used in the API: same concat of lower(name), sku, barcode.
-- Rollback: DROP INDEX IF EXISTS idx_items_search_combined_gin;
-- =====================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Single expression: "name sku barcode" (lowercase, space-separated). One GIN scan for ILIKE '%term%'.
CREATE INDEX IF NOT EXISTS idx_items_search_combined_gin ON items USING gin(
  (concat(lower(COALESCE(name,'')), ' ', lower(COALESCE(sku,'')), ' ', lower(COALESCE(barcode,'')))) gin_trgm_ops
) WHERE is_active = true;

COMMENT ON INDEX idx_items_search_combined_gin IS 'Item search: single GIN scan on combined name+sku+barcode for fast ILIKE';
