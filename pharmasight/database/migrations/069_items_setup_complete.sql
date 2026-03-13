-- Migration 069: Item setup_complete – gate transactions until pack size and units are configured.
-- Excel import creates items with setup_complete = false; user must complete item setup before using in sales/purchases/GRN.

ALTER TABLE items ADD COLUMN IF NOT EXISTS setup_complete BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN items.setup_complete IS 'When false, item was imported with minimal data (e.g. name only). User must complete pack size and units before the item can be used in sales, purchases, or GRN.';
