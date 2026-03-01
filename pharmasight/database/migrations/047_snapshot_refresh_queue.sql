-- =====================================================
-- 047: snapshot_refresh_queue — deduplicated queue for bulk POS snapshot refresh
-- Single-item changes refresh synchronously in-transaction; bulk (company margin, VAT, etc.)
-- enqueue here and are processed in background in batches.
-- Rollback: DROP TABLE IF EXISTS snapshot_refresh_queue;
-- =====================================================

CREATE TABLE IF NOT EXISTS snapshot_refresh_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID REFERENCES items(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- One branch-wide job per (company_id, branch_id): item_id IS NULL means "refresh all items in branch"
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_refresh_queue_branch
    ON snapshot_refresh_queue(company_id, branch_id) WHERE item_id IS NULL;

-- One item job per (company_id, branch_id, item_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_refresh_queue_item
    ON snapshot_refresh_queue(company_id, branch_id, item_id) WHERE item_id IS NOT NULL;

-- Pending jobs: processed_at IS NULL, for worker to select
CREATE INDEX IF NOT EXISTS idx_snapshot_refresh_queue_pending
    ON snapshot_refresh_queue(company_id, branch_id) WHERE processed_at IS NULL;

COMMENT ON TABLE snapshot_refresh_queue IS 'Deduplicated queue for bulk POS snapshot refresh. Processed in background. item_id NULL = refresh entire branch.';
