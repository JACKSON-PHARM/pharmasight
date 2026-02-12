-- Migration 015: Allow fractional base units in inventory_ledger for stock harmonization.
-- Enables correct deduction when selling in retail units (e.g. 20 tablets from 1 packet = 100 tablets).
-- Base = wholesale; 1 packet = 1 base, 1 tablet = 1/pack_size base (e.g. 0.01). So 20 tablets = 0.2 base.

ALTER TABLE inventory_ledger
  ALTER COLUMN quantity_delta TYPE NUMERIC(20, 4) USING quantity_delta::NUMERIC(20, 4);

COMMENT ON COLUMN inventory_ledger.quantity_delta IS 'Stock movement in base (wholesale) units. Fractional allowed for retail sales (e.g. -0.2 for 20 tablets when 1 packet = 100 tablets).';
