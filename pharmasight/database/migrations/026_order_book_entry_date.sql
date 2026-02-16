-- Migration 026: Add entry_date to daily order book so items are unique per date.
-- Same item can appear once per (branch, date); different dates can have the same item.

-- Add entry_date column (nullable first for backfill)
ALTER TABLE daily_order_book
    ADD COLUMN IF NOT EXISTS entry_date DATE;

-- Backfill from created_at date (use local date from timestamp)
UPDATE daily_order_book
SET entry_date = (created_at::timestamptz AT TIME ZONE 'UTC')::date
WHERE entry_date IS NULL;

-- Default for new rows
ALTER TABLE daily_order_book
    ALTER COLUMN entry_date SET DEFAULT CURRENT_DATE;

-- Enforce NOT NULL after backfill
ALTER TABLE daily_order_book
    ALTER COLUMN entry_date SET NOT NULL;

COMMENT ON COLUMN daily_order_book.entry_date IS 'Date this order book entry belongs to; items are unique per (branch, item, entry_date).';

-- Drop the previous per-item-only unique index (from 025)
DROP INDEX IF EXISTS idx_daily_order_book_one_active_per_item;

-- Enforce one active entry per (branch, item, date)
CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_order_book_one_active_per_item_date
    ON daily_order_book (branch_id, item_id, entry_date)
    WHERE status IN ('PENDING', 'ORDERED');

COMMENT ON INDEX idx_daily_order_book_one_active_per_item_date IS
    'One order book entry per item per branch per entry_date (PENDING or ORDERED).';

-- Update auto-generate function to be date-aware (one entry per item per date)
CREATE OR REPLACE FUNCTION auto_generate_order_book_entries(
    p_branch_id UUID,
    p_company_id UUID
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_item RECORD;
    v_monthly_sales NUMERIC;
    v_current_stock INTEGER;
    v_threshold NUMERIC;
    v_entries_created INTEGER := 0;
BEGIN
    FOR v_item IN 
        SELECT DISTINCT i.id, i.name, i.base_unit, i.sku, i.wholesale_unit, i.default_supplier_id
        FROM items i
        WHERE i.company_id = p_company_id
    LOOP
        SELECT COALESCE(SUM(quantity_delta), 0)::INTEGER INTO v_current_stock
        FROM inventory_ledger
        WHERE item_id = v_item.id AND branch_id = p_branch_id;
        
        SELECT COALESCE(SUM(ABS(quantity_delta)), 0) INTO v_monthly_sales
        FROM inventory_ledger
        WHERE item_id = v_item.id 
          AND branch_id = p_branch_id
          AND transaction_type = 'SALE'
          AND created_at >= CURRENT_DATE - INTERVAL '30 days';
        
        v_threshold := GREATEST(v_monthly_sales / 2, 0);
        
        IF (v_current_stock < v_threshold OR v_current_stock = 0) THEN
            -- Only one pending entry per (branch, item, entry_date)
            IF NOT EXISTS (
                SELECT 1 FROM daily_order_book
                WHERE branch_id = p_branch_id
                  AND item_id = v_item.id
                  AND entry_date = CURRENT_DATE
                  AND status = 'PENDING'
            ) THEN
                INSERT INTO daily_order_book (
                    company_id,
                    branch_id,
                    item_id,
                    entry_date,
                    supplier_id,
                    quantity_needed,
                    unit_name,
                    reason,
                    priority,
                    status,
                    created_by
                ) VALUES (
                    p_company_id,
                    p_branch_id,
                    v_item.id,
                    CURRENT_DATE,
                    v_item.default_supplier_id,
                    GREATEST(CEIL(v_threshold - v_current_stock), 1),
                    COALESCE(NULLIF(TRIM(v_item.wholesale_unit), ''), v_item.base_unit),
                    'AUTO_THRESHOLD',
                    5,
                    'PENDING',
                    (SELECT id FROM users WHERE is_active = TRUE LIMIT 1)
                );
                v_entries_created := v_entries_created + 1;
            END IF;
        END IF;
    END LOOP;
    RETURN v_entries_created;
END;
$$;
