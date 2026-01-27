-- =====================================================
-- CLEANUP SCRIPT: Wipe Items Data for Fresh 3-Tier Import
-- =====================================================
-- WARNING: This will DELETE ALL items, ALL transactions, and ALL related data
-- This is a DESTRUCTIVE operation for ADMIN-ONLY use when loading fresh Excel stocks
-- Use ONLY when you want to start completely fresh with Excel import
-- Run this BEFORE importing the Excel template after migration

-- IMPORTANT: Run the migration FIRST:
-- \i database/add_3tier_units.sql

-- =====================================================
-- STEP 1: Delete all transaction-related records that reference items
-- =====================================================
-- These tables have foreign keys to items WITHOUT CASCADE, so we must delete them first

-- Delete sales invoice items (references items)
DELETE FROM sales_invoice_items;

-- Delete purchase invoice items (references items)
DELETE FROM purchase_invoice_items;

-- Delete credit note items (references items)
DELETE FROM credit_note_items;

-- Delete quotation items (references items)
DELETE FROM quotation_items;

-- Delete purchase order items (references items)
DELETE FROM purchase_order_items;

-- OPTIONAL: If you want to delete parent invoices/orders too (completely clean slate)
-- Uncomment these if you want to remove ALL invoices, orders, and quotations:
-- DELETE FROM sales_invoices;
-- DELETE FROM purchase_invoices;
-- DELETE FROM credit_notes;
-- DELETE FROM quotations;
-- DELETE FROM purchase_orders;
-- DELETE FROM payments;  -- Payments reference sales_invoices

-- =====================================================
-- STEP 2: Delete all inventory and stock-related records
-- =====================================================

-- Delete ALL inventory ledger entries (including opening balances)
-- This includes all stock movements, purchases, sales, adjustments
DELETE FROM inventory_ledger;

-- Delete stock take records (has CASCADE but being explicit)
-- Note: These tables have CASCADE, but we delete explicitly for clarity
-- Using DO block to check table existence (some tables may not exist if migrations not run)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_take_adjustments') THEN
        DELETE FROM stock_take_adjustments;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_take_counter_locks') THEN
        DELETE FROM stock_take_counter_locks;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_take_counts') THEN
        DELETE FROM stock_take_counts;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_take_sessions') THEN
        DELETE FROM stock_take_sessions;
    END IF;
END $$;

-- Delete daily order book records (has CASCADE but being explicit)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'order_book_history') THEN
        DELETE FROM order_book_history;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_order_book') THEN
        DELETE FROM daily_order_book;
    END IF;
END $$;

-- =====================================================
-- STEP 3: Delete item-related configuration tables
-- =====================================================

-- Delete item_units (will be recreated from 3-tier system)
DELETE FROM item_units;

-- Delete item_pricing (legacy pricing table)
-- Note: 3-tier pricing is now on items table, not item_pricing
DELETE FROM item_pricing;

-- =====================================================
-- STEP 4: Delete all items (now safe - no foreign key constraints)
-- =====================================================
-- CAUTION: This deletes ALL items for ALL companies
-- If you only want to delete for a specific company, uncomment and set company_id:
-- DELETE FROM items WHERE company_id = 'YOUR_COMPANY_UUID_HERE';
DELETE FROM items;

-- =====================================================
-- VERIFICATION QUERIES (run after cleanup, before import)
-- =====================================================
-- SELECT COUNT(*) as items_count FROM items;  -- Should be 0
-- SELECT COUNT(*) as units_count FROM item_units;  -- Should be 0
-- SELECT COUNT(*) as pricing_count FROM item_pricing;  -- Should be 0
-- SELECT COUNT(*) as ledger_count FROM inventory_ledger;  -- Should be 0
-- SELECT COUNT(*) as sales_items_count FROM sales_invoice_items;  -- Should be 0
-- SELECT COUNT(*) as purchase_items_count FROM purchase_invoice_items;  -- Should be 0
-- SELECT COUNT(*) as quotation_items_count FROM quotation_items;  -- Should be 0
-- SELECT COUNT(*) as order_items_count FROM purchase_order_items;  -- Should be 0

-- =====================================================
-- NEXT STEPS
-- =====================================================
-- After cleanup, import Excel template via frontend "Import Excel" button
-- The system will create items with 3-tier structure
-- All previous transactions and stock movements are permanently deleted
