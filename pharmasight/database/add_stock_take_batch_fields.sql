-- =====================================================
-- ADD BATCH NUMBER, EXPIRY DATE, AND REQUIRE SHELF LOCATION
-- =====================================================
-- Adds batch tracking fields to stock_take_counts table
-- Makes shelf_location required (NOT NULL)
-- =====================================================

-- Add batch_number column
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS batch_number VARCHAR(200);

-- Add expiry_date column
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS expiry_date DATE;

-- Add unit_name column (for tracking which unit was used for counting)
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS unit_name VARCHAR(50);

-- Add quantity_in_unit column (for storing the actual counted quantity in the selected unit)
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS quantity_in_unit NUMERIC(20, 4);

-- Make shelf_location required (NOT NULL)
-- First, set any NULL shelf_locations to a default value
UPDATE stock_take_counts
SET shelf_location = 'UNKNOWN'
WHERE shelf_location IS NULL;

-- Now make it NOT NULL
ALTER TABLE stock_take_counts
    ALTER COLUMN shelf_location SET NOT NULL;

-- Add index on shelf_location for faster queries
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_shelf_location 
    ON stock_take_counts(shelf_location);

-- Add index on batch_number for faster queries
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_batch_number 
    ON stock_take_counts(batch_number);

-- Add comment explaining the new fields
COMMENT ON COLUMN stock_take_counts.batch_number IS 'Batch number for this count (if item requires batch tracking)';
COMMENT ON COLUMN stock_take_counts.expiry_date IS 'Expiry date for this count (if item requires expiry tracking)';
COMMENT ON COLUMN stock_take_counts.unit_name IS 'Unit name used for counting (e.g., PACKET, TABLET). Counted quantity is stored in base units.';
COMMENT ON COLUMN stock_take_counts.quantity_in_unit IS 'Quantity counted in the selected unit (before conversion to base units)';
COMMENT ON COLUMN stock_take_counts.shelf_location IS 'Shelf name/location where count was performed (REQUIRED)';
