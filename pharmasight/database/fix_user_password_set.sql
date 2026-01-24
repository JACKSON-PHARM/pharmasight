-- =====================================================
-- FIX USER PASSWORD SET FLAG
-- =====================================================
-- This script fixes the password_set flag for users
-- so they don't have to reset password every time they log out
-- =====================================================

-- First, ensure the columns exist (if they don't, add them)
DO $$
BEGIN
    -- Add password_set column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'password_set'
    ) THEN
        ALTER TABLE users ADD COLUMN password_set BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added password_set column to users table';
    END IF;
    
    -- Add is_pending column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'is_pending'
    ) THEN
        ALTER TABLE users ADD COLUMN is_pending BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added is_pending column to users table';
    END IF;
END $$;

-- Fix specific user: jackmwas102@gmail.com
-- Set password_set = true and is_pending = false
UPDATE users
SET 
    password_set = TRUE,
    is_pending = FALSE,
    is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP
WHERE email = 'jackmwas102@gmail.com';

-- Verify the update
SELECT 
    id,
    email,
    full_name,
    password_set,
    is_pending,
    is_active,
    created_at,
    updated_at
FROM users
WHERE email = 'jackmwas102@gmail.com';

-- Optional: Fix all users who have logged in before (if they have a password in Supabase Auth)
-- This sets password_set = true for all active users who are not pending
-- Uncomment if you want to fix all users at once:
/*
UPDATE users
SET 
    password_set = TRUE,
    is_pending = FALSE
WHERE 
    is_active = TRUE 
    AND deleted_at IS NULL
    AND (password_set = FALSE OR is_pending = TRUE);
*/

COMMENT ON COLUMN users.password_set IS 'Set to TRUE after user sets their password. Users with password_set=FALSE will be prompted to set password.';
COMMENT ON COLUMN users.is_pending IS 'Set to TRUE for newly invited users. Set to FALSE after password is set.';
