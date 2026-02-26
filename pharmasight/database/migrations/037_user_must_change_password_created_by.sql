-- Migration 037: Admin-created users (must_change_password, created_by)
-- Existing users default to must_change_password = FALSE so existing login is unchanged.

ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL;

COMMENT ON COLUMN users.must_change_password IS 'When true, user must change password on next login (admin-created users).';
COMMENT ON COLUMN users.created_by IS 'User who created this user (admin-create flow); NULL for invited or legacy users.';

-- Ensure existing rows have must_change_password = false (column default handles new rows in migration)
UPDATE users SET must_change_password = FALSE WHERE must_change_password IS NULL;
