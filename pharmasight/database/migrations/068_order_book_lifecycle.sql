-- Migration 068: Order Book lifecycle (RECEIVED, CLOSED, timestamps for day/week/month review)
-- Design: pharmasight/docs/ORDER_BOOK_LIFECYCLE_DESIGN.md
-- daily_order_book: ordered_at, received_at; status may be RECEIVED before archive.
-- order_book_history: entry_date, ordered_at, received_at, branch_order_id for full timeline.

-- daily_order_book: when entry becomes ORDERED or RECEIVED
ALTER TABLE daily_order_book
    ADD COLUMN IF NOT EXISTS ordered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ;

COMMENT ON COLUMN daily_order_book.ordered_at IS 'When the entry was converted to a purchase order or branch order (status=ORDERED).';
COMMENT ON COLUMN daily_order_book.received_at IS 'When stock was received (GRN or branch receipt); set before archiving to history as CLOSED.';

-- order_book_history: full timeline for day/week/month filtering
ALTER TABLE order_book_history
    ADD COLUMN IF NOT EXISTS entry_date DATE,
    ADD COLUMN IF NOT EXISTS ordered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS branch_order_id UUID REFERENCES branch_orders(id) ON DELETE SET NULL;

COMMENT ON COLUMN order_book_history.entry_date IS 'Day the shortage event belonged to (for filtering by day/week/month).';
COMMENT ON COLUMN order_book_history.ordered_at IS 'When the order was placed (PO or branch order).';
COMMENT ON COLUMN order_book_history.received_at IS 'When stock was received (GRN or branch receipt).';
COMMENT ON COLUMN order_book_history.branch_order_id IS 'Set when entry was fulfilled via branch order (mirror of daily table).';

-- Backfill entry_date from created_at for existing history rows
UPDATE order_book_history
SET entry_date = (created_at::timestamptz AT TIME ZONE 'UTC')::date
WHERE entry_date IS NULL;

CREATE INDEX IF NOT EXISTS idx_order_book_history_entry_date ON order_book_history(entry_date) WHERE entry_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_order_book_history_branch_order_id ON order_book_history(branch_order_id) WHERE branch_order_id IS NOT NULL;
