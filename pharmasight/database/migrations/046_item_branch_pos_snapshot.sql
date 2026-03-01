-- =====================================================
-- 046: item_branch_pos_snapshot — write-time computed POS search cache
-- Single-table search when pos_snapshot_enabled; no joins, no read-time pricing/stock.
-- Updated in same transaction as GRN, sale, adjustment, pricing, item edit.
-- Rollback: DROP TABLE IF EXISTS item_branch_pos_snapshot;
-- =====================================================

CREATE TABLE IF NOT EXISTS item_branch_pos_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    pack_size INTEGER NOT NULL DEFAULT 1,
    base_unit VARCHAR(50),
    sku VARCHAR(100),
    vat_rate NUMERIC(5, 2),
    vat_category VARCHAR(20),
    current_stock NUMERIC(20, 4) NOT NULL DEFAULT 0,
    average_cost NUMERIC(20, 4),
    last_purchase_price NUMERIC(20, 4),
    selling_price NUMERIC(20, 4),
    margin_percent NUMERIC(10, 2),
    next_expiry_date DATE,
    search_text TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(item_id, branch_id)
);

-- B-tree on (company_id, branch_id) for search WHERE company_id = ? AND branch_id = ?
CREATE INDEX IF NOT EXISTS idx_pos_snapshot_company_branch
    ON item_branch_pos_snapshot(company_id, branch_id);

-- Unique index on (item_id, branch_id) — same as UNIQUE constraint, explicit for upserts
CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_snapshot_item_branch
    ON item_branch_pos_snapshot(item_id, branch_id);

-- GIN index on search_text for fast ILIKE (trigram)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_pos_snapshot_search_text_gin
    ON item_branch_pos_snapshot USING gin(search_text gin_trgm_ops);

COMMENT ON TABLE item_branch_pos_snapshot IS 'Write-time computed POS search snapshot. One row per (item_id, branch_id). Updated on GRN, sale, adjustment, pricing, item edit. Used for single-SELECT search when pos_snapshot_enabled.';
