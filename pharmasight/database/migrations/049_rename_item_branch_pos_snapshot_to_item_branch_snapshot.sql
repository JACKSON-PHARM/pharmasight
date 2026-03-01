-- =====================================================
-- 049: Rename item_branch_pos_snapshot → item_branch_snapshot
-- Table is used for item search app-wide (sales, quotations, inventory, suppliers, etc.), not POS-only.
-- Rollback: ALTER TABLE item_branch_snapshot RENAME TO item_branch_pos_snapshot; (and revert index/constraint names)
-- Idempotent: if the table was already renamed (e.g. manually in Supabase), this is a no-op so startup does not fail.
-- =====================================================
-- Disable statement timeout for this migration (Supabase pooler may have short default; renames can take time).
SET statement_timeout = 0;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'item_branch_pos_snapshot'
  ) THEN
    ALTER TABLE item_branch_pos_snapshot RENAME TO item_branch_snapshot;

    ALTER INDEX idx_pos_snapshot_company_branch RENAME TO idx_item_branch_snapshot_company_branch;
    ALTER INDEX idx_pos_snapshot_item_branch RENAME TO idx_item_branch_snapshot_item_branch;
    ALTER INDEX idx_pos_snapshot_search_text_gin RENAME TO idx_item_branch_snapshot_search_text_gin;

    -- Constraint name from UNIQUE(item_id, branch_id) is default: item_branch_pos_snapshot_item_id_branch_id_key
    ALTER TABLE item_branch_snapshot RENAME CONSTRAINT item_branch_pos_snapshot_item_id_branch_id_key TO item_branch_snapshot_item_id_branch_id_key;

    COMMENT ON TABLE item_branch_snapshot IS 'Item search snapshot: one row per (item_id, branch_id). Updated in same transaction as ledger. Used for single-SELECT item search across app (sales, quotations, inventory, etc.).';
  END IF;
  -- If item_branch_pos_snapshot does not exist, the rename was already done (e.g. manual run or previous apply). No-op.
END $$;
