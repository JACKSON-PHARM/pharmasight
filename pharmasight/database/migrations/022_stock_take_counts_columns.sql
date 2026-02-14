-- =====================================================
-- 022: Stock take counts - batch, expiry, unit, verification
-- =====================================================
-- Adds columns required by StockTakeCount model so stock take
-- save/complete work. Applied automatically on app restart.
-- =====================================================

-- Batch / unit columns
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS batch_number VARCHAR(200);
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS expiry_date DATE;
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS unit_name VARCHAR(50);
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS quantity_in_unit NUMERIC(20, 4);

-- Verification columns
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'PENDING';
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS verified_by UUID REFERENCES users(id);
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE stock_take_counts ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- Backfill verification_status for existing rows
UPDATE stock_take_counts SET verification_status = 'PENDING' WHERE verification_status IS NULL;

-- Constraint (drop first so re-run is safe)
ALTER TABLE stock_take_counts DROP CONSTRAINT IF EXISTS check_verification_status;
ALTER TABLE stock_take_counts ADD CONSTRAINT check_verification_status
    CHECK (verification_status IN ('PENDING', 'APPROVED', 'REJECTED'));

-- Shelf location NOT NULL
UPDATE stock_take_counts SET shelf_location = 'UNKNOWN' WHERE shelf_location IS NULL;
ALTER TABLE stock_take_counts ALTER COLUMN shelf_location SET NOT NULL;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_shelf_location ON stock_take_counts(shelf_location);
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_batch_number ON stock_take_counts(batch_number);
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_verification_status ON stock_take_counts(verification_status);
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_shelf_verification ON stock_take_counts(shelf_location, verification_status);
