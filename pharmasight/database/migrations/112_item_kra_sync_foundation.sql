-- Migration 112: Item KRA sync foundation (bootstrap + update propagation)
-- Additive fields on items table for operational sync tracking.

ALTER TABLE items
    ADD COLUMN IF NOT EXISTS kra_sync_status VARCHAR(30) NOT NULL DEFAULT 'not_synced',
    ADD COLUMN IF NOT EXISTS kra_sync_error TEXT,
    ADD COLUMN IF NOT EXISTS kra_synced_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS kra_last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS kra_sync_attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS kra_payload_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS kra_needs_resync BOOLEAN NOT NULL DEFAULT true;

CREATE INDEX IF NOT EXISTS idx_items_kra_sync_status ON items(kra_sync_status);
CREATE INDEX IF NOT EXISTS idx_items_kra_needs_resync ON items(kra_needs_resync);
