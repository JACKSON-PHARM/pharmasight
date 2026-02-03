-- Migration 009: Simplify items table to match agreed schema
-- Adds: description, is_controlled, is_cold_chain, track_expiry
-- Drops: deprecated price columns, redundant VAT columns, generic_name, requires_batch_tracking, requires_expiry_tracking
-- Cost/price remains from inventory_ledger only. base_unit kept for now (reference = wholesale_unit).

-- 1. Add new columns
ALTER TABLE items ADD COLUMN IF NOT EXISTS description VARCHAR(255);
ALTER TABLE items ADD COLUMN IF NOT EXISTS is_controlled BOOLEAN DEFAULT false;
ALTER TABLE items ADD COLUMN IF NOT EXISTS is_cold_chain BOOLEAN DEFAULT false;
ALTER TABLE items ADD COLUMN IF NOT EXISTS track_expiry BOOLEAN DEFAULT false;

-- 2. Backfill from old columns (only if old columns exist)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'items' AND column_name = 'generic_name') THEN
        UPDATE items SET description = generic_name WHERE description IS NULL AND generic_name IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'items' AND column_name = 'requires_batch_tracking') THEN
        UPDATE items SET is_controlled = COALESCE(requires_batch_tracking, false);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'items' AND column_name = 'requires_expiry_tracking') THEN
        UPDATE items SET track_expiry = COALESCE(requires_expiry_tracking, false);
    END IF;
END $$;

-- 3. Drop deprecated columns (only if they exist)
ALTER TABLE items DROP COLUMN IF EXISTS default_cost;
ALTER TABLE items DROP COLUMN IF EXISTS purchase_price_per_supplier_unit;
ALTER TABLE items DROP COLUMN IF EXISTS wholesale_price_per_wholesale_unit;
ALTER TABLE items DROP COLUMN IF EXISTS retail_price_per_retail_unit;
ALTER TABLE items DROP COLUMN IF EXISTS is_vatable;
ALTER TABLE items DROP COLUMN IF EXISTS vat_code;
ALTER TABLE items DROP COLUMN IF EXISTS price_includes_vat;
ALTER TABLE items DROP COLUMN IF EXISTS generic_name;
ALTER TABLE items DROP COLUMN IF EXISTS requires_batch_tracking;
ALTER TABLE items DROP COLUMN IF EXISTS requires_expiry_tracking;

-- 4. Comments
COMMENT ON COLUMN items.description IS 'Item description (was generic_name)';
COMMENT ON COLUMN items.is_controlled IS 'Whether item is a controlled substance (was requires_batch_tracking)';
COMMENT ON COLUMN items.is_cold_chain IS 'Whether item requires cold chain storage';
COMMENT ON COLUMN items.track_expiry IS 'Whether item requires expiry date tracking (was requires_expiry_tracking)';
