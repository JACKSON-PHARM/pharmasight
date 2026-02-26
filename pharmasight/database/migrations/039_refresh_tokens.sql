-- Migration 039: Refresh tokens table (per-device/session, rotation, revoke on logout)
-- Applied per tenant DB. Stores active refresh tokens for validation and one-time rotation.
-- Logout invalidates all active refresh tokens for the user in this tenant.

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jti TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    device_info TEXT,
    tenant_id UUID,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_jti ON refresh_tokens (jti);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_tenant_active ON refresh_tokens (user_id, tenant_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens (expires_at);

COMMENT ON TABLE refresh_tokens IS 'Active refresh tokens per user/tenant; rotated on use, invalidated on logout.';
