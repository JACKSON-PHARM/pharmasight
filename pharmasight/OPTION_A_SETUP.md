# Option A: Same Project (Master + Legacy)

Use the **existing** Supabase project (`kwvkkbofubsjiwqlqakt`) for both:

- **Master DB**: tenant registry, subscriptions, provisioning metadata only. Never used for operational queries.
- **Legacy / default app DB**: existing company (no tenant header). Same Postgres.

Tenant DBs (e.g. PHARMASIGHT MEDS LTD) use their **own** Supabase projects; those URLs are stored in master (`tenant.database_url`), not in env.

---

## 1. Render environment variables

In **Render → pharmasight service → Environment**, set:

| Variable | Value | Secret? |
|----------|--------|--------|
| **MASTER_DATABASE_URL** | Same Postgres URI as below (direct connection) | Yes |
| **DATABASE_URL** | `postgresql://postgres.<ref>:<password>@...supabase.co:5432/postgres` (same project) | Yes |
| **SUPABASE_URL** | `https://kwvkkbofubsjiwqlqakt.supabase.co` | No |
| **SUPABASE_KEY** | Anon (publishable) key for this project | Yes |
| **SUPABASE_SERVICE_ROLE_KEY** | Service role key for this project | Yes |
| **CORS_ORIGINS** | Your frontend origins, e.g. `https://your-app.onrender.com,http://localhost:3000` | No |
| **APP_PUBLIC_URL** | Your frontend URL, e.g. `https://your-app.onrender.com` | No |
| **DEBUG** | `False` in production | No |
| **SECRET_KEY** | Generated secret (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`) | Yes |

**Option A rule:** `MASTER_DATABASE_URL` and `DATABASE_URL` **both** point to the **same** Supabase Postgres (direct URI). Use the **direct** connection string (Settings → Database → URI), not the pooler, for migrations/provisioning.

---

## 2. Where to get the URIs and keys

- **Same project**: Supabase Dashboard → **kwvkkbofubsjiwqlqakt** (your existing project).
- **Database**: Settings → Database → **Connection string** → **URI**. Replace `[YOUR-PASSWORD]` with your DB password.
- **API**: Settings → API → **Project URL** (SUPABASE_URL), **anon** (SUPABASE_KEY), **service_role** (SUPABASE_SERVICE_ROLE_KEY).

Use that **one** project for both `MASTER_DATABASE_URL` and `DATABASE_URL`.

---

## 3. Checklist

- [ ] **MASTER_DATABASE_URL** set on Render = same project Postgres URI (direct).
- [ ] **DATABASE_URL** set on Render = same project Postgres URI.
- [ ] **SUPABASE_URL**, **SUPABASE_KEY**, **SUPABASE_SERVICE_ROLE_KEY** = same project (legacy Auth).
- [ ] **CORS_ORIGINS** and **APP_PUBLIC_URL** = your frontend URL(s).
- [ ] Redeploy the Render service after changing env vars.

---

## 4. Tenant DBs (e.g. PHARMASIGHT MEDS LTD)

Tenant databases are **not** in env. They use separate Supabase projects:

1. Create a Supabase project for the tenant (e.g. PHARMASIGHT MEDS LTD → `nlrpyprfrxqjekleaqtv`).
2. Run provisioning:
   ```bash
   cd pharmasight/backend
   python provision_tenant_db.py "PHARMASIGHT MEDS LTD" --url "postgresql://postgres:<PASSWORD>@db.nlrpyprfrxqjekleaqtv.supabase.co:5432/postgres"
   ```
3. `tenant.database_url` is stored in **master**; the app resolves it dynamically when the tenant context is present.

---

## 5. Summary

| Purpose | Source |
|--------|--------|
| Master (registry only) | **MASTER_DATABASE_URL** (same project as legacy) |
| Legacy app DB | **DATABASE_URL** (same project) |
| Tenant DBs | **tenant.database_url** in master (each tenant’s own Supabase project) |
| Legacy Supabase Auth | **SUPABASE_*** env (same project) |
