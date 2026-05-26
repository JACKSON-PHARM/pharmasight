CREATE EXTENSION IF NOT EXISTS pgcrypto;

UPDATE platform_admin_users
SET email = 'sightopserp@gmail.com', updated_at = NOW()
WHERE lower(email) = 'jackmwas102@gmail.com'
  AND NOT EXISTS (
      SELECT 1 FROM platform_admin_users WHERE lower(email) = 'sightopserp@gmail.com'
  );

INSERT INTO platform_admin_users (email, password_hash, is_active)
VALUES ('sightopserp@gmail.com', NULL, TRUE)
ON CONFLICT (email) DO NOTHING;

CREATE TABLE IF NOT EXISTS platform_admin_email_change_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES platform_admin_users(id) ON DELETE CASCADE,
    new_email VARCHAR(255) NOT NULL,
    otp_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_admin_email_change_requests_admin
    ON platform_admin_email_change_requests(admin_user_id, created_at DESC);
