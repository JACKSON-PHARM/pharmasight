-- Migration 109: KRA control-plane hardening (health + observability helpers)
-- Additive and backward-compatible.

ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failed_validation_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_blockers TEXT;

CREATE INDEX IF NOT EXISTS idx_branch_etims_credentials_token_expires_at
    ON branch_etims_credentials(token_expires_at);

COMMENT ON COLUMN branch_etims_credentials.failed_validation_count IS
    'Count of consecutive failed validation attempts for operational monitoring.';
COMMENT ON COLUMN branch_etims_credentials.activation_blockers IS
    'Semicolon-delimited activation blockers (missing credentials or failed checks).';
