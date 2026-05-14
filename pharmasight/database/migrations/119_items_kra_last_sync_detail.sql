-- Last completed item→KRA sync audit (path, saveItem vs lookup-only, VAT alignment hint).
ALTER TABLE items ADD COLUMN IF NOT EXISTS kra_last_sync_detail jsonb;

COMMENT ON COLUMN items.kra_last_sync_detail IS
  'Written when sync_item_to_kra finishes: sync_path, save_item_called, PharmaSight vs catalogue tax codes, user_hint.';
