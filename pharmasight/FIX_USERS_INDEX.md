# Fix Users Table Index Issue

## Problem
The `users` table primary key index (`users_pkey`) is extremely slow, causing INSERT operations to timeout after 2+ minutes.

## Solution

### Option 1: Rebuild Index + Insert User (Recommended)

1. Go to Supabase SQL Editor: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new

2. Run this SQL:

```sql
-- Rebuild the primary key index
REINDEX INDEX users_pkey;

-- Rebuild the email unique index (if it exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'users_email_key') THEN
        REINDEX INDEX users_email_key;
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        NULL;
END $$;

-- Insert the user manually
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
```

3. Verify the user exists:
```sql
SELECT id, email, full_name, phone, is_active 
FROM users 
WHERE id = '29932846-bf01-4bdf-9e13-25cb27764c16'::UUID;
```

4. Then try the company setup again in the browser!

### Option 2: Drop and Recreate Index (If REINDEX doesn't work)

```sql
-- Drop the primary key constraint (this will drop the index)
ALTER TABLE users DROP CONSTRAINT users_pkey;

-- Recreate the primary key (this will create a new index)
ALTER TABLE users ADD PRIMARY KEY (id);

-- Insert the user
INSERT INTO users (id, email, full_name, phone, is_active)
VALUES (
    '29932846-bf01-4bdf-9e13-25cb27764c16'::UUID,
    'jackmwas102@gmail.com',
    'Jackson mwangi',
    '0708476318',
    TRUE
)
ON CONFLICT (id) DO NOTHING;
```

## Why This Happens

On Supabase free tier, indexes can become slow or corrupted, especially after schema changes or large operations. Rebuilding the index fixes this.

## After Fixing

Once the user is inserted and the index is rebuilt, the company setup should work normally. The app will detect the existing user and just update it if needed.
