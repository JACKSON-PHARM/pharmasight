-- Migration: Add missing columns to sales_invoices table
-- This ensures customer_phone and sales_type columns exist

-- =====================================================
-- 1. Add customer_phone column (if not exists)
-- =====================================================

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);

COMMENT ON COLUMN sales_invoices.customer_phone IS 'Customer phone number (required for credit payment mode)';

-- =====================================================
-- 2. Add sales_type column (if not exists)
-- =====================================================

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS sales_type VARCHAR(20) DEFAULT 'RETAIL';

COMMENT ON COLUMN sales_invoices.sales_type IS 'RETAIL (customers) or WHOLESALE (pharmacies). Determines which pricing tier to use.';

-- =====================================================
-- 3. Update existing records to have default values
-- =====================================================

-- Set default sales_type for existing invoices that don't have it
UPDATE sales_invoices 
SET sales_type = 'RETAIL' 
WHERE sales_type IS NULL;

-- =====================================================
-- 4. Verify columns exist
-- =====================================================

-- This query will fail if columns don't exist (helpful for debugging)
DO $$
BEGIN
    -- Check customer_phone
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sales_invoices' 
        AND column_name = 'customer_phone'
    ) THEN
        RAISE EXCEPTION 'Column customer_phone was not added successfully';
    END IF;
    
    -- Check sales_type
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sales_invoices' 
        AND column_name = 'sales_type'
    ) THEN
        RAISE EXCEPTION 'Column sales_type was not added successfully';
    END IF;
    
    RAISE NOTICE '✅ All columns verified successfully';
END $$;
