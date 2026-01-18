-- Migration: Add VAT Classification Fields to Items Table
-- For Kenya Pharmacy Context: Items store VAT classification as intrinsic property
-- Most medicines are zero-rated (0%), some items/services are standard-rated (16%)

-- Step 1: Add VAT classification columns to items table (FAST - just adds columns)
ALTER TABLE items
ADD COLUMN IF NOT EXISTS is_vatable BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS vat_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS price_includes_vat BOOLEAN DEFAULT FALSE;

-- Step 2: Add column comments (FAST)
COMMENT ON COLUMN items.is_vatable IS 'Is this item VATable? EXEMPT items are not vatable.';
COMMENT ON COLUMN items.vat_rate IS 'VAT rate: 0 for zero-rated medicines, 16 for standard-rated items/services';
COMMENT ON COLUMN items.vat_code IS 'VAT code: ZERO_RATED | STANDARD | EXEMPT';
COMMENT ON COLUMN items.price_includes_vat IS 'Is price inclusive of VAT?';

-- Step 3: Update existing rows (OPTIONAL - only if you have existing items)
-- This uses DEFAULT values from ALTER TABLE, so UPDATE is only needed for vat_code
-- Run this separately if you have many items, or skip it and let new items use defaults

-- For large tables, run this UPDATE in smaller batches or skip it entirely
-- New items will get defaults (vat_rate=0, is_vatable=TRUE, price_includes_vat=FALSE)
-- Only vat_code needs to be set explicitly
-- UPDATE items SET vat_code = 'ZERO_RATED' WHERE vat_code IS NULL;
