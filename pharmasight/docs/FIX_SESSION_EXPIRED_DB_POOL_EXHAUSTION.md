# Fix: "Session Expired" When Adding Items (Database Pool Exhaustion)

## Root Cause

Clients see "Session expired. Please log in again." when adding items to supplier invoices, but the **actual problem is not session expiry**. It is **Supabase database connection pool exhaustion**.

### What the Logs Show

```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) connection to server at 
"aws-1-eu-west-1.pooler.supabase.com" (54.247.26.119), port 5432 failed: 
FATAL: MaxClientsInSessionMode: max clients reached - in Session mode max clients are limited to pool_size
```

- **Port 5432** = Supabase **Session mode** on the shared pooler
- Session mode limits concurrent connections by `pool_size` (often 15–30 depending on tier)
- When the limit is reached, new connections are rejected → backend fails → user gets logged out or sees errors

### Why "Session Expired" Appears

1. The backend fails with `OperationalError` when it cannot get a DB connection.
2. In some code paths (auth resolution, token refresh), this can surface as **401 Unauthorized** or cause the frontend to treat the failure as an auth issue.
3. The frontend shows "Session expired. Please log in again." and triggers logout on **401** responses (`api.js`).

So the user is logged out not because their session expired, but because the database could not accept more connections.

---

## Solution: Switch to Transaction Mode (Port 6543)

### Why Transaction Mode Fixes It

| Mode           | Port | Connection behavior                          | Concurrency          |
|----------------|------|-----------------------------------------------|----------------------|
| **Session**    | 5432 | One Postgres connection per client until close| Limited by pool_size |
| **Transaction**| 6543 | Connection held only during each transaction  | Much higher          |

Transaction mode releases connections after each transaction, so many more clients can be served from the same pool.

### Step 1: Get the Transaction Mode Connection String

1. Open [Supabase Dashboard](https://supabase.com/dashboard) → your project.
2. Go to **Project Settings** → **Database**.
3. In the connection string section, select **Transaction** (or **Connection pooling** → **Transaction mode**).
4. Copy the connection string. It should look like one of:

   **If using pooler.supabase.com (IPv4):**
   ```
   postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-1-eu-west-1.pooler.supabase.com:6543/postgres?pgbouncer=true
   ```

   **If using direct connection (db.xxx.supabase.co – may require IPv6):**
   ```
   postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:6543/postgres?pgbouncer=true
   ```

### Step 2: Update Render Environment Variables

1. In [Render Dashboard](https://dashboard.render.com) → your PharmaSight web service.
2. Open **Environment**.
3. Set `DATABASE_URL` to the **transaction mode** connection string (port **6543**, with `?pgbouncer=true`).
4. If you use `MASTER_DATABASE_URL`, update it the same way.
5. Save and redeploy the service.

### Step 3: Verify

After redeploy:

- Log in and open a supplier invoice.
- Add an item. It should succeed without "Session expired".
- Check Render logs for any `OperationalError` or `MaxClientsInSessionMode` messages.

---

## Optional: Reduce Connection Usage (If Issues Persist)

If you need to stay on Session mode (5432) temporarily, lower SQLAlchemy pool usage:

In `backend/app/database.py`, `database_master.py`, and `dependencies.py`:

```python
pool_size=3,       # was 5
max_overflow=5,    # was 10
```

This reduces peak connections but can increase latency under load. **Preferred fix is switching to transaction mode.**

---

## Technical Notes

1. **Transaction mode and prepared statements**  
   Transaction mode does not support prepared statements. The app already sets `prepare_threshold=None` for pooler URLs in `dependencies.py`. Ensure `database.py` and `database_master.py` also use this when connecting via port 6543 or `pgbouncer=true`.

2. **Tenant databases**  
   If you use multiple tenants with separate `database_url` values, point them to transaction mode (6543) too, or the same limits can apply to tenant DB connections.

3. **Supabase pool size**  
   In **Database** → **Settings**, you can increase the pool size for your tier if needed. Transaction mode still usually gives better scalability for serverless and cloud deployments.

---

## Summary

| Action                               | Location              |
|--------------------------------------|------------------------|
| Use transaction mode (port 6543)     | Render `DATABASE_URL`  |
| Add `?pgbouncer=true`                 | Connection string     |
| Redeploy backend                     | Render                 |

This removes the "max clients reached" errors and the resulting "Session expired" behavior when adding items.
