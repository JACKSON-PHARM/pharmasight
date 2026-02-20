# Supabase Storage Architecture – Single Bucket for All Tenants

## Bucket Rules

| Rule | Implementation |
|------|----------------|
| **Bucket name** | `tenant-assets` |
| **Visibility** | PRIVATE |
| **Count** | One bucket only; **do NOT** create per-tenant buckets |
| **Auth** | All operations use `SUPABASE_SERVICE_ROLE_KEY` only |
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

## Why One Bucket

- **1, 100, or 10,000 pharmacies** → still one bucket.
- Simple structure, no bucket proliferation.
- Tenant isolation by path and backend checks only.
