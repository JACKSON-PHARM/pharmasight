-- Fix slow users table index
-- Run this in Supabase SQL Editor

-- Step 1: Rebuild the primary key index (this is the main problem)
-- This will fix the slow index issue
REINDEX INDEX users_pkey;

-- Step 3: Insert the user manually (if it doesn't exist)
-- This bypasses the slow index during app startup
INSERT INTO users (id, email, full_name, phone, is_active)
VALUES (
    '29932846-bf01-4bdf-9e13-25cb27764c16'::UUID,
    'jackmwas102@gmail.com',
    'Jackson mwangi',
    '0708476318',
    TRUE
)
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    full_name = EXCLUDED.full_name,
    phone = EXCLUDED.phone,
    is_active = EXCLUDED.is_active;

-- Verify the user was inserted
SELECT id, email, full_name, phone, is_active 
FROM users 
WHERE id = '29932846-bf01-4bdf-9e13-25cb27764c16'::UUID;
