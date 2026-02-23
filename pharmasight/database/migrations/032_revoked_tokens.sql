-- Migration 032: Revoked tokens table (server-side logout per tenant/legacy DB)
-- Each tenant DB and the legacy DB store their own revoked JTIs so the tenant DB
-- is the source of truth for its users' sessions (same as password_hash in users).

CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti VARCHAR(64) PRIMARY KEY,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires_at ON revoked_tokens (expires_at);

COMMENT ON TABLE revoked_tokens IS 'Revoked JWT IDs (jti) for server-side logout; prune by expires_at periodically.';
