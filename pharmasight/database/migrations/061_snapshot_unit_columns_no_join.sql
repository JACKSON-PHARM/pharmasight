-- =============================================================================
-- 061: Add unit columns to item_branch_snapshot so search needs no Item join
-- Enables single-table search; keeps query plan identical to EXPLAIN in diagnose_item_search_indexes.sql.
-- =============================================================================

-- Add columns (denormalized from items for POS search display)
ALTER TABLE item_branch_snapshot
  ADD COLUMN IF NOT EXISTS retail_unit VARCHAR(50) DEFAULT 'piece',
  ADD COLUMN IF NOT EXISTS supplier_unit VARCHAR(50) DEFAULT 'piece',
  ADD COLUMN IF NOT EXISTS wholesale_unit VARCHAR(50) DEFAULT 'piece',
  ADD COLUMN IF NOT EXISTS wholesale_units_per_supplier NUMERIC(20, 4) NOT NULL DEFAULT 1;

-- Backfill from items (one row per snapshot row)
UPDATE item_branch_snapshot s
SET
  retail_unit = COALESCE(NULLIF(TRIM(i.retail_unit), ''), 'piece'),
  supplier_unit = COALESCE(NULLIF(TRIM(i.supplier_unit), ''), 'piece'),
  wholesale_unit = COALESCE(NULLIF(TRIM(i.wholesale_unit), ''), 'piece'),
  wholesale_units_per_supplier = COALESCE(i.wholesale_units_per_supplier, 1)
FROM items i
WHERE i.id = s.item_id;

COMMENT ON COLUMN item_branch_snapshot.retail_unit IS 'From items; avoids join in search.';
COMMENT ON COLUMN item_branch_snapshot.supplier_unit IS 'From items; avoids join in search.';
COMMENT ON COLUMN item_branch_snapshot.wholesale_unit IS 'From items; avoids join in search.';
COMMENT ON COLUMN item_branch_snapshot.wholesale_units_per_supplier IS 'From items; avoids join in search.';
