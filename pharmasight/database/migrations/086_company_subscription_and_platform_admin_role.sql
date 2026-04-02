-- Migration 086: Company subscription/status fields + platform_super_admin role seed

-- Companies: subscription fields for platform admin control.
ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS subscription_plan TEXT NULL,
    ADD COLUMN IF NOT EXISTS subscription_status TEXT NULL,
    ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_companies_is_active ON companies(is_active);
CREATE INDEX IF NOT EXISTS idx_companies_trial_expires_at ON companies(trial_expires_at);

-- Seed platform_super_admin role (used by /api/platform-admin/* authorization).
INSERT INTO user_roles (role_name, description)
VALUES ('platform_super_admin', 'Platform super admin (cross-company platform controls)')
ON CONFLICT (role_name) DO NOTHING;

