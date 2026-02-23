# Supabase Storage Architecture – Single or Per-Tenant Project

## Master vs per-tenant Supabase

- **Single project (default):** Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the environment (e.g. on Render). This is the **master** Supabase project: same project that hosts the master DB (when using Supabase Postgres) and the **shared** `tenant-assets` bucket. All tenants’ assets (logos, stamps, PO PDFs) live in that one bucket under paths `tenant-assets/{tenant_id}/...`. No per-tenant key needed.

- **Per-tenant project (optional):** For clients that have their **own** Supabase project, store that project’s URL and service role key on the tenant row in the **master** DB. When present, storage (upload, download, signed URL) for that tenant uses their project instead of the global env. Same bucket name `tenant-assets` is used **in that project**.  
  - **Master DB migration:** Run `database/add_tenant_supabase_storage.sql` on the **master** database to add `supabase_storage_url` and `supabase_storage_service_role_key` to the `tenants` table.  
  - **Security:** Prefer encrypting the service role key at rest; restrict who can read/update these columns.

---

## Bucket Rules (per project)

| Rule | Implementation |
|------|----------------|
| **Bucket name** | `tenant-assets` |
| **Visibility** | PRIVATE |
| **Count** | One bucket per Supabase project (shared project = one bucket for all tenants; per-tenant project = one bucket in that tenant’s project) |
| **Auth** | `SUPABASE_SERVICE_ROLE_KEY` (global) or tenant’s `supabase_storage_service_role_key` when set |
| **Paths** | Never expose raw storage paths to the frontend; use signed URLs only |

The backend:

1. **Checks if the bucket exists** on first use (e.g. upload or signed URL).
2. **Creates it if missing** with `private: true`.
3. **Never creates** buckets per tenant (no `tenant-assets-{tenant_id}`).

Isolation is by **folder structure** plus **DB tenant_id** and **backend permission checks**. All tenants share the single `tenant-assets` bucket.

---

## Folder Structure (Enforced)

All files **must** follow this pattern:

```
tenant-assets/{tenant_id}/logo.png
tenant-assets/{tenant_id}/stamp.png
tenant-assets/{tenant_id}/users/{user_id}/signature.png
tenant-assets/{tenant_id}/documents/purchase_orders/{po_id}.pdf
```

- `tenant_id` and `user_id` / `po_id` are UUIDs.
- No other top-level keys; no per-tenant buckets.

---

## Security

- **Service role only**  
  Storage is accessed only with `SUPABASE_SERVICE_ROLE_KEY`. The anon key is never used for storage.

- **No raw paths to frontend**  
  Stored paths (e.g. `tenant-assets/xxx/stamp.png`) are kept in the DB and used only server-side.  
  The API returns:
  - **Stamp:** `stamp_preview_url` (signed URL) in `document_branding`; raw `stamp_url` is not sent.
  - **Signature:** `has_signature: true/false`; preview via `GET /users/{id}/signature-preview-url`.
  - **PO PDF:** `GET /purchases/order/{id}/pdf-url` returns a signed URL only.

- **Signed URLs**  
  Used for:
  - PDF retrieval (approved PO).
  - Stamp/logo preview when needed.
  - Signature preview when needed.  
  Expiry: **5–15 minutes** (default 10 min, `SIGNED_URL_EXPIRY_SECONDS`).

---

## Validation (Uploads)

- **Allowed types:** PNG, JPG (content-type `image/png`, `image/jpeg`).
- **Max size:** 2MB.
- **Checks:** file extension, content-type, and size. Invalid files are rejected with 400.

---

## Why one bucket per project

- **Single project:** 1, 100, or 10,000 pharmacies → one bucket; isolation by path and backend checks.
- **Per-tenant project:** Each client’s Supabase project has its own `tenant-assets` bucket; credentials live in the master DB tenant row.

---

## Default tenant (development / demos)

When using the **master** (default) database as the only DB — no tenant header — the app can still treat it as a tenant so that:

- Company stamp upload works
- User signature upload works
- PO approve and PDF storage work

**Requirement:** The same database must be **listed in the tenants table** in the master DB, with `database_url` equal to the app’s `DATABASE_URL`. Then, when no `X-Tenant-ID` or `X-Tenant-Subdomain` header is sent, the backend resolves this “default” tenant and uses its `tenant_id` for storage paths.

**Setup:** Run the script `database/setup_default_tenant_for_dev.sql` on the **master** database, after replacing `YOUR_DATABASE_URL` with your actual `DATABASE_URL` (same value as in `.env`). That registers the default DB as a tenant (e.g. subdomain `default`) so it can be used for development, testing, and demos.
