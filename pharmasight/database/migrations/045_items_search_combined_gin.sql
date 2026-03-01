-- =====================================================
-- 045: Combined GIN trigram index for item search (name + sku + barcode)
-- One index scan instead of OR of three columns; dramatically reduces base_query time
-- for searches like "osteocare" (was ~1.3s, target <200ms).
-- PostgreSQL requires index expressions to use IMMUTABLE functions; lower() is STABLE (locale-dependent).
-- One immutable function does the full expression so the index has no non-immutable calls.
-- Rollback: DROP INDEX IF EXISTS idx_items_search_combined_gin; DROP FUNCTION IF EXISTS items_search_combined_immutable(text, text, text);
-- ======zx===============================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Single IMMUTABLE function: combined "name sku barcode" lowercased (C locale). Used only in index.
CREATE OR REPLACE FUNCTION items_search_combined_immutable(n text, s text, b text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT concat(
      lower(COALESCE(n, '')::text COLLATE "C"),
      ' ',
      lower(COALESCE(s, '')::text COLLATE "C"),
      ' ',
      lower(COALESCE(b, '')::text COLLATE "C")
    );
  $$;

CREATE INDEX IF NOT EXISTS idx_items_search_combined_gin ON items USING gin(
  (items_search_combined_immutable(name, sku, barcode)) gin_trgm_ops
) WHERE is_active = true;

COMMENT ON INDEX idx_items_search_combined_gin IS 'Item search: single GIN scan on combined name+sku+barcode for fast ILIKE';
