-- =====================================================
-- 3-TIER UNIT SYSTEM MIGRATION
-- =====================================================
-- Adds 3-tier UNIT hierarchy to items table:
-- Supplier Unit: what we buy (packet, box, bottle)
-- Wholesale Unit: what pharmacies buy (packet, box, bottle)
-- Retail Unit: what customers buy (tablet, capsule, ml, gram)
-- Stock tracked in RETAIL UNITS. Display: "5 packets + 25 tablets"

-- 3-TIER UNIT SYSTEM
ALTER TABLE items ADD COLUMN IF NOT EXISTS supplier_unit VARCHAR(50) DEFAULT 'piece';
ALTER TABLE items ADD COLUMN IF NOT EXISTS wholesale_unit VARCHAR(50) DEFAULT 'piece';
ALTER TABLE items ADD COLUMN IF NOT EXISTS retail_unit VARCHAR(50) DEFAULT 'piece';
ALTER TABLE items ADD COLUMN IF NOT EXISTS pack_size INTEGER NOT NULL DEFAULT 1;
ALTER TABLE items ADD COLUMN IF NOT EXISTS can_break_bulk BOOLEAN NOT NULL DEFAULT TRUE;

-- PRICING WITH CLEAR UNIT ATTRIBUTION (on items table)
ALTER TABLE items ADD COLUMN IF NOT EXISTS purchase_price_per_supplier_unit NUMERIC(15,2) DEFAULT 0;
ALTER TABLE items ADD COLUMN IF NOT EXISTS wholesale_price_per_wholesale_unit NUMERIC(15,2) DEFAULT 0;
ALTER TABLE items ADD COLUMN IF NOT EXISTS retail_price_per_retail_unit NUMERIC(15,2) DEFAULT 0;

-- VAT CLASSIFICATION
ALTER TABLE items ADD COLUMN IF NOT EXISTS vat_category VARCHAR(20) DEFAULT 'ZERO_RATED';
-- vat_rate, price_includes_vat already exist on items

-- Backfill: set 3-tier units from base_unit for existing rows
UPDATE items
SET supplier_unit = COALESCE(NULLIF(TRIM(base_unit), ''), 'piece'),
    wholesale_unit = COALESCE(NULLIF(TRIM(base_unit), ''), 'piece'),
    retail_unit = COALESCE(NULLIF(TRIM(base_unit), ''), 'piece')
WHERE supplier_unit = 'piece' AND wholesale_unit = 'piece' AND retail_unit = 'piece';

ALTER TABLE items DROP CONSTRAINT IF EXISTS chk_pack_size_positive;
ALTER TABLE items ADD CONSTRAINT chk_pack_size_positive CHECK (pack_size >= 1);

COMMENT ON COLUMN items.supplier_unit IS 'What we buy: packet, box, bottle';
COMMENT ON COLUMN items.wholesale_unit IS 'What pharmacies buy: packet, box, bottle';
COMMENT ON COLUMN items.retail_unit IS 'What customers buy: tablet, capsule, ml, gram';
COMMENT ON COLUMN items.pack_size IS 'Retail units per supplier/wholesale unit (e.g. 30 tablets per packet)';
COMMENT ON COLUMN items.can_break_bulk IS 'Can we sell individual retail units?';
COMMENT ON COLUMN items.purchase_price_per_supplier_unit IS 'Cost per supplier unit (e.g. per packet)';
COMMENT ON COLUMN items.wholesale_price_per_wholesale_unit IS 'Sell price per wholesale unit to pharmacies';
COMMENT ON COLUMN items.retail_price_per_retail_unit IS 'Sell price per retail unit to customers (e.g. per tablet)';
COMMENT ON COLUMN items.vat_category IS 'ZERO_RATED (medicines) or STANDARD_RATED (non-medical)';
