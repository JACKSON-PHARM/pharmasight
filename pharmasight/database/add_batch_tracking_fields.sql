-- Migration: Add Batch Tracking Fields to Inventory Ledger and Items
-- Date: 2024
-- Description: Adds enhanced batch tracking capabilities including batch cost, remaining quantity, 
--              batch splits, and per-item batch/expiry tracking configuration

-- =====================================================
-- 1. ENHANCE INVENTORY LEDGER WITH BATCH TRACKING
-- =====================================================

-- Add batch_cost column (cost for this specific batch)
ALTER TABLE inventory_ledger 
ADD COLUMN IF NOT EXISTS batch_cost NUMERIC(20, 4);

COMMENT ON COLUMN inventory_ledger.batch_cost IS 'Cost for this specific batch (for FIFO/LIFO support)';

-- Add remaining_quantity column (for tracking remaining stock in batch)
ALTER TABLE inventory_ledger 
ADD COLUMN IF NOT EXISTS remaining_quantity INTEGER;

COMMENT ON COLUMN inventory_ledger.remaining_quantity IS 'Remaining quantity in this batch (for tracking)';

-- Add is_batch_tracked column (whether this entry is batch-tracked)
ALTER TABLE inventory_ledger 
ADD COLUMN IF NOT EXISTS is_batch_tracked BOOLEAN DEFAULT TRUE;

COMMENT ON COLUMN inventory_ledger.is_batch_tracked IS 'Whether this entry is batch-tracked';

-- Add parent_batch_id column (for batch splits within same transaction)
ALTER TABLE inventory_ledger 
ADD COLUMN IF NOT EXISTS parent_batch_id UUID REFERENCES inventory_ledger(id);

COMMENT ON COLUMN inventory_ledger.parent_batch_id IS 'Reference to parent batch for batch splits within same transaction';

-- Add split_sequence column (0=main batch, 1,2,3... for splits)
ALTER TABLE inventory_ledger 
ADD COLUMN IF NOT EXISTS split_sequence INTEGER DEFAULT 0;

COMMENT ON COLUMN inventory_ledger.split_sequence IS '0=main batch, 1,2,3... for splits within same transaction';

-- Update existing records: set is_batch_tracked based on batch_number presence
UPDATE inventory_ledger 
SET is_batch_tracked = (batch_number IS NOT NULL AND batch_number != '')
WHERE is_batch_tracked IS NULL;

-- Update existing records: set batch_cost = unit_cost for existing entries
UPDATE inventory_ledger 
SET batch_cost = unit_cost
WHERE batch_cost IS NULL AND batch_number IS NOT NULL AND batch_number != '';

-- Update existing records: set remaining_quantity = quantity_delta for positive entries
UPDATE inventory_ledger 
SET remaining_quantity = quantity_delta
WHERE remaining_quantity IS NULL AND quantity_delta > 0;

-- =====================================================
-- 2. ADD BATCH TRACKING CONFIGURATION TO ITEMS
-- =====================================================

-- Add requires_batch_tracking column
ALTER TABLE items 
ADD COLUMN IF NOT EXISTS requires_batch_tracking BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN items.requires_batch_tracking IS 'Whether item requires batch tracking';

-- Add requires_expiry_tracking column
ALTER TABLE items 
ADD COLUMN IF NOT EXISTS requires_expiry_tracking BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN items.requires_expiry_tracking IS 'Whether item requires expiry date tracking';

-- =====================================================
-- 3. CREATE INDEXES FOR PERFORMANCE
-- =====================================================

-- Index for batch queries
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_batch 
ON inventory_ledger(item_id, branch_id, batch_number, expiry_date) 
WHERE batch_number IS NOT NULL;

-- Index for parent batch lookups
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_parent_batch 
ON inventory_ledger(parent_batch_id) 
WHERE parent_batch_id IS NOT NULL;

-- Index for batch tracking flag
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_batch_tracked 
ON inventory_ledger(item_id, branch_id, is_batch_tracked) 
WHERE is_batch_tracked = TRUE;

-- Index for items with batch tracking requirements
CREATE INDEX IF NOT EXISTS idx_items_batch_tracking 
ON items(requires_batch_tracking, requires_expiry_tracking) 
WHERE requires_batch_tracking = TRUE OR requires_expiry_tracking = TRUE;

-- =====================================================
-- 4. VALIDATION CONSTRAINTS (Optional - can be added if needed)
-- =====================================================

-- Note: We don't add NOT NULL constraints on batch_cost and remaining_quantity
-- because they may be NULL for non-batch-tracked items or historical entries

-- Ensure split_sequence is non-negative (using DO block since IF NOT EXISTS not supported for constraints)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM pg_constraint 
        WHERE conname = 'check_split_sequence_non_negative'
    ) THEN
        ALTER TABLE inventory_ledger 
        ADD CONSTRAINT check_split_sequence_non_negative 
        CHECK (split_sequence >= 0);
    END IF;
END $$;

-- =====================================================
-- 5. UPDATE COMMENTS
-- =====================================================

COMMENT ON TABLE inventory_ledger IS 'Append-only inventory ledger with enhanced batch tracking. Supports multiple batches per transaction, batch splits, and FIFO/LIFO cost tracking.';

COMMENT ON TABLE items IS 'Item master data with batch and expiry tracking configuration.';

-- =====================================================
-- MIGRATION COMPLETE
-- =====================================================

-- Verify migration
DO $$
BEGIN
    RAISE NOTICE 'Migration completed successfully';
    RAISE NOTICE 'New columns added to inventory_ledger: batch_cost, remaining_quantity, is_batch_tracked, parent_batch_id, split_sequence';
    RAISE NOTICE 'New columns added to items: requires_batch_tracking, requires_expiry_tracking';
END $$;
