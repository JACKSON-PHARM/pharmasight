-- Migration 008: Deprecate items table price columns (hard deprecation — do not remove columns)
-- Cost/price MUST come from inventory_ledger only. No reads or writes to these columns.
-- Run after backend and frontend enforcement is complete.

-- Only deprecate columns that exist (some DBs may not have 3-tier price columns yet)
DO $$
BEGIN
    -- default_cost (always exists)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='default_cost') THEN
        EXECUTE 'COMMENT ON COLUMN items.default_cost IS ''DEPRECATED — DO NOT READ OR WRITE. Use inventory_ledger.''';
        EXECUTE 'ALTER TABLE items ALTER COLUMN default_cost DROP DEFAULT';
    END IF;
    
    -- purchase_price_per_supplier_unit (may not exist in older schemas)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='purchase_price_per_supplier_unit') THEN
        EXECUTE 'COMMENT ON COLUMN items.purchase_price_per_supplier_unit IS ''DEPRECATED — DO NOT READ OR WRITE.''';
        EXECUTE 'ALTER TABLE items ALTER COLUMN purchase_price_per_supplier_unit DROP DEFAULT';
    END IF;
    
    -- wholesale_price_per_wholesale_unit (may not exist in older schemas)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='wholesale_price_per_wholesale_unit') THEN
        EXECUTE 'COMMENT ON COLUMN items.wholesale_price_per_wholesale_unit IS ''DEPRECATED — DO NOT READ OR WRITE.''';
        EXECUTE 'ALTER TABLE items ALTER COLUMN wholesale_price_per_wholesale_unit DROP DEFAULT';
    END IF;
    
    -- retail_price_per_retail_unit (may not exist in older schemas)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='retail_price_per_retail_unit') THEN
        EXECUTE 'COMMENT ON COLUMN items.retail_price_per_retail_unit IS ''DEPRECATED — DO NOT READ OR WRITE.''';
        EXECUTE 'ALTER TABLE items ALTER COLUMN retail_price_per_retail_unit DROP DEFAULT';
    END IF;
END $$;
