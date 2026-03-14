-- Migration 070: Admin impersonation audit log
-- PLATFORM_ADMIN-only impersonation: log every impersonation for security and compliance.
-- Table lives in app DB (same as companies/users). Do not use for tenant DB switching.

CREATE TABLE IF NOT EXISTS admin_impersonation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_identifier VARCHAR(255) NOT NULL,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    client_ip VARCHAR(45),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_impersonation_log_company_id ON admin_impersonation_log(company_id);
CREATE INDEX IF NOT EXISTS idx_admin_impersonation_log_user_id ON admin_impersonation_log(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_impersonation_log_started_at ON admin_impersonation_log(started_at);
CREATE INDEX IF NOT EXISTS idx_admin_impersonation_log_admin_identifier ON admin_impersonation_log(admin_identifier);

COMMENT ON TABLE admin_impersonation_log IS 'Audit log for PLATFORM_ADMIN impersonation sessions. Every impersonation must be logged.';
