# Get Session Pooler Connection String

## Problem
Your network is IPv4-only, but Supabase Direct Connection requires IPv6. This causes connection timeouts.

## Solution: Use Session Pooler

### Step 1: Switch to Session Pooler

1. In the Supabase dashboard (where you are now):
   - Find the **"Method"** dropdown
   - Change it from **"Direct connection"** to **"Session Pooler"**

2. The connection string will update automatically

3. It should look like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.kwvkkbofubsjiwqlqakt.supabase.co:6543/postgres?pgbouncer=true
   ```
   
   Note: Port changes from `5432` to `6543` and includes `?pgbouncer=true`

### Step 2: Copy the Connection String

1. Copy the entire connection string from the text field
2. Replace `[YOUR-PASSWORD]` with your actual database password

### Step 3: Update .env File

1. Open: `C:\PharmaSight\pharmasight\.env`

2. Update the `DATABASE_URL` line:
   ```env
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.kwvkkbofubsjiwqlqakt.supabase.co:6543/postgres?pgbouncer=true
   ```

3. Save the file

### Step 4: Restart Backend

1. Stop the backend (Ctrl+C)
2. Start it again:
   ```powershell
   python start.py
   ```

### Step 5: Test Connection

Run:
```powershell
python test_db_connection.py
```

It should now connect successfully!

## Why Session Pooler?

- **IPv4 compatible**: Works on IPv4-only networks
- **Better for serverless**: Handles connection pooling automatically
- **Recommended for most apps**: Especially for cloud deployments

## Alternative: IPv4 Add-on

If you prefer Direct Connection, you can purchase the IPv4 add-on from Supabase, but Session Pooler is free and works perfectly for this use case.
