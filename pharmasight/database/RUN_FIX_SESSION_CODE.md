# Fix Stock Take Session Code Column Length

## Problem
The `session_code` column in `stock_take_sessions` table is `VARCHAR(6)`, but the function generates codes like "ST-MAR25A" (8 characters), causing:
```
psycopg2.errors.StringDataRightTruncation: value too long for type character varying(6)
```

## Solution
Run the migration SQL file to:
1. Alter the column from `VARCHAR(6)` to `VARCHAR(10)`
2. Update the function to ensure codes never exceed 10 characters

## How to Run

### Option 1: Supabase SQL Editor (Recommended)
1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
2. Open `database/fix_stock_take_session_code_length.sql`
3. Copy the entire contents
4. Paste into Supabase SQL Editor
5. Click **Run** (or press Cmd/Ctrl + Enter)
6. Verify success - you should see "Success. No rows returned"

### Option 2: psql Command Line
```bash
psql "postgresql://postgres:6iP.zRY6QyK8L*Z@db.kwvkkbofubsjiwqlqakt.supabase.co:5432/postgres" -f database/fix_stock_take_session_code_length.sql
```

## Verify the Fix

After running the migration, verify with this query:
```sql
SELECT 
    column_name, 
    data_type, 
    character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'stock_take_sessions' 
  AND column_name = 'session_code';
```

Expected result:
- `data_type`: `character varying`
- `character_maximum_length`: `20`

## Test the Function

Test that the function now works:
```sql
SELECT generate_stock_take_session_code();
```

This should return a code like "ST-JAN25A" (8 characters) without errors.

## Important Notes

- The column is set to VARCHAR(20) for safety margin (codes are typically 8 characters)
- The function generates codes in format: ST-{MON}{DAY}{SUFFIX} (e.g., ST-JAN25A)
- If 26 codes per day are exhausted, fallback uses timestamp format
