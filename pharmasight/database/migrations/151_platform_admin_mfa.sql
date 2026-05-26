CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS platform_admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_admin_users_email_lower
    ON platform_admin_users(lower(email));

CREATE TABLE IF NOT EXISTS platform_admin_otp_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES platform_admin_users(id) ON DELETE CASCADE,
    otp_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_admin_otp_challenges_admin
    ON platform_admin_otp_challenges(admin_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS platform_admin_password_resets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES platform_admin_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_admin_password_resets_admin
    ON platform_admin_password_resets(admin_user_id, created_at DESC);

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
