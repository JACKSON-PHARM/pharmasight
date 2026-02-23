# Tenants Table and Render: How It Works

## Purpose of `public.tenants` (Master DB)

The `public.tenants` table in the **master database** was designed so that:

- **Render (or any single deployment) only needs the master project’s environment variables.**
- **Tenant database URLs are not stored in Render env.** They are stored in the `tenants` table and read at runtime.
- The app connects to **one master DB** (tenant registry) and to **many tenant DBs** using URLs from that table.

So you load only the master project’s env (e.g. `DATABASE_URL`, `SECRET_KEY`, etc.) in Render; you do **not** configure each Supabase project’s URL or credentials per tenant in Render.

---

## Is It Still in Use?

**Yes.** The tenants table is still the single source of truth for:

1. **Tenant identity** – `id`, `name`, `subdomain`, `admin_email`, etc.
2. **Which database to use** – `database_url` (and `database_name`, `is_provisioned`, etc.).
3. **Access control** – `status` (trial, active, suspended, cancelled, past_due).

Flow in code:

- **Master DB connection**  
  `database_master.py` uses `MASTER_DATABASE_URL` or falls back to `settings.database_connection_string` (your single `DATABASE_URL`). That is the **only** DB URL that must be in Render env for the app to start and resolve tenants.

- **Tenant resolution**  
  When a request has `X-Tenant-Subdomain` (or `X-Tenant-ID`), `get_tenant_from_header()` runs a query against the **master** DB:

  ```text
  SELECT ... FROM tenants WHERE subdomain = :subdomain
  ```

  So the row in `public.tenants` is still what maps “harte-pharmacy-ltd” (and any tenant) to a database.

- **Tenant DB connection**  
  The app then uses `tenant.database_url` from that row to open a connection to that tenant’s database (via `_session_factory_for_url(tenant.database_url)` in `dependencies.py`). No env var per tenant is involved.

So the design “one master env on Render, all tenant DB URLs in the tenants table” is still in use and unchanged in principle.

---

## Where `database_url` Comes From

- **Not from Render env.**  
  There is no `TENANT_X_DATABASE_URL` or similar in the app.

- **Written when the tenant DB is provisioned:**
  - Admin creates a tenant (name, subdomain, admin email, etc.) → new row in `tenants` with `database_url = NULL`.
  - Admin runs “Initialize tenant database” (e.g. `POST /api/admin/tenants/{id}/initialize`) and sends the **tenant’s** Postgres URI (e.g. from that tenant’s Supabase project: Settings → Database → URI).
  - The backend runs migrations on that URL, creates the initial admin user in that DB, then sets `tenant.database_url`, `tenant.database_name`, `tenant.is_provisioned`, `tenant.provisioned_at` in the **master** DB.

So each tenant’s `database_url` is stored **once** in the master DB when that tenant’s database is initialized; Render never needs to know these URLs in its environment.

---

## What Changed Over Development (Behavior Only)

The **schema and role** of `public.tenants` did not change. The table you described (with `id`, `name`, `subdomain`, `database_url`, `status`, `admin_email`, etc.) is still the same idea and still in use.

What **did** change is **how** the app uses `tenant.database_url` when connecting from certain environments:

1. **Supabase pooler on Render (recent)**  
   Supabase’s direct connection (`db.xxx.supabase.co:5432`) uses IPv6. Render’s network could not reach it, so tenant login returned 503 “Tenant database is temporarily unreachable.”

   - **Change:** When the app runs on Render (or when `USE_SUPABASE_POOLER_FOR_TENANTS=true`), it **rewrites** the stored URL at runtime from port `5432` to port `6543` (Supabase transaction pooler), which is reachable from Render.
   - **Important:** The **stored** value in `tenants.database_url` is still the direct URI (e.g. `...@db.xxx.supabase.co:5432/postgres`). The app does not change the table; it only adjusts the URL used for the connection when creating the engine/session. So you still only load the master project’s env on Render; no new env vars per tenant.

2. **503 handling**  
   If the connection to `tenant.database_url` (after any pooler rewrite) fails (e.g. network/DNS), the app returns 503 with a clear message instead of a generic error. This does not change where the URL comes from (still `tenants`).

3. **Auth and “default” tenant**  
   For requests **without** `X-Tenant-Subdomain`, the app can treat the “legacy” DB as a tenant by matching `tenants.database_url` to the app’s `DATABASE_URL` (`get_tenant_or_default`). That still relies on the same `tenants` table and `database_url` column.

So: **table and “one master env, tenant URLs in DB” are unchanged; only connection behavior (pooler, 503, default-tenant logic) was refined.**

---

## Summary

| Question | Answer |
|--------|--------|
| Is `public.tenants` still used? | Yes. It is the registry for tenant identity and for the tenant DB URL (`database_url`). |
| Do we still use it so Render only needs master env? | Yes. Only the master DB URL is in Render env; all tenant DB URLs come from `tenants.database_url`. |
| Did the table schema or its role change? | No. Same table, same idea: one master DB, many tenant DBs, URLs stored in the table. |
| What changed? | Runtime only: optional rewrite to Supabase pooler (port 6543) on Render, better 503 handling, and default-tenant resolution; no change to where `database_url` is stored or read from. |

So the design “we loaded only the environments for the master project” is still how it works; the tenants table is still what allows Render to access every tenant’s database without loading each tenant’s Supabase env in Render.
