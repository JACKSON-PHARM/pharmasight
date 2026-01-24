# 🔧 Run Database Migration - Fix Missing Columns

## Problem
The backend is trying to access columns that don't exist yet:
- `users.invitation_token`
- `users.invitation_code`
- `users.is_pending`
- `users.password_set`
- `users.deleted_at`

## Solution: Run the Migration

### Step 1: Open Supabase SQL Editor

1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
2. Or: Dashboard → SQL Editor → New Query

### Step 2: Copy the Migration SQL

Open the file: `pharmasight/database/add_user_invitation_fields.sql`

Copy the **entire contents** of that file.

### Step 3: Paste and Run

1. Paste the SQL into the Supabase SQL Editor
2. Click **Run** (or press Ctrl+Enter / Cmd+Enter)
3. Wait for "Success" message

### Step 4: Verify

After running, you should see:
- ✅ "Success. No rows returned"
- The columns should now exist in the `users` table

### Step 5: Restart Backend

1. Stop your backend server (Ctrl+C in the terminal)
2. Restart it:
   ```bash
   cd pharmasight/backend
   uvicorn app.main:app --reload
   ```

### Step 6: Test

1. Refresh your browser (hard refresh: Ctrl+Shift+R)
2. Navigate to Settings → Users & Roles
3. The page should now load without errors!

---

## Quick Copy-Paste SQL

If you want to copy directly, here's the SQL:

```sql
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS invitation_token VARCHAR(255),
    ADD COLUMN IF NOT EXISTS invitation_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS is_pending BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS password_set BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_invitation_token ON users(invitation_token);
CREATE INDEX IF NOT EXISTS idx_users_invitation_code ON users(invitation_code);
CREATE INDEX IF NOT EXISTS idx_users_is_pending ON users(is_pending);
CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invitation_token_unique 
    ON users(invitation_token) WHERE invitation_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invitation_code_unique 
    ON users(invitation_code) WHERE invitation_code IS NOT NULL;
```
