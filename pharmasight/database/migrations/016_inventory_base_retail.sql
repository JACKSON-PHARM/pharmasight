-- Migration 016: Switch inventory base unit from wholesale to retail.
-- Ledger quantity_delta becomes "retail units" (e.g. 1 pack received = +100, 20 tablets sold = -20).
-- Convert existing data: multiply each quantity_delta by the item's pack_size (1 pack -> 100 retail).
--
-- Some tenant DBs may not have items.pack_size (older migrations never added it). Add it if missing
-- so the UPDATE works and future app code can rely on it.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'items' AND column_name = 'pack_size') THEN
    ALTER TABLE items ADD COLUMN pack_size INTEGER NOT NULL DEFAULT 1;
    COMMENT ON COLUMN items.pack_size IS 'Wholesale-to-retail: 1 wholesale unit = pack_size retail units (e.g. 100 tablets per pack).';
  END IF;
END $$;

UPDATE inventory_ledger l
SET quantity_delta = l.quantity_delta * COALESCE(
  (SELECT GREATEST(1, COALESCE(i.pack_size, 1)) FROM items i WHERE i.id = l.item_id),
  1
);

COMMENT ON COLUMN inventory_ledger.quantity_delta IS 'Stock movement in base (retail) units. e.g. +100 for 1 pack received (pack_size 100), -20 for 20 tablets sold.';
