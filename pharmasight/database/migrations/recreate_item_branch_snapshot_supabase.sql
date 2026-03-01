-- =====================================================
-- Drop and recreate item_branch_snapshot (run in Supabase SQL Editor)
-- Use when backfill is failing and you want a clean table.
-- After this, run the backfill script again.
-- =====================================================

SET statement_timeout = 0;

DROP TABLE IF EXISTS item_branch_snapshot CASCADE;

CREATE TABLE item_branch_snapshot (
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

CREATE INDEX idx_item_branch_snapshot_company_branch
    ON item_branch_snapshot(company_id, branch_id);

CREATE UNIQUE INDEX idx_item_branch_snapshot_item_branch
    ON item_branch_snapshot(item_id, branch_id);

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_item_branch_snapshot_search_text_gin
    ON item_branch_snapshot USING gin(search_text gin_trgm_ops);

COMMENT ON TABLE item_branch_snapshot IS 'Item search snapshot: one row per (item_id, branch_id). Updated in same transaction as ledger. Used for single-SELECT item search across app (sales, quotations, inventory, etc.).';
