-- Migration 038: Minimal audit log for tenant-level admin actions (e.g. admin_create_user)

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type VARCHAR(64) NOT NULL,
    performed_by UUID NOT NULL,
    target_user_id UUID,
    tenant_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    request_ip VARCHAR(64)
);

COMMENT ON TABLE admin_audit_log IS 'Minimal audit for admin actions; e.g. admin_create_user. No event bus or framework.';

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_tenant_created ON admin_audit_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action ON admin_audit_log(action_type);
