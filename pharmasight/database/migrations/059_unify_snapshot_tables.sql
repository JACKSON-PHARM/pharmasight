-- =====================================================
-- 059: Unify snapshot tables — extend item_branch_snapshot
-- Add columns from item_branch_purchase_snapshot and item_branch_search_snapshot,
-- plus pricing inputs and effective_selling_price/price_source.
-- Legacy tables are NOT dropped; reads will migrate to this table first.
-- Rollback: drop added columns (see end of file).
-- =====================================================

-- 1. Add columns from item_branch_purchase_snapshot
ALTER TABLE item_branch_snapshot
  ADD COLUMN IF NOT EXISTS last_purchase_date timestamptz,
  ADD COLUMN IF NOT EXISTS last_supplier_id uuid REFERENCES suppliers(id) ON DELETE SET NULL;

-- 2. Add columns from item_branch_search_snapshot
ALTER TABLE item_branch_snapshot
  ADD COLUMN IF NOT EXISTS last_order_date date,
  ADD COLUMN IF NOT EXISTS last_sale_date date,
  ADD COLUMN IF NOT EXISTS last_order_book_date timestamptz,
  ADD COLUMN IF NOT EXISTS last_quotation_date date;

-- 3. Pricing inputs (populated by snapshot refresh)
ALTER TABLE item_branch_snapshot
  ADD COLUMN IF NOT EXISTS default_item_margin numeric(10,2),
  ADD COLUMN IF NOT EXISTS branch_margin numeric(10,2),
  ADD COLUMN IF NOT EXISTS company_margin numeric(10,2),
  ADD COLUMN IF NOT EXISTS floor_price numeric(20,4),
  ADD COLUMN IF NOT EXISTS minimum_margin numeric(10,2),
  ADD COLUMN IF NOT EXISTS promotion_price numeric(20,4),
  ADD COLUMN IF NOT EXISTS promotion_start timestamptz,
  ADD COLUMN IF NOT EXISTS promotion_end timestamptz,
  ADD COLUMN IF NOT EXISTS promotion_active boolean DEFAULT false;

-- 4. Computed selling price and source
ALTER TABLE item_branch_snapshot
  ADD COLUMN IF NOT EXISTS effective_selling_price numeric(20,4),
  ADD COLUMN IF NOT EXISTS price_source text;

-- 5. Indexes for promotion/background jobs (optional; use for future promo refresh jobs)
CREATE INDEX IF NOT EXISTS idx_item_branch_snapshot_promotion_active
  ON item_branch_snapshot(promotion_active) WHERE promotion_active = true;
CREATE INDEX IF NOT EXISTS idx_item_branch_snapshot_promotion_end
  ON item_branch_snapshot(promotion_end) WHERE promotion_end IS NOT NULL;

-- 6. Backfill from item_branch_purchase_snapshot (last_purchase_date, last_supplier_id)
UPDATE item_branch_snapshot s
SET
  last_purchase_date = p.last_purchase_date,
  last_supplier_id = p.last_supplier_id
FROM item_branch_purchase_snapshot p
WHERE p.item_id = s.item_id AND p.branch_id = s.branch_id AND p.company_id = s.company_id;

-- 7. Backfill from item_branch_search_snapshot (activity dates)
UPDATE item_branch_snapshot s
SET
  last_order_date = src.last_order_date,
  last_sale_date = src.last_sale_date,
  last_order_book_date = src.last_order_book_date,
  last_quotation_date = src.last_quotation_date
FROM item_branch_search_snapshot src
WHERE src.item_id = s.item_id AND src.branch_id = s.branch_id AND src.company_id = s.company_id;

-- 8. Set effective_selling_price = selling_price and price_source for existing rows (refresh will overwrite with full logic)
UPDATE item_branch_snapshot
SET
  effective_selling_price = COALESCE(effective_selling_price, selling_price),
  price_source = COALESCE(price_source, 'company_margin')
WHERE effective_selling_price IS NULL AND selling_price IS NOT NULL;

COMMENT ON COLUMN item_branch_snapshot.last_purchase_date IS 'From item_branch_purchase_snapshot; last purchase timestamp.';
COMMENT ON COLUMN item_branch_snapshot.last_supplier_id IS 'From item_branch_purchase_snapshot; supplier of last purchase.';
COMMENT ON COLUMN item_branch_snapshot.last_order_date IS 'From item_branch_search_snapshot; last PO date.';
COMMENT ON COLUMN item_branch_snapshot.effective_selling_price IS 'Final price displayed in search; promotion > floor > margin.';
COMMENT ON COLUMN item_branch_snapshot.price_source IS 'promotion, floor, branch_margin, company_margin, default_margin, manual.';
