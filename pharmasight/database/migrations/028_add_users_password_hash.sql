-- Migration 028: Add password_hash for internal authentication (dual-auth with Supabase)
-- Nullable: existing users keep using Supabase Auth until they set password or reset.

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255) NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_updated_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN users.password_hash IS 'Bcrypt hash for internal auth; NULL = use Supabase Auth (dual-auth).';
COMMENT ON COLUMN users.password_updated_at IS 'When password was last set/changed (internal auth).';
