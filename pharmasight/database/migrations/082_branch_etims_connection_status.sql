-- eTIMS branch credentials: connection test lifecycle for UI + submission gating
ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS connection_status VARCHAR(30) NOT NULL DEFAULT 'not_configured',
    ADD COLUMN IF NOT EXISTS last_tested_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN branch_etims_credentials.connection_status IS 'disabled | not_configured | not_tested | verified | failed';
COMMENT ON COLUMN branch_etims_credentials.last_tested_at IS 'Last eTIMS test-connection (or inferred check) timestamp';

-- Backfill from existing rows (submission requires verified after this release; OAuth may come from app env)
UPDATE branch_etims_credentials
SET connection_status = CASE
    WHEN enabled IS NOT TRUE THEN 'disabled'
    WHEN NULLIF(TRIM(COALESCE(kra_bhf_id, '')), '') IS NULL THEN 'not_configured'
    WHEN NULLIF(TRIM(COALESCE(device_serial, '')), '') IS NULL THEN 'not_configured'
    WHEN NULLIF(TRIM(COALESCE(cmc_key_encrypted, '')), '') IS NULL THEN 'not_configured'
    ELSE 'not_tested'
END;
