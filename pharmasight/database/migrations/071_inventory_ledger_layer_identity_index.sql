-- Migration 071: Optional composite index for dashboard valuation and layer-identity queries
-- Supports: WHERE company_id = ? AND branch_id = ? with grouping by (item_id, batch_number, expiry_date, unit_cost)
-- Safe to add; no existing indexes removed. Improves get_total_stock_value and any future all-branches aggregation.

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_layer_identity
ON inventory_ledger (company_id, branch_id, item_id, batch_number, expiry_date, unit_cost);

COMMENT ON INDEX idx_inventory_ledger_layer_identity IS
  'Dashboard valuation and layer aggregation: filter by company/branch; grouping by full layer identity.';
