# Fix Database Connection Issue

## Problem
The backend is timing out because it cannot connect to the database. The error is:
```
could not translate host name "db.kwvkkbofubsjiwqlqakt.supabase.co" to address
```

## Solution

### Step 1: Get Correct Database Connection String

1. Go to your Supabase Dashboard:
   - https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/settings/database
   - Or: Dashboard → Settings → Database

2. Find "Connection string" section

3. Look for "URI" or "Connection pooling" tab

4. Copy the connection string. It should look like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```

### Step 2: Update .env File

1. Open: `C:\PharmaSight\pharmasight\.env`

2. Update the `DATABASE_URL` line with the correct connection string:
   ```env
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
   ```

3. Or update individual components:
   ```env
   SUPABASE_DB_HOST=db.YOUR_PROJECT_REF.supabase.co
   SUPABASE_DB_PASSWORD=YOUR_PASSWORD
   ```

### Step 3: Verify Connection

Run the test script:
```powershell
cd C:\PharmaSight\pharmasight
python test_db_connection.py
```

It should show "[SUCCESS] Database connection is working!"

### Step 4: Restart Backend

1. Stop the current backend (Ctrl+C in the terminal)
2. Start it again:
   ```powershell
   python start.py
   ```

### Step 5: Try Setup Again

After the backend is running and can connect to the database, try the company setup again.

## Common Issues

- **Project paused**: Free tier projects pause after inactivity. Go to Supabase dashboard and resume it.
- **Wrong project ID**: Make sure you're using the correct project reference in the hostname.
- **Password changed**: If you changed the database password, update it in .env.

## Quick Check

To verify your Supabase project is active:
1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt
2. Check if the project is "Active" or "Paused"
3. If paused, click "Resume project"
