-- Wipe all data from PharmaSight tables (for clean reload)
-- This script deletes all data but keeps the schema intact
-- WARNING: This will delete ALL data. Use only in development!

-- Disable foreign key checks temporarily (PostgreSQL doesn't support this, so we delete in order)
-- Delete in reverse dependency order to avoid foreign key violations

BEGIN;

-- Delete transaction data first (most dependent)
DELETE FROM inventory_ledger;
DELETE FROM sales_invoice_items;
DELETE FROM sales_invoices;
DELETE FROM purchase_invoice_items;
DELETE FROM purchase_invoices;
DELETE FROM grn_items;
DELETE FROM grns;
DELETE FROM credit_note_items;
DELETE FROM credit_notes;
DELETE FROM payments;

-- Delete master data
DELETE FROM item_units;
DELETE FROM items;
DELETE FROM suppliers;

-- Delete configuration
DELETE FROM company_pricing_defaults;
DELETE FROM item_pricing;
DELETE FROM document_sequences;
DELETE FROM company_settings;

-- Delete branch and company data (if you want to start fresh)
-- Uncomment these if you want to wipe everything including company setup:
-- DELETE FROM user_branch_roles;
-- DELETE FROM branches;
-- DELETE FROM companies;
-- DELETE FROM user_roles;
-- DELETE FROM users;

COMMIT;

-- Note: This script does NOT delete:
-- - Users (you may want to keep these)
-- - Company/Branch setup (you may want to keep these)
-- - User roles

-- To completely start fresh, also run:
-- DELETE FROM users;
-- DELETE FROM branches;
-- DELETE FROM companies;
