-- =====================================================
-- REBUILD SCHEMA - Development Only
-- Drops all database objects and rebuilds from scratch
-- USE ONLY IN DEVELOPMENT - WILL DELETE ALL DATA
-- =====================================================

-- Step 1: Drop TRIGGERS first (they depend on tables)
DROP TRIGGER IF EXISTS check_single_company ON companies CASCADE;

-- Step 2: Drop FUNCTIONS (they may be referenced by triggers)
DROP FUNCTION IF EXISTS enforce_single_company() CASCADE;
DROP FUNCTION IF EXISTS get_next_document_number(UUID, UUID, VARCHAR) CASCADE;
DROP FUNCTION IF EXISTS get_current_stock(UUID, UUID) CASCADE;
DROP FUNCTION IF EXISTS get_company_id() CASCADE;

-- Step 3: Drop INDEXES (they depend on tables)
DROP INDEX IF EXISTS idx_inventory_ledger_item CASCADE;
DROP INDEX IF EXISTS idx_inventory_ledger_branch CASCADE;
DROP INDEX IF EXISTS idx_inventory_ledger_expiry CASCADE;
DROP INDEX IF EXISTS idx_inventory_ledger_company CASCADE;
DROP INDEX IF EXISTS idx_inventory_ledger_reference CASCADE;
DROP INDEX IF EXISTS idx_inventory_ledger_batch CASCADE;

-- Step 4: Drop all tables in reverse dependency order (CASCADE handles foreign keys)
DROP TABLE IF EXISTS credit_note_items CASCADE;
DROP TABLE IF EXISTS credit_notes CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS sales_invoice_items CASCADE;
DROP TABLE IF EXISTS sales_invoices CASCADE;
DROP TABLE IF EXISTS purchase_invoice_items CASCADE;
DROP TABLE IF EXISTS purchase_invoices CASCADE;
DROP TABLE IF EXISTS grn_items CASCADE;
DROP TABLE IF EXISTS grns CASCADE;
DROP TABLE IF EXISTS inventory_ledger CASCADE;
DROP TABLE IF EXISTS expenses CASCADE;
DROP TABLE IF EXISTS expense_categories CASCADE;
DROP TABLE IF EXISTS item_pricing CASCADE;
DROP TABLE IF EXISTS item_units CASCADE;
DROP TABLE IF EXISTS items CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS document_sequences CASCADE;
DROP TABLE IF EXISTS company_pricing_defaults CASCADE;
DROP TABLE IF EXISTS company_settings CASCADE;
DROP TABLE IF EXISTS user_branch_roles CASCADE;
DROP TABLE IF EXISTS branches CASCADE;
DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS companies CASCADE;

-- Step 5: Verify cleanup (optional - comment out if you want)
DO $$
DECLARE
    table_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_type = 'BASE TABLE'
    AND table_name IN (
        'companies', 'users', 'user_roles', 'branches', 'user_branch_roles',
        'items', 'item_units', 'company_pricing_defaults', 'item_pricing',
        'suppliers', 'inventory_ledger', 'grns', 'grn_items',
        'purchase_invoices', 'purchase_invoice_items',
        'sales_invoices', 'sales_invoice_items', 'payments',
        'credit_notes', 'credit_note_items',
        'expense_categories', 'expenses',
        'company_settings', 'document_sequences'
    );
    
    IF table_count > 0 THEN
        RAISE NOTICE 'WARNING: % tables still exist. Some drops may have failed.', table_count;
    ELSE
        RAISE NOTICE 'SUCCESS: All tables dropped successfully.';
    END IF;
END $$;

-- =====================================================
-- NEXT STEP: Run schema.sql to recreate everything
-- =====================================================
-- After running this script, execute: pharmasight/database/schema.sql
