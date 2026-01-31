-- =====================================================
-- ADD USERNAME FIELD TO USERS TABLE
-- =====================================================
-- This migration adds a username field to allow users
-- to log in with their username instead of email.
-- Email is still required for communication (password resets, etc.)
-- =====================================================

-- Add username column (unique, nullable for existing users)
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS username VARCHAR(100) UNIQUE;

-- Create index for faster username lookups
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- Add comment
COMMENT ON COLUMN users.username IS 'Unique username for login. Email is used for communication (password resets, etc.)';

-- =====================================================
-- MIGRATION NOTES:
-- =====================================================
-- 1. Existing users will have NULL username initially
-- 2. You may want to populate usernames for existing users:
--    UPDATE users SET username = LOWER(REGEXP_REPLACE(full_name, '[^a-zA-Z0-9]', '', 'g'))
--    WHERE username IS NULL AND full_name IS NOT NULL;
-- 3. New users should have username set when created
-- =====================================================
