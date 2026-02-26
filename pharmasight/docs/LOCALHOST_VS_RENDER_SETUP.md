# Localhost vs Render: Why Setup Redirect Can Differ

## What you see

- **On Render:** You log in and go to the dashboard (company is operating).
- **On localhost:** You log in and get redirected to **#setup** (company setup form), as if the company doesn’t exist.

**Important:** Localhost and Render use the **same database** (Supabase). So the data (company, tenants) is shared; the difference is not “empty local DB.”

## Why it can still differ

Both environments talk to the same Supabase-backed data, but they use **different backends** and **different browser state**:

| Where you are | Frontend        | API (backend)     | Database   | Browser storage      |
|---------------|-----------------|-------------------|------------|----------------------|
| **Render**    | Render origin   | Same origin       | Supabase   | Render’s localStorage |
| **Localhost** | localhost:3000  | localhost:8000    | Supabase   | Localhost’s localStorage |

- **No shared login:** Render and localhost are different origins, so they don’t share `localStorage` or cookies. Logging in on Render doesn’t log you in on localhost, and vice versa.
- **Different backend for the check:** On localhost, the setup check (`/api/setup/status`) is sent to **your local backend** (e.g. localhost:8000). That backend uses the same Supabase DB, but its **env** (e.g. `DATABASE_URL`, master DB, tenant list) or **tenant resolution** (e.g. how it picks the tenant when the request comes from localhost) can differ from Render. If the local backend resolves to a different tenant or context, it can return “company doesn’t exist” even though the company exists in Supabase for the tenant you use on Render.
- **Back and forth:** Changing code or config to “fix” localhost can affect what the **deployed** app does on Render if that change is deployed, so behavior can flip when you switch environments.

So the issue is **which backend runs the setup check and how it resolves tenant/context**, not different or empty databases.

## How to get consistent behavior

### Option A: Use Render’s API from localhost (same backend as production)

Point the localhost frontend at Render’s API so the **same** backend (and same tenant resolution) handles the setup check. Then localhost and Render behave the same.

1. Open your app on **localhost** (e.g. `http://localhost:3000`).
2. Open DevTools → Console.
3. Run (use your real Render API URL if different):
   ```js
   localStorage.setItem('pharmasight_api_base_url', 'https://pharmasight.onrender.com');
   location.reload();
   ```
4. After reload, log in again on localhost. The app will call Render’s API; same Supabase DB and same backend logic as production → no incorrect setup redirect.

To use the **local backend** again on localhost:

```js
localStorage.removeItem('pharmasight_api_base_url');
location.reload();
```

This override is **only applied when the app is served from localhost/127.0.0.1**. Render never uses it.

### Option B: Fix local backend so it matches Render

If you want localhost to use the **local** backend and still avoid the setup redirect, make sure your local backend:

- Uses the **same** Supabase / DB config as Render (same `DATABASE_URL`, master DB, tenant DBs).
- Resolves tenant the same way (same env and logic as on Render).

Then the local backend will return the same “company exists” result as Render for the same user.

## Summary

- **Correct:** Localhost and Render use the **same** database (Supabase).
- **Cause of different behavior:** Different backend (localhost:8000 vs Render) and/or different tenant resolution / env, not a different or empty DB.
- **Fix (no code change):** On localhost, set `localStorage.pharmasight_api_base_url` to your Render URL and reload to use Render’s API from localhost. Render is not affected by this override.
