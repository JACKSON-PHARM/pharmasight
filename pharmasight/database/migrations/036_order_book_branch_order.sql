-- Migration 036: Order Book – branch order conversion
-- When a branch order is batched, add/update order book entries for the ordering branch and mark as ORDERED with branch_order_id (same pattern as purchase_order_id).

ALTER TABLE daily_order_book
    ADD COLUMN IF NOT EXISTS branch_order_id UUID REFERENCES branch_orders(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_daily_order_book_branch_order_id ON daily_order_book(branch_order_id) WHERE branch_order_id IS NOT NULL;

COMMENT ON COLUMN daily_order_book.branch_order_id IS 'Set when entry is fulfilled via a branch order (status=ORDERED). Distinguishes from purchase_order_id.';
