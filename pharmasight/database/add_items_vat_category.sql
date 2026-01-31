-- One-off: Add vat_category to items (for manual run on a single DB only).
-- PREFERRED: Use the numbered migration so all tenants get it automatically:
--   database/migrations/004_add_items_vat_category.sql
-- That file is applied to ALL tenant DBs on backend startup and to new tenants on provision.
-- See database/TENANT_MIGRATIONS.md for how to add new schema changes across tenants.

ALTER TABLE items
ADD COLUMN IF NOT EXISTS vat_category VARCHAR(20) DEFAULT 'ZERO_RATED';

COMMENT ON COLUMN items.vat_category IS 'VAT category: ZERO_RATED | STANDARD_RATED';
