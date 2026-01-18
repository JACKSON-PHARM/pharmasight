-- Migration: Add VAT Classification Fields to Items Table (BATCHED UPDATE)
-- Use this if you have many items and the UPDATE times out

-- Step 1: Add columns (FAST)
ALTER TABLE items
ADD COLUMN IF NOT EXISTS is_vatable BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS vat_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS price_includes_vat BOOLEAN DEFAULT FALSE;

-- Step 2: Add comments (FAST)
COMMENT ON COLUMN items.is_vatable IS 'Is this item VATable? EXEMPT items are not vatable.';
COMMENT ON COLUMN items.vat_rate IS 'VAT rate: 0 for zero-rated medicines, 16 for standard-rated items/services';
COMMENT ON COLUMN items.vat_code IS 'VAT code: ZERO_RATED | STANDARD | EXEMPT';
COMMENT ON COLUMN items.price_includes_vat IS 'Is price inclusive of VAT?';

-- Step 3: Update vat_code in batches (run each batch separately if needed)
-- The DEFAULT values handle is_vatable, vat_rate, and price_includes_vat
-- Only vat_code needs explicit UPDATE

-- Batch 1: First 1000 rows
UPDATE items 
SET vat_code = 'ZERO_RATED' 
WHERE vat_code IS NULL 
AND id IN (
    SELECT id FROM items 
    WHERE vat_code IS NULL 
    ORDER BY created_at 
    LIMIT 1000
);

-- Batch 2: Next 1000 rows (run if needed)
-- UPDATE items 
-- SET vat_code = 'ZERO_RATED' 
-- WHERE vat_code IS NULL 
-- AND id IN (
--     SELECT id FROM items 
--     WHERE vat_code IS NULL 
--     ORDER BY created_at 
--     LIMIT 1000
-- );

-- Continue with more batches if needed...
