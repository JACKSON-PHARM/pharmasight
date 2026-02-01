-- Add wholesale_units_per_supplier to items (3-tier units: base = wholesale, 1 supplier = N wholesale)
ALTER TABLE items ADD COLUMN IF NOT EXISTS wholesale_units_per_supplier NUMERIC(20,4) NOT NULL DEFAULT 1;
COMMENT ON COLUMN items.wholesale_units_per_supplier IS 'Wholesale units per 1 supplier unit (1 supplier = N wholesale). supplier_qty = wholesale_qty / N.';
