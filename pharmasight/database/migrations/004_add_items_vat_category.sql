-- Migration 004: Add vat_category column to items table
-- Required for Item model (ZERO_RATED | STANDARD_RATED).
-- Applied automatically to all tenant DBs on backend startup and to new tenants on provision.

ALTER TABLE items
ADD COLUMN IF NOT EXISTS vat_category VARCHAR(20) DEFAULT 'ZERO_RATED';

COMMENT ON COLUMN items.vat_category IS 'VAT category: ZERO_RATED | STANDARD_RATED';
