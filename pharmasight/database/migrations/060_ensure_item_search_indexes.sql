-- =============================================================================
-- 060: Ensure item search indexes (pg_trgm + GIN + company_branch)
-- Idempotent: safe to run on any DB. Ensures search stays <100ms at 1.5M rows.
-- Run in TENANT database (same DB as GET /api/items/search).
-- =============================================================================

-- 1. Install pg_trgm extension (required for GIN trigram index on search_text)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Branch filter: (company_id, branch_id) — narrows to one branch (~7.5k rows at scale)
CREATE INDEX IF NOT EXISTS idx_item_branch_snapshot_company_branch
    ON item_branch_snapshot (company_id, branch_id);

-- 3. Trigram GIN on search_text — fast ILIKE '%term%' (no seq scan)
CREATE INDEX IF NOT EXISTS idx_item_branch_snapshot_search_text_gin
    ON item_branch_snapshot USING gin(search_text gin_trgm_ops);

-- 4. Update statistics so planner uses indexes
ANALYZE item_branch_snapshot;

COMMENT ON INDEX idx_item_branch_snapshot_company_branch IS 'Item search: filter by branch (~7.5k rows per branch at 1.5M scale).';
COMMENT ON INDEX idx_item_branch_snapshot_search_text_gin IS 'Item search: ILIKE partial match via trigram; keeps search <100ms.';
