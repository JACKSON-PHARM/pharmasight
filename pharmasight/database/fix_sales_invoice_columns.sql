-- Quick Fix: Add missing columns to sales_invoices
-- Run this to fix the "column does not exist" errors

-- Add customer_phone if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sales_invoices' 
        AND column_name = 'customer_phone'
    ) THEN
        ALTER TABLE sales_invoices ADD COLUMN customer_phone VARCHAR(50);
        RAISE NOTICE 'Added customer_phone column';
    ELSE
        RAISE NOTICE 'customer_phone column already exists';
    END IF;
END $$;

-- Add sales_type if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sales_invoices' 
        AND column_name = 'sales_type'
    ) THEN
        ALTER TABLE sales_invoices ADD COLUMN sales_type VARCHAR(20) DEFAULT 'RETAIL';
        RAISE NOTICE 'Added sales_type column';
    ELSE
        RAISE NOTICE 'sales_type column already exists';
    END IF;
END $$;

-- Update existing records
UPDATE sales_invoices 
SET sales_type = 'RETAIL' 
WHERE sales_type IS NULL;

-- Verify
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'sales_invoices' 
AND column_name IN ('customer_phone', 'sales_type')
ORDER BY column_name;
