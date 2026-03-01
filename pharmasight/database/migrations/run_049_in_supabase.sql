-- =====================================================
-- Run this entire script in Supabase SQL Editor (one run).
-- 049: Rename item_branch_pos_snapshot → item_branch_snapshot
-- Stop the app first so no other connection locks the table.
-- =====================================================

SET statement_timeout = 0;

-- 1. Rename table
ALTER TABLE item_branch_pos_snapshot RENAME TO item_branch_snapshot;

-- 2. Rename indexes
ALTER INDEX idx_pos_snapshot_company_branch RENAME TO idx_item_branch_snapshot_company_branch;
ALTER INDEX idx_pos_snapshot_item_branch RENAME TO idx_item_branch_snapshot_item_branch;
ALTER INDEX idx_pos_snapshot_search_text_gin RENAME TO idx_item_branch_snapshot_search_text_gin;

-- 3. Rename unique constraint (default name from UNIQUE(item_id, branch_id))
-- If this fails with "constraint ... does not exist", run:
--   SELECT conname FROM pg_constraint WHERE conrelid = 'item_branch_snapshot'::regclass AND contype = 'u';
-- and replace the name below with the result.
ALTER TABLE item_branch_snapshot RENAME CONSTRAINT item_branch_pos_snapshot_item_id_branch_id_key TO item_branch_snapshot_item_id_branch_id_key;

-- 4. Table comment
COMMENT ON TABLE item_branch_snapshot IS 'Item search snapshot: one row per (item_id, branch_id). Updated in same transaction as ledger. Used for single-SELECT item search across app (sales, quotations, inventory, etc.).';

-- 5. Mark migration as applied so the app skips it on startup
INSERT INTO schema_migrations (version, applied_at)
VALUES ('049_rename_item_branch_pos_snapshot_to_item_branch_snapshot', NOW())
ON CONFLICT (version) DO NOTHING;
