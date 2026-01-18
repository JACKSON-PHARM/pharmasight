-- =====================================================
-- ADD USER INVITATION FIELDS
-- =====================================================
-- This migration adds fields to support user invitations
-- and password setup for new users.
-- 
-- New fields:
-- - invitation_token: Unique token for invitation link
-- - invitation_code: Simple code for invitation (alternative to link)
-- - is_pending: Whether user is pending password setup
-- - password_set: Whether user has set their password
-- - deleted_at: Soft delete timestamp
-- =====================================================

-- Add invitation fields to users table
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS invitation_token VARCHAR(255),
    ADD COLUMN IF NOT EXISTS invitation_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS is_pending BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS password_set BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_users_invitation_token ON users(invitation_token);
CREATE INDEX IF NOT EXISTS idx_users_invitation_code ON users(invitation_code);
CREATE INDEX IF NOT EXISTS idx_users_is_pending ON users(is_pending);
CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);

-- Add unique constraint on invitation_token and invitation_code
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invitation_token_unique 
    ON users(invitation_token) WHERE invitation_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invitation_code_unique 
    ON users(invitation_code) WHERE invitation_code IS NOT NULL;

-- Add comments for documentation
COMMENT ON COLUMN users.invitation_token IS 'Unique token for invitation link. Generated when user is created.';
COMMENT ON COLUMN users.invitation_code IS 'Simple invitation code (alternative to link). Generated when user is created.';
COMMENT ON COLUMN users.is_pending IS 'Whether user is pending password setup. True for newly invited users.';
COMMENT ON COLUMN users.password_set IS 'Whether user has completed password setup. Set to true after first login with password.';
COMMENT ON COLUMN users.deleted_at IS 'Soft delete timestamp. NULL means user is active, timestamp means soft deleted.';
