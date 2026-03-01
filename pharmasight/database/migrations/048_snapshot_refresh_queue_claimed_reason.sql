-- =====================================================
-- 048: snapshot_refresh_queue — claimed_at (for chunked processing), reason (debug)
-- claimed_at: set when worker starts a branch-wide job so others skip it; released after chunked work.
-- reason: optional text for debugging (e.g. company_margin_change, promotion_update).
-- Rollback: ALTER TABLE snapshot_refresh_queue DROP COLUMN IF EXISTS claimed_at, DROP COLUMN IF EXISTS reason;
-- =====================================================

ALTER TABLE snapshot_refresh_queue
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reason TEXT;

CREATE INDEX IF NOT EXISTS idx_snapshot_refresh_queue_claimed
    ON snapshot_refresh_queue(claimed_at) WHERE processed_at IS NULL;

COMMENT ON COLUMN snapshot_refresh_queue.claimed_at IS 'Set when worker starts processing (branch-wide); allows chunked commits without re-locking.';
COMMENT ON COLUMN snapshot_refresh_queue.reason IS 'Optional: company_margin_change, promotion_update, vat_change, etc.';
