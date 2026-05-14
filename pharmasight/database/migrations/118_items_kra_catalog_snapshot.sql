-- Full KRA selectItemList row for items.kra_item_code (authoritative catalog metadata after each sync / refresh).
ALTER TABLE items ADD COLUMN IF NOT EXISTS kra_catalog_snapshot jsonb;

COMMENT ON COLUMN items.kra_catalog_snapshot IS
  'Last OSCU selectItemList row for this itemCd from KRA; updated when sync/refresh applies catalog (same txn as kra_* columns).';
