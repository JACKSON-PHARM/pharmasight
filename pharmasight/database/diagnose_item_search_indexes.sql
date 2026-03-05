-- =============================================================================
-- Item search latency diagnosis
-- Run this in the TENANT database (same DB used by GET /api/items/search).
-- Replace :company_id and :branch_id with your actual UUIDs for EXPLAIN ANALYZE.
-- =============================================================================

-- 1. Check pg_trgm extension (required for GIN trigram index on search_text)
SELECT extname, extversion
FROM pg_extension
WHERE extname = 'pg_trgm';
-- Expected: one row. If empty, run: CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. List indexes on item_branch_snapshot
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'item_branch_snapshot'
ORDER BY indexname;
-- Expected: idx_item_branch_snapshot_company_branch, idx_item_branch_snapshot_item_branch,
--           idx_item_branch_snapshot_search_text_gin (GIN on search_text).
-- If idx_item_branch_snapshot_search_text_gin is missing, create it (see ITEM_SEARCH_LATENCY_INVESTIGATION.md).

-- 3. Row count for item_branch_snapshot (and per branch if you pass branch_id)
SELECT COUNT(*) AS total_rows FROM item_branch_snapshot;

-- Optional: rows per (company_id, branch_id) to see how large the search set is
-- SELECT company_id, branch_id, COUNT(*) AS rows
-- FROM item_branch_snapshot
-- GROUP BY company_id, branch_id
-- ORDER BY rows DESC
-- LIMIT 20;

-- 4. EXPLAIN (ANALYZE, BUFFERS) — exact search pattern (single table, no join)
-- Confirms planner uses Bitmap Index Scan or Index Scan, NOT Seq Scan.
-- Execution time should be <50 ms. Run after applying 060_ensure_item_search_indexes.sql.
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    s.item_id,
    s.name,
    s.pack_size,
    s.base_unit,
    s.sku,
    s.current_stock,
    s.effective_selling_price
FROM item_branch_snapshot s
WHERE s.company_id = '9c71915e-3e59-45d5-9719-56d2322ff673'
  AND s.branch_id = 'bec5d46a-7f21-45ef-945c-8c68171aa386'
  AND s.search_text ILIKE '%nilacid%'
ORDER BY (s.current_stock <= 0), s.name
LIMIT 50;

-- 5. Interpret the plan:
--    GOOD: "Bitmap Index Scan" or "Index Scan" on idx_item_branch_snapshot_search_text_gin (or BitmapAnd with idx_item_branch_snapshot_company_branch).
--    BAD:  "Seq Scan on item_branch_snapshot" → run migration 060 or create indexes manually (see 060_ensure_item_search_indexes.sql).
--    Execution Time: must be <50 ms to keep API under 100 ms.
