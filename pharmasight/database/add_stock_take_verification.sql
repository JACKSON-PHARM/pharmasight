-- =====================================================
-- ADD VERIFICATION STATUS TO STOCK TAKE COUNTS
-- =====================================================
-- Adds verification workflow: PENDING, APPROVED, REJECTED
-- =====================================================

-- Add verification status column
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'PENDING';

-- Add verified_by column (user who verified)
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS verified_by UUID REFERENCES users(id);

-- Add verified_at timestamp
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

-- Add rejection_reason (why it was rejected)
ALTER TABLE stock_take_counts
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- Add constraint for valid status values
ALTER TABLE stock_take_counts
    ADD CONSTRAINT check_verification_status 
    CHECK (verification_status IN ('PENDING', 'APPROVED', 'REJECTED'));

-- Add index for faster queries
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_verification_status 
    ON stock_take_counts(verification_status);

CREATE INDEX IF NOT EXISTS idx_stock_take_counts_shelf_verification 
    ON stock_take_counts(shelf_location, verification_status);

-- Add comment
COMMENT ON COLUMN stock_take_counts.verification_status IS 'Verification status: PENDING (awaiting verification), APPROVED (verified correct), REJECTED (returned to counter)';
COMMENT ON COLUMN stock_take_counts.verified_by IS 'User ID who verified this count';
COMMENT ON COLUMN stock_take_counts.verified_at IS 'Timestamp when count was verified';
COMMENT ON COLUMN stock_take_counts.rejection_reason IS 'Reason for rejection (if verification_status = REJECTED)';
