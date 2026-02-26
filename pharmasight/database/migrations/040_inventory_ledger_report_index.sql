-- Migration 040: Composite index on inventory_ledger for branch-scoped item movement report
-- Supports: WHERE company_id = ? AND branch_id = ? AND item_id = ? AND created_at >= ? AND created_at < ?
-- ORDER BY created_at ASC, id ASC

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_company_branch_item_created
  ON inventory_ledger (company_id, branch_id, item_id, created_at);

COMMENT ON INDEX idx_inventory_ledger_company_branch_item_created IS
  'Item movement report: filter by company, branch, item and date range; stable sort by created_at, id';
