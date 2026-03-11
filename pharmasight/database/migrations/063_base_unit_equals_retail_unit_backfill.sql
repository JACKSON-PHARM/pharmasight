-- Unit harmonization: align items.base_unit with retail_unit.
-- Ledger and stock quantities are in retail units; base_unit must equal retail_unit for consistent labels.
-- Safe to run multiple times (idempotent).

UPDATE items
SET base_unit = COALESCE(NULLIF(TRIM(retail_unit), ''), base_unit, 'piece')
WHERE base_unit IS DISTINCT FROM COALESCE(NULLIF(TRIM(retail_unit), ''), base_unit, 'piece');
