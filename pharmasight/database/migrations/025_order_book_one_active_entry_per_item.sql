-- Migration 025: Enforce at most one active order book entry per (branch_id, item_id).
-- Prevents duplicate entries when the same item is auto-added from a sale and then manually added.
-- Active = status IN ('PENDING', 'ORDERED').

-- Remove duplicate active entries: keep the earliest created per (branch_id, item_id), delete the rest
DELETE FROM daily_order_book d1
USING daily_order_book d2
WHERE d1.branch_id = d2.branch_id
  AND d1.item_id = d2.item_id
  AND d1.status IN ('PENDING', 'ORDERED')
  AND d2.status IN ('PENDING', 'ORDERED')
  AND d1.created_at > d2.created_at;

-- Drop the old unique constraint that allowed (branch, item, PENDING) and (branch, item, ORDERED) as two rows
ALTER TABLE daily_order_book
    DROP CONSTRAINT IF EXISTS daily_order_book_branch_id_item_id_status_key;

-- Enforce one active entry per (branch, item): only one row with status PENDING or ORDERED per branch+item
CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_order_book_one_active_per_item
    ON daily_order_book (branch_id, item_id)
    WHERE status IN ('PENDING', 'ORDERED');

COMMENT ON INDEX idx_daily_order_book_one_active_per_item IS
    'Ensures at most one order book entry per item per branch (PENDING or ORDERED) to prevent duplicates from auto-sale + manual add';
