# Supabase storage and “Could not generate PDF URL”

The error **“Could not generate PDF URL. Check Supabase storage config (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) and Render logs.”** means the backend could not create a signed URL for the stored PO PDF. Fix it using **one** of the two approaches below.

---

## Option A: Single Supabase project (recommended for one app + one Supabase)

Use the **same** Supabase project for the master DB and for storage. No tenant table changes.

1. **On Render (backend service)** set:
   - `SUPABASE_URL` = your Supabase project URL (e.g. `https://xxxx.supabase.co`)
   - `SUPABASE_SERVICE_ROLE_KEY` = that project’s **service role** key (Project Settings → API → `service_role` secret)

2. **Redeploy** the backend.

3. If it still fails, open **Render → your service → Logs** and trigger the PDF again. The logs will show whether the client is missing or the Supabase call failed.

The **tenant DB** (the database that holds companies, orders, etc. per client) does **not** store these keys. They live only in the **app environment** (Render env vars).

---

## Option B: Per-tenant Supabase (storage key in “tenant” record)

Use a **different** Supabase project per client. The app then uses the URL and **service role key** stored on the **tenant** row in the **master** DB (same place as `database_url`), not in the tenant DB.

### 1. Master DB: add columns

The **tenants** table lives in the **master** database (the one pointed at by `DATABASE_URL` on Render). Run this **on the master DB** (e.g. in Supabase SQL Editor for the master project):

```sql
-- Run on MASTER database (where tenants table lives)
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS supabase_storage_url TEXT,
    ADD COLUMN IF NOT EXISTS supabase_storage_service_role_key TEXT;
```

File: `pharmasight/database/add_tenant_supabase_storage.sql`

### 2. Set the key for a tenant

You can set the values in either place:

**A) Admin API (PATCH tenant)**  
PATCH the tenant and send the storage URL and service role key (e.g. from your admin UI or Postman):

- `PATCH /api/admin/tenants/{tenant_id}`
- Body (JSON):  
  `{ "supabase_storage_url": "https://that-tenant-project.supabase.co", "supabase_storage_service_role_key": "eyJ..." }`

**B) SQL on master DB**

```sql
-- Replace with your tenant id/subdomain and the tenant's Supabase project URL and service_role key
UPDATE tenants
SET
  supabase_storage_url = 'https://TENANT_PROJECT_REF.supabase.co',
  supabase_storage_service_role_key = 'eyJ...'  -- service_role key from that project
WHERE id = 'tenant-uuid-here'
   OR subdomain = 'your-tenant-subdomain';
```

### 3. Behaviour

The app builds the Supabase client **per field** from tenant row, then env:

- **URL:** tenant `supabase_storage_url` if set, else **Render env** `SUPABASE_URL`.
- **Key:** tenant `supabase_storage_service_role_key` if set, else **Render env** `SUPABASE_SERVICE_ROLE_KEY`.

So you can:

- Set **both** URL and key on the tenant → that tenant uses its own Supabase project for storage.
- Set **only the key** on the tenant and leave URL blank → that tenant uses **Render’s** `SUPABASE_URL` with the tenant’s key (same project for all, key stored per tenant).
- Set **neither** → use only Render env (`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`).

**On Render you must set `SUPABASE_URL`** (and optionally `SUPABASE_SERVICE_ROLE_KEY` as fallback). If you use per-tenant keys only (URL null), the app still needs `SUPABASE_URL` so it can create signed URLs with the tenant key.

---

## Summary

| Goal | Where to set it |
|------|------------------|
| One Supabase for all tenants (PDF works for everyone) | Render env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| Different Supabase per client (key per tenant) | Master DB: run migration, then set `supabase_storage_url` and `supabase_storage_service_role_key` on the **tenants** row (via PATCH or SQL). |

The **tenant DB** (per-client database) is only for app data (companies, orders, invoices). Supabase storage keys belong in **app env** (Option A) or in the **tenants** table in the **master** DB (Option B), not in the tenant DB.
