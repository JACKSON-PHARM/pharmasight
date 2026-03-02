# Single-DB Identity Flow Audit

**Context:** The app moved from **database-per-tenant** (each tenant = own DB/Supabase project) to **one database** where clients exist as **companies**. Identity for document and user scoping must be **company, branch, item, user** — not tenant. This doc summarizes how the shift affected identity flow and what was changed so that:

- Document open/edit works without tenant headers (single-DB).
- No user signatures or data mix across companies.
- Company/branch is the source of truth for access.

---

## 1. Architecture Shift Summary

| Before (multi-tenant DB) | After (single-DB) |
|--------------------------|-------------------|
| Tenant ≈ customer; each had own DB | One app DB; tenants table optional (e.g. for storage only) |
| Isolation by **tenant + database_url** | Isolation by **company_id** (user's branches) |
| JWT/header tenant → which DB to use | No header → always app DB; company from user's branches |
| Document “open” could fail if tenant/DB mismatch | Document open/edit uses app DB + company check |

---

## 2. Current Identity Flow (After Changes)

### 2.1 Database selection (`get_tenant_db`)

- **Input:** `get_tenant_from_header(request)` → tenant or `None`.
- **Behavior:**
  - **No `X-Tenant-Subdomain` / `X-Tenant-ID`** → `get_tenant_from_header` returns **`None`** (we no longer resolve tenant from JWT when no header is sent).
  - **Tenant is `None`** or tenant has no `database_url` → session is **app DB** (`SessionLocal()`).
  - **Tenant set and has `database_url`** → session is that tenant’s DB (legacy multi-DB if still used).
- **Single-DB:** With no tenant header, every request uses the app DB; users and documents live in the same database.

### 2.2 User and company resolution (`get_current_user`)

- Resolves **user** from JWT (sub) in the chosen DB (app or tenant).
- **Company:** `get_effective_company_id_for_user(db, user)`:
  - Prefer: first branch’s `company_id` from `UserBranchRole` → `Branch`.
  - Fallback: single company in DB (`Company.limit(1)`).
- **RLS GUC:** `SET LOCAL jwt.claims.company_id = <that company_id>` so RLS (if enabled) and app logic can scope by company.

So for single-DB, **identity** is: **user** (from JWT) → **company_id** (from user’s branches) → **branch** (from context/request). Tenant is **not** used for identity.

### 2.3 Document access (get by ID / add item / PDF)

- **Company check:** After loading a document by ID (sales invoice, supplier invoice, quotation, purchase order), the API calls **`require_document_belongs_to_user_company(db, user, document, "Document")`**.
- That helper:
  - Raises **404** if `document` is `None`.
  - If the user has an effective company and `document.company_id != effective_company_id` → **404** (same as “not found” to avoid leaking existence).
- **Applied in:**
  - Get document: `get_sales_invoice`, `get_supplier_invoice`, `get_quotation`, `get_purchase_order`
  - Get PDF: `get_sales_invoice_pdf`, `get_supplier_invoice_pdf`, `get_quotation_pdf`, `get_purchase_order_pdf_url`
  - Add item: `add_quotation_item`, `add_sales_invoice_item`, `add_supplier_invoice_item`, `add_purchase_order_item`

So **opening** or **editing** a document (including add item) only succeeds if the document belongs to the authenticated user’s company. No cross-company access.

### 2.4 Tenant usage after the shift

- **Tenant** is used only when a header is sent (`X-Tenant-Subdomain` or `X-Tenant-ID`).
- **Used for:** storage paths (e.g. logo, PO PDF upload, signed URLs). When tenant is `None`, those features are skipped or return a clear error (e.g. “Tenant required for PDF URL”).
- **Not used for:** choosing which DB to use when no header is sent; not used for document visibility or company isolation.

---

## 3. Why “Open Supplier Invoice / Sales Document” Could Fail Before

Possible causes that are now addressed:

1. **Tenant required (400):** Endpoints that used `get_tenant_or_default` raised 400 when no tenant header and no default tenant. **Change:** Those document endpoints now use `get_tenant_optional` so they work without tenant; logo/PDF use tenant only when present.
2. **Wrong DB:** When no header was sent, tenant was still resolved from JWT `tenant_subdomain` and `get_tenant_db` could use that tenant’s `database_url`. If that pointed to another (or empty) project, user or document lookup could fail or return wrong data. **Change:** With no tenant header we no longer resolve tenant from JWT; `get_tenant_from_header` returns `None`, so `get_tenant_db` always uses the app DB when no header is sent.
3. **No company check:** Document was loaded by ID only; if RLS was not enabled, another company’s document could be returned. **Change:** All document get/add-item/PDF endpoints now call `require_document_belongs_to_user_company` so only the user’s company documents are accessible.

---

## 4. User / Approver / Signature Scoping (No Cross-Company Mix)

- **created_by / approver:** Loaded by ID from the same DB (e.g. `User.id == document.created_by`). In single-DB, users from multiple companies live in the same table; the **document** is already restricted to one company via `require_document_belongs_to_user_company`, and the document’s `company_id` (and usually `branch_id`) tie it to that company. So `created_by` and `approved_by_user_id` on that document are already company-scoped by association.
- **Signature / logo paths:** Stored as tenant-assets paths and resolved with `tenant` when present. Tenant is resolved from **header only** (not JWT when header is absent). So in single-DB without tenant header, signature/logo URLs are simply not generated; no mixing of assets across tenants. When tenant header is sent, it is the client’s explicit choice (e.g. one tenant per company in storage).
- **Recommendation:** When displaying or resolving approver/signature, always do it in the context of a document that has already passed `require_document_belongs_to_user_company`. No extra company filter on `User` is strictly required for security, but you can add an explicit check that the approver’s company (e.g. via their branch roles) matches the document’s company if you want defense in depth.

---

## 5. Enforced Flow (Single-DB)

1. **Request** (no tenant header) → `get_tenant_from_header` returns `None` → **app DB**.
2. **Auth** → `get_current_user` → user from app DB, **company_id** from user’s branches, **RLS GUC** set.
3. **Document by ID** → load from DB, then **`require_document_belongs_to_user_company(db, user, document, "…")`** → 404 if wrong company or missing.
4. **Add item / update / delete** → same: load document, enforce company, then mutate.
5. **Tenant** → only when header is sent; used for storage/logo/PDF URL only; not used for DB choice when header is absent.

This keeps identity on **company, branch, item, user** and avoids mixing signatures or data across companies.

---

## 6. Code References

| Area | File | Change |
|------|------|--------|
| Tenant from header | `app/dependencies.py` | `get_tenant_from_header`: no header → return `None` (do not use JWT tenant for DB). |
| Company check | `app/dependencies.py` | `require_document_belongs_to_user_company(db, user, document, name)`. |
| Sales | `app/api/sales.py` | Get invoice, get PDF, add item: use `require_document_belongs_to_user_company`. |
| Supplier invoice | `app/api/purchases.py` | Get invoice, get PDF, add item: same. |
| Quotation | `app/api/quotations.py` | Get quotation, get PDF, add item: same. |
| Purchase order | `app/api/purchases.py` | Get order, get PDF URL, add item: same. |

---

## 7. Optional: RLS for Defense in Depth

The app already sets `jwt.claims.company_id` per request. If you enable RLS on document tables (e.g. `sales_invoices`, `supplier_invoices`, `quotations`, `purchase_orders`) with a policy like:

```sql
USING (company_id = current_setting('jwt.claims.company_id', true)::uuid)
```

then the database will enforce company scope even for raw SQL. Application-level `require_document_belongs_to_user_company` remains the main guarantee when RLS is not yet enabled.

---

*Audit and fixes applied for single-DB identity flow; document open/edit and add-item should now work without tenant and stay company-scoped.*
