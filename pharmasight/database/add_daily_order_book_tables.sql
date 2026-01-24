-- =====================================================
-- DAILY ORDER BOOK TABLES
-- Branch-level order book for tracking items needing reordering
-- =====================================================

-- Daily Order Book (Current active entries)
CREATE TABLE daily_order_book (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    supplier_id UUID REFERENCES suppliers(id), -- Preferred supplier for this item
    quantity_needed NUMERIC(20,4) NOT NULL, -- Quantity to order (in base units)
    unit_name VARCHAR(50) NOT NULL, -- Unit name for display
    reason VARCHAR(100) NOT NULL, -- AUTO_THRESHOLD, MANUAL_SALE, MANUAL_QUOTATION, MANUAL_ADD
    source_reference_type VARCHAR(50), -- sales_invoice, quotation, null for auto/manual
    source_reference_id UUID, -- ID of sales invoice or quotation if applicable
    notes TEXT,
    priority INTEGER DEFAULT 5, -- 1-10, higher = more urgent
    status VARCHAR(50) DEFAULT 'PENDING', -- PENDING, ORDERED, CANCELLED
    purchase_order_id UUID REFERENCES purchase_orders(id), -- If converted to PO
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(branch_id, item_id, status) -- One pending entry per item per branch
);

COMMENT ON TABLE daily_order_book IS 'Daily order book entries at branch level. Tracks items needing reordering.';
COMMENT ON COLUMN daily_order_book.reason IS 'AUTO_THRESHOLD: Auto-generated from stock threshold, MANUAL_SALE: Added from sales invoice, MANUAL_QUOTATION: Added from quotation, MANUAL_ADD: Manually added by user';
COMMENT ON COLUMN daily_order_book.status IS 'PENDING: Not yet ordered, ORDERED: Converted to purchase order, CANCELLED: Cancelled by user';
COMMENT ON COLUMN daily_order_book.quantity_needed IS 'Quantity needed in base units';

-- Order Book History (Archive of completed/cancelled entries)
CREATE TABLE order_book_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    supplier_id UUID REFERENCES suppliers(id),
    quantity_needed NUMERIC(20,4) NOT NULL,
    unit_name VARCHAR(50) NOT NULL,
    reason VARCHAR(100) NOT NULL,
    source_reference_type VARCHAR(50),
    source_reference_id UUID,
    notes TEXT,
    priority INTEGER DEFAULT 5,
    status VARCHAR(50) NOT NULL, -- ORDERED, CANCELLED
    purchase_order_id UUID REFERENCES purchase_orders(id),
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL, -- Original creation time
    updated_at TIMESTAMPTZ NOT NULL, -- When status changed
    archived_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP -- When moved to history
);

COMMENT ON TABLE order_book_history IS 'Historical archive of order book entries that were ordered or cancelled.';

-- Indexes for performance
CREATE INDEX idx_order_book_branch ON daily_order_book(branch_id);
CREATE INDEX idx_order_book_item ON daily_order_book(item_id);
CREATE INDEX idx_order_book_status ON daily_order_book(status);
CREATE INDEX idx_order_book_supplier ON daily_order_book(supplier_id);
CREATE INDEX idx_order_book_created ON daily_order_book(created_at);
CREATE INDEX idx_order_book_company_branch ON daily_order_book(company_id, branch_id);

CREATE INDEX idx_order_book_history_branch ON order_book_history(branch_id);
CREATE INDEX idx_order_book_history_item ON order_book_history(item_id);
CREATE INDEX idx_order_book_history_status ON order_book_history(status);
CREATE INDEX idx_order_book_history_archived ON order_book_history(archived_at);

-- Function to auto-generate order book entries based on stock threshold
-- Threshold = half of monthly sales (or zero if no sales)
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
    -- Loop through all items for this branch
    FOR v_item IN 
        SELECT DISTINCT i.id, i.name, i.base_unit, i.sku
        FROM items i
        WHERE i.company_id = p_company_id
    LOOP
        -- Get current stock for this item at this branch
        SELECT COALESCE(SUM(quantity_delta), 0)::INTEGER INTO v_current_stock
        FROM inventory_ledger
        WHERE item_id = v_item.id AND branch_id = p_branch_id;
        
        -- Calculate monthly sales (last 30 days)
        SELECT COALESCE(SUM(ABS(quantity_delta)), 0) INTO v_monthly_sales
        FROM inventory_ledger
        WHERE item_id = v_item.id 
          AND branch_id = p_branch_id
          AND transaction_type = 'SALE'
          AND created_at >= CURRENT_DATE - INTERVAL '30 days';
        
        -- Threshold = half of monthly sales (or 0 if no sales)
        v_threshold := GREATEST(v_monthly_sales / 2, 0);
        
        -- Only add to order book if:
        -- 1. Current stock is below threshold, OR
        -- 2. Current stock is zero (regardless of sales)
        IF (v_current_stock < v_threshold OR v_current_stock = 0) THEN
            -- Check if there's already a pending entry for this item
            IF NOT EXISTS (
                SELECT 1 FROM daily_order_book
                WHERE branch_id = p_branch_id
                  AND item_id = v_item.id
                  AND status = 'PENDING'
            ) THEN
                -- Calculate quantity needed (threshold - current stock, minimum 1)
                INSERT INTO daily_order_book (
                    company_id,
                    branch_id,
                    item_id,
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
                    GREATEST(CEIL(v_threshold - v_current_stock), 1),
                    v_item.base_unit,
                    'AUTO_THRESHOLD',
                    5, -- Default priority
                    'PENDING',
                    (SELECT id FROM users WHERE is_active = TRUE LIMIT 1) -- System user or first active user
                );
                
                v_entries_created := v_entries_created + 1;
            END IF;
        END IF;
    END LOOP;
    
    RETURN v_entries_created;
END;
$$;

COMMENT ON FUNCTION auto_generate_order_book_entries IS 'Auto-generates order book entries for items below stock threshold (half of monthly sales) or with zero stock.';
