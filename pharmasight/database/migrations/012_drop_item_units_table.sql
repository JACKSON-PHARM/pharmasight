-- Drop item_units table: units are item characteristics (items table is the single source of truth).
-- Unit names and conversion rates (supplier_unit, wholesale_unit, retail_unit, pack_size,
-- wholesale_units_per_supplier, can_break_bulk) are defined and updated only via create/update item.
-- Run this on each tenant DB and default DB that has item_units.

DROP TABLE IF EXISTS item_units CASCADE;
