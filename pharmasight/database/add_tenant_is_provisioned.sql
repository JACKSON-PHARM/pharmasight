-- Add is_provisioned and provisioned_at to tenants (master DB).
-- Run this against the master database.
-- Only mark provisioned after verifying tables exist (initialize flow).

ALTER TABLE tenants
  ADD COLUMN IF NOT EXISTS is_provisioned BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS provisioned_at TIMESTAMPTZ;

COMMENT ON COLUMN tenants.is_provisioned IS 'True only after initialize verified tables exist. Never set without verification.';
COMMENT ON COLUMN tenants.provisioned_at IS 'When initialize completed successfully.';
