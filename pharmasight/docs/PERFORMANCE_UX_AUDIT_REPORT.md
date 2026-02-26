# PharmaSight — Performance & UX Audit Report

**Scope:** Full-stack audit of live multi-tenant ERP (Render + Supabase Postgres).  
**Focus:** Performance bottlenecks, session/auth stability, database patterns, frontend UX, and scalability.  
**Constraint:** Audit + optimization only — no business-logic refactors, no auth breakage.

---

## Executive Summary

PharmaSight is a database-per-tenant FastAPI + vanilla JS SPA with Supabase Auth (and optional internal JWT). The backend verifies JWTs locally (no per-request Supabase call); auth flow is generally sound. The main risks are:

| Area | Severity | Summary |
|------|----------|--------|
| **Items overview** | **High** | `/api/items/overview` loads all company items in one response with no pagination; frontend uses this for Inventory → Items. At 10k–20k+ items this causes slow responses, large payloads, and Render timeout risk. |
| **Dashboard API waterfall** | **Medium** | Dashboard runs 7+ sequential API calls (items count, stock count, today summary, gross profit, expiring count, stock value, order book). No parallelization; no skeleton loaders. |
| **PDF generation** | **Medium** | All PDFs (sales invoice, GRN, supplier invoice, quotation, PO, stock-take template) are generated synchronously inside the request. Cold start + PDF can exceed Render free-tier timeout. |
| **Default-tenant resolution** | **Medium** | `get_tenant_or_default()` and `_get_default_tenant()` scan all tenants when no header is sent (full table read on master DB). |
| **Session/JWT** | **Low** | JWT verification is in-process (decode only); no excessive Supabase calls. Possible double session sources (Auth legacy + AuthBootstrap) and 401 → globalLogout can feel abrupt. |
| **Frontend** | **Medium** | Re-fetch on every route/hash change; no response caching; item search has no debounce documented in central API client; Excel import polls every 2s (acceptable but bounded). |

**Quick wins:** Paginate or cap items overview; parallelize dashboard requests; add skeleton loaders; add index for default-tenant lookup; consider short cache for permissions.  
**Structural:** Move heavy PDFs to background job or async with streaming; introduce HTTP caching for reference data; optional Redis for session/tenant cache.  
**Scale (50+ users):** Address items overview and PDF first; then connection pooling and read replicas if needed.

---

## 1. Auth Flow

### 1.1 Current auth flow (high level)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ FRONTEND                                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ • AuthBootstrap.init() once on load → refreshAuthState() → getSession()     │
│   (Supabase) or getInternalAuthState() (localStorage pharmasight_*)         │
│ • On route/navigation: isAuthenticated() = AuthBootstrap.getCurrentSession() │
│   (sync, from in-memory cache when internal auth)                            │
│ • API client: every request adds Authorization: Bearer <token> from           │
│   localStorage (pharmasight_access_token or admin_token)                    │
│ • 401 response → showToast + globalLogout() → redirect to login             │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ BACKEND (per protected request)                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. get_current_user (or get_current_user_optional)                           │
│    → Extract Bearer token from Authorization header                           │
│ 2. decode_token_dual(token) → internal JWT first, else Supabase JWT          │
│    (no network call; local HMAC verify)                                      │
│ 3. Resolve tenant: token tenant_subdomain OR X-Tenant-Subdomain/ID           │
│    → master DB: Tenant lookup (by subdomain or id)                            │
│ 4. If no tenant from token/header: _get_default_tenant(master_db)             │
│    → loads ALL tenants with database_url, compares URL to DATABASE_URL     │
│ 5. Open tenant DB session (pooled per database_url)                         │
│ 6. is_token_revoked_in_db(db, jti) → SELECT 1 FROM revoked_tokens           │
│ 7. User lookup in tenant DB: User by id, deleted_at IS NULL, is_active       │
│ 8. If must_change_password → allow only change-password-first-time, logout,  │
│    auth/me                                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 How often is the session checked?

- **Frontend:** Session is read from in-memory state (AuthBootstrap) when checking auth; no repeated `getSession()` on every navigation. Initial load and invite flow call `getSession()`; AuthBootstrap also calls `getSession()` once in `refreshAuthState()` when no internal token.
- **Backend:** Every protected request runs the full `get_current_user` chain (decode JWT, tenant resolution, revocation check, user lookup). There is no backend-level “session cache” per request; each request is independent.

### 1.3 Risk points

| Risk | Location | Notes |
|------|----------|--------|
| **Double auth entry points** | `auth.js` (legacy) vs `auth_bootstrap.js` | Some code paths may still use `Auth.getCurrentUser()` which can call `supabase.auth.getUser()` and add latency or inconsistency. |
| **401 → full logout** | `api.js` (401 handler) | Any 401 triggers `globalLogout()` and redirect. Network blips or temporary 503 can look like “session expired” and clear the user out. |
| **Default tenant scan** | `dependencies.py` `_get_default_tenant()` | When no X-Tenant-* header (e.g. default/legacy DB), all tenants with `database_url` are loaded and URL-compared. Cost scales with tenant count. |
| **Token refresh** | Frontend | Internal auth uses access + refresh; refresh is used on auth/refresh endpoint. No evidence of “refresh on every N minutes” in a way that would cause excessive calls. |
| **Logout loops** | Mitigated | AuthBootstrap keeps internal auth when Supabase fires SIGNED_OUT, reducing false logout. Fail-open on setup status avoids redirect loops. |

### 1.4 Stability improvements

1. **Prefer AuthBootstrap everywhere** — Ensure no remaining callers use legacy `Auth.getCurrentUser()` / `getSession()` for “am I logged in?” so session is read from cache.
2. **Soften 401 handling** — On 401, optionally retry once with token refresh (if internal auth) before calling `globalLogout()`, and/or distinguish “invalid token” vs “server/network error” where possible.
3. **Cache default tenant** — In backend, cache the result of “default tenant” (e.g. by DATABASE_URL) in process or in a small TTL cache to avoid scanning all tenants on every unheaded request.
4. **Index tenant lookup** — Add index on `tenants(subdomain)` and `tenants(database_url)` (or expression index for default-tenant match) so that when you do need to resolve tenant, it’s a single indexed lookup where possible.

---

## 2. Database Performance (Supabase Postgres)

### 2.1 Query improvement list

| Location | Issue | Recommendation | Risk |
|----------|------|----------------|-------|
| **items.py** `get_items_overview` | Loads all items for company: `items_query.all()` with no limit. Then runs stock aggregation, last-purchase subquery, supplier lookups. | Add server-side limit (e.g. 2k–5k) or paginate (limit/offset or cursor). Expose a “total count” endpoint if needed. Frontend should use paginated list for large catalogs. | **High** |
| **items.py** `list_items` | Has limit/offset but optional; when not used, full list can be returned. | Require a default limit (e.g. 100) and max (e.g. 1000); document that overview is for “summary” and list is for paginated browsing. | **Medium** |
| **dependencies.py** `_get_default_tenant` | `master_db.query(Tenant).filter(Tenant.database_url.isnot(None)).all()` then loop to compare URLs. | Avoid full scan: add index (see below) and/or cache default tenant by DATABASE_URL. | **Medium** |
| **dependencies.py** `get_tenant_or_default` | Same pattern: iterate all tenants with database_url. | Same as above. | **Medium** |
| **sales.py** COGS path | Loads all invoices in date range with `selectinload` then loops and may call `db.query(Item)` per line when `line.item` is None. | Ensure selectinload always loads item; avoid per-line query in hot path. | **Low–Medium** |
| **item_movement_report_service** | Multiple single-row lookups (company, branch, item, opening balance, ledger rows). | Already uses single aggregated query for ledger; ensure indexes cover filters (company_id, branch_id, item_id, created_at). Index 040 exists. | **Low** |
| **pricing_service.py** | Multiple single-row lookups per item (Item, ItemPricing, CompanyMarginTier, CompanyPricingDefault). | Acceptable for single-item pricing; if called in a loop from API, consider batch API. | **Low** |
| **tenants.py** list | Paginated with offset/limit; good. | Keep; ensure index on `created_at` for ordering. | **Low** |
| **auth.py** username_login | Tenant search limited to `MAX_TENANTS_TO_SEARCH`. | Good; keep limit. | **Low** |

### 2.2 Existing indexes (relevant)

- **inventory_ledger:** `idx_inventory_ledger_company_branch_item_created` (040), `idx_inventory_ledger_item`, `idx_inventory_ledger_branch`, `idx_inventory_ledger_company`, `idx_inventory_ledger_reference`, `idx_inventory_ledger_batch`, plus batch-tracking indexes from add_batch_tracking_fields.
- **items:** From optimize_item_search_indexes: `idx_items_company_active`, `idx_items_name_lower`, `idx_items_sku_lower`, `idx_items_barcode_lower`, `idx_items_company_name_lower`, plus purchase/order item indexes and pg_trgm GIN.
- **revoked_tokens:** `idx_revoked_tokens_expires_at` (032).
- **refresh_tokens:** (039) table exists; ensure index on (user_id, is_active, expires_at) for revocation/rotation.

### 2.3 Recommended indexes (SQL only — do not auto-apply)

```sql
-- 1) Default tenant lookup (master DB): avoid full table scan when resolving tenant by database_url.
-- Only useful if you keep comparing DATABASE_URL to tenant.database_url; consider caching instead.
CREATE INDEX IF NOT EXISTS idx_tenants_database_url_not_null
  ON tenants (database_url)
  WHERE database_url IS NOT NULL;

-- 2) Tenant by subdomain (master DB) — likely already used in unique/lookup; ensure one exists.
CREATE INDEX IF NOT EXISTS idx_tenants_subdomain
  ON tenants (subdomain)
  WHERE subdomain IS NOT NULL;

-- 3) Revoked tokens jti lookup is PK; no extra index needed.

-- 4) Refresh tokens: active tokens per user (tenant/legacy DB)
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_active_expires
  ON refresh_tokens (user_id, is_active, expires_at)
  WHERE is_active = TRUE;

-- 5) Inventory ledger: batch movement report (branch + item + batch_number)
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_branch_item_batch
  ON inventory_ledger (branch_id, item_id, batch_number, created_at)
  WHERE batch_number IS NOT NULL AND batch_number != '';

-- 6) Sales invoices: branch + status + date (COGS / reporting)
CREATE INDEX IF NOT EXISTS idx_sales_invoice_branch_status_date
  ON sales_invoices (branch_id, status, batched_at);

-- 7) Supplier invoice items (purchase_invoice_items): item + created_at (last purchase lookups)
CREATE INDEX IF NOT EXISTS idx_purchase_invoice_items_item_created
  ON purchase_invoice_items (item_id, created_at DESC);
```

(Table names: `sales_invoices`, `purchase_invoice_items` — per app models.)

### 2.4 Risk level summary

- **High:** Items overview unbounded load and large payload.
- **Medium:** Default tenant full scan; sales COGS loading all invoices in range.
- **Low:** Most other queries are point lookups or already limited/indexed.

---

## 3. Render Deployment Impact

### 3.1 Cold start vulnerability

- **Free tier:** Services spin down after inactivity; first request after idle can take 30–60+ seconds. The 60s API client timeout helps avoid hanging forever but user sees long wait.
- **Impact:** Any endpoint that runs after cold start is affected. Heavier endpoints (items overview, PDF generation) are more likely to hit timeouts when combined with cold start.

### 3.2 Long-running / heavy endpoints

| Endpoint | Behavior | Recommendation |
|----------|----------|----------------|
| `GET /api/items/overview` | Loads all items + stock + suppliers | Paginate or cap; or move to background + cache. |
| `GET /api/sales/invoice/{id}/pdf` | Synchronous ReportLab PDF in request | Return 202 + job id and poll, or stream; or background worker. |
| `GET /api/purchases/grn/{id}/pdf` | Same | Same as above. |
| `GET /api/purchases/invoice/{id}/pdf` | Same | Same. |
| `GET /api/quotations/{id}/pdf` | Same | Same. |
| `POST .../purchases/order/.../approve` | Builds PO PDF, uploads to Supabase, updates DB | Best candidate for background task (approve immediately, generate PDF async). |
| `GET /api/stock-take/template/pdf` | Synchronous ReportLab | Less critical; consider caching generated template bytes. |
| Dashboard aggregates | Multiple sequential DB calls | Parallelize; consider single “dashboard summary” endpoint. |

### 3.3 Endpoints that should be async / background / cached

- **Async or background:** All “download PDF” and “approve PO (with PDF generation)” flows. Optionally stock-take template PDF generation.
- **Caching:** Dashboard summary (short TTL per branch/user); permissions per user/branch; default tenant; static or rarely changing reference data (e.g. branches list for a company).
- **Sync but bounded:** Item search (already limited); list items (with enforced limit); reports (item movement, batch movement) are read-only and index-friendly.

### 3.4 CPU-heavy work in request lifecycle

- PDF generation (ReportLab) is CPU-bound and runs in the request process. On a small instance this can block other requests and increase latency under concurrency.
- No other heavy CPU patterns were identified in the request path (e.g. no large in-memory transforms of full tables).

---

## 4. Frontend Performance

### 4.1 Re-render and data loading

- **SPA structure:** Single DOM; `loadPage(pageName)` swaps visible “page” and calls page-specific loaders (e.g. `loadDashboard()`, `loadInventory()` → `loadSubPageData()`).
- **Re-render risk:** Each navigation to a page re-runs that page’s loader and refetches data. There is no “keep previous data while refetching” or route-level cache (e.g. no in-memory cache keyed by route + branch). So: **every visit to Dashboard = 7+ API calls; every visit to Inventory (Items) = full overview fetch.**

### 4.2 Components / pages with high re-render or over-fetch risk

| Page / flow | Behavior | Suggestion |
|-------------|----------|------------|
| **Dashboard** | loadDashboard() runs when dashboard is active; multiple sequential API calls; no skeleton. | Parallelize requests (Promise.all); add skeleton placeholders for cards; optional short-lived client cache for dashboard payload per branch. |
| **Inventory → Items** | Uses API.items.overview(); full list every time. | Use paginated list API for table; use overview only for a small subset or summary; show loading state until first chunk. |
| **Settings** | May call getUserPermissions multiple times (e.g. settings.js). | Rely on Permissions cache (clearPermissionsCache on branch change); ensure single permission load per “view” where possible. |
| **Branch change** | BranchContext.onBranchChange triggers updateStatusBar and permission cache clear. | Expected; ensure only one refetch per branch change, not per component. |

### 4.3 Unnecessary or repeated API calls

- **getUserPermissions(branchId):** Called from dashboard (per card), settings, and possibly others. `utils/permissions.js` and dashboard both call it; caching exists but can be invalidated often. Consider one permission fetch per “screen” and pass down or use a small cache TTL.
- **needsPasswordSetup(user):** Calls `API.users.get(user.id)` with `_t` to bypass cache. Needed only at login/wizard; ensure not called on every navigation.
- **Items overview:** Fetched on every Inventory → Items load; no cache.

### 4.4 Missing memoization / loading states

- **Memoization:** No React; vanilla JS. “Memoization” here means: avoid re-calling the same API with same params within a short window. Not implemented for overview, dashboard, or list endpoints.
- **Skeleton loaders:** Dashboard shows “0” and “—” placeholders then fills in; no skeleton. Inventory sub-pages: loading state is minimal. Adding skeletons (e.g. for cards and tables) would improve perceived performance.
- **Blocking UI:** During load, the UI is not explicitly “blocked” by a global overlay for dashboard/inventory; the main issue is empty or stale content until requests complete.

### 4.5 UX improvement suggestions

1. **Dashboard:** Parallelize all stat API calls; show skeleton cards until data arrives; optionally cache result for 1–2 minutes per branch.
2. **Inventory Items:** Switch to paginated list API for the table; show “Loading…” or skeleton rows; avoid loading full overview when only a page of items is visible.
3. **Permissions:** Single fetch per page/screen; cache with TTL or until branch change; avoid per-card permission calls when possible.
4. **Global loading:** For heavy actions (e.g. PDF download, approve PO), show a clear “Generating…” state and disable duplicate clicks.

---

## 5. Network & API Structure

### 5.1 Payload size

- **Large responses:** `GET /api/items/overview` returns all items with stock and supplier info; payload can be megabytes for large catalogs. Other list endpoints (sales invoices, purchases) use pagination or bounded limits in some places but not for items overview.
- **Recommendation:** Paginate or cap overview; consider field selection (e.g. exclude heavy fields for list view).

### 5.2 Repeated fetching of same data

- Same dashboard data refetched on every visit; same items overview on every Inventory → Items visit; permissions refetched in multiple places (with cache). No ETag or If-None-Match; no explicit response caching headers from backend.

### 5.3 Caching headers and compression

- No audit of backend response headers (Cache-Control, ETag, Vary) was performed in codebase; typically FastAPI does not set long-lived cache headers by default. Compression (gzip) is usually handled by Render/reverse proxy; confirm it’s enabled for JSON.
- **Recommendation:** For reference data (e.g. branches, company), set short Cache-Control (e.g. 60s) and optionally ETag; consider compression for large JSON responses if not already applied at infra level.

---

## 6. User Experience Flow (Simulated)

**Path:** Login → Dashboard → Inventory → Generate report → Switch branch → Logout.

| Step | What happens | Slow transitions / duplicate calls / blocking |
|------|----------------|-----------------------------------------------|
| **Login** | Username login → tenant discovery → AuthBootstrap.init → getSession/refresh; optional needsPasswordSetup → API.users.get; branch-select or dashboard. | Tenant discovery can add a request; password-set check adds one more. 1s delay on invite flow (setTimeout) for Supabase hash. |
| **Dashboard** | loadDashboard() → 7+ sequential API calls (items count, stock count, today sales, gross profit, expiring, stock value, order book). Permission checks per card. | **Slow:** Sequential waterfall; no skeleton. **Duplicate:** Permission fetch can be shared across cards. |
| **Inventory** | loadPage('inventory') → loadInventory() → renderInventoryPage() → loadSubPageData() → for Items subpage, API.items.overview(). | **Slow:** One large overview request; table renders after full payload. **Blocking:** Table empty until overview returns. |
| **Generate report** | User opens Reports → item/batch movement; backend builds report (indexed queries). Optional PDF export (if any) would be sync. | Report build is read-only and indexed; acceptable. PDF in request would block. |
| **Switch branch** | BranchContext change → updateStatusBar; Permissions.clearPermissionsCache(); dashboard and inventory may refetch on next visit. | Expected refetch; no duplicate calls during the switch itself. |
| **Logout** | Sign out → clear storage; Supabase signOut; redirect to #login. | Minimal; no blocking. |

**Summary:** Main lag points are (1) dashboard sequential calls and no skeleton, (2) inventory items full overview and no pagination/loading state, (3) any synchronous PDF in the flow.

---

## 7. Critical Performance Issues (Ranked)

1. **Items overview unbounded** — High impact; large payload and timeout risk; fix by pagination/cap and/or separate “list” vs “overview” usage.
2. **Dashboard API waterfall** — Medium impact; slow first paint; fix by parallelizing and adding skeletons.
3. **Synchronous PDF generation** — Medium impact; risk of timeouts and blocking; fix by async/background or streaming.
4. **Default tenant full scan** — Medium impact on master DB; fix by index and/or caching default tenant.
5. **No HTTP caching for reference data** — Low–medium; fix by Cache-Control and optional ETag for branches/company.
6. **401 → immediate global logout** — UX/stability; fix by optional retry/refresh before full logout.
7. **Permissions fetched in multiple places** — Low; already partially cached; consolidate to one fetch per screen where possible.

---

## 8. Quick Wins (Safe Improvements)

- **Backend:** Enforce a maximum limit on items overview (e.g. 2000) and return a clear “truncated” or “use pagination” indicator; add `idx_tenants_subdomain` and `idx_refresh_tokens_user_active_expires`; add Cache-Control: private, max-age=60 for company/branches list endpoints if safe.
- **Frontend:** Parallelize dashboard API calls (Promise.all); add skeleton placeholders for dashboard cards and inventory table; ensure item search uses debounce (if not already in item search input handler).
- **Config:** Confirm gzip for API responses on Render; consider increasing backend timeout slightly for PDF endpoints only if you keep them sync temporarily (not a long-term fix).

---

## 9. Structural Improvements (Medium Effort)

- **Items:** New paginated “list” endpoint or enforce limit/offset on existing list; frontend Inventory Items table uses this with infinite scroll or page size; keep overview for a “summary” or small subset only.
- **PDF:** Move “download PDF” to async job (return 202 + job id, poll for URL or stream when ready); move PO-approve PDF generation to background task so approve responds immediately.
- **Dashboard:** Single “dashboard summary” endpoint that returns all stats in one DB round-trip or minimal queries; or keep multiple endpoints but always call in parallel and cache response 1–2 minutes per branch.
- **Default tenant:** Cache default tenant in process (or Redis) keyed by DATABASE_URL; invalidate on tenant update if needed.
- **Skeletons:** Add CSS/HTML skeleton components for dashboard and main tables and show them until data is ready.

---

## 10. Long-Term Scalability Recommendations

- **Read replicas:** For reporting and heavy read endpoints (e.g. item movement report), consider read replica if Supabase supports it; point report-only queries to replica.
- **Background workers:** Dedicated worker for PDF generation and other heavy jobs; use job queue (e.g. Redis, or Render background workers if available).
- **Caching layer:** Redis (or similar) for session/tenant cache, dashboard summary cache, and optional permission cache to reduce DB load.
- **Connection pooling:** Already in use (SQLAlchemy pool per tenant URL); ensure Supabase pooler (session mode) is used for all tenant connections to avoid exhausting connections.
- **Frontend:** Consider moving to a framework with built-in data fetching and cache (e.g. React Query) for clearer cache boundaries and less duplicate fetch; optional, not required for immediate scale.

---

## 11. SQL Index Recommendations (Consolidated)

Run these only after verifying table/column names against your actual schema (tenant DB vs master DB as noted).

**Master DB:**

```sql
CREATE INDEX IF NOT EXISTS idx_tenants_subdomain
  ON tenants (subdomain) WHERE subdomain IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tenants_database_url_not_null
  ON tenants (database_url) WHERE database_url IS NOT NULL;
```

**Tenant / Legacy DB:**

```sql
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_active_expires
  ON refresh_tokens (user_id, is_active, expires_at) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_inventory_ledger_branch_item_batch
  ON inventory_ledger (branch_id, item_id, batch_number, created_at)
  WHERE batch_number IS NOT NULL AND batch_number != '';

CREATE INDEX IF NOT EXISTS idx_sales_invoice_branch_status_date
  ON sales_invoices (branch_id, status, batched_at);

CREATE INDEX IF NOT EXISTS idx_purchase_invoice_items_item_created
  ON purchase_invoice_items (item_id, created_at DESC);
```

---

## 12. Caching Strategy Proposal

| What | Where | TTL | Invalidation |
|------|--------|-----|--------------|
| Default tenant (by DATABASE_URL) | Backend in-process or Redis | 5–15 min | On tenant update (or restart) |
| Dashboard summary per (branch_id, user_id) | Frontend memory or backend | 1–2 min | On branch change; optional manual refresh |
| Permissions per (user_id, branch_id) | Frontend (existing) + optional backend | Session / 5 min | On branch change; logout |
| Company / branches list | Backend or CDN | 1–5 min | On company/branch update |
| Item list (paginated) | Frontend only | No TTL or short | On create/update/delete item |
| PDFs (generated) | Storage (Supabase); signed URL | Per existing design | N/A |

---

## 13. Session Stabilization Proposal

1. **Single source of truth:** Use AuthBootstrap only for “current user/session” in the app; deprecate direct Supabase getSession/getUser for auth checks.
2. **401 handling:** On 401, if using internal auth, try refresh token once; if refresh succeeds, retry request; only then call globalLogout. For Supabase-only flows, keep current behavior or add one retry with refreshed session.
3. **No redirect inside auth listener:** Already done in AuthBootstrap (listener only updates state; no navigation). Keep it.
4. **Token refresh:** Ensure refresh is called only when access token is expired or about to expire (e.g. on 401 or a single proactive refresh before expiry), not on a fixed short interval.
5. **Multi-tab:** BroadcastChannel already syncs auth state; ensure logout in one tab clears storage and broadcasts so other tabs don’t hold stale token.

---

## 14. Deployment Tier Recommendation

- **Current (Render free tier):** Cold starts and single-instance timeouts are the main limits. Prioritize: (1) cap or paginate items overview, (2) parallelize dashboard and add skeletons, (3) move PDF to background or async.
- **Upgrade (e.g. paid Render):** Keep instance always-on to avoid cold start; consider dedicated worker for PDF and heavy jobs; add Redis for cache if you introduce server-side caching.
- **50+ users:** Same as above plus: ensure connection pooler for Supabase (session mode) for all tenant DBs; consider read replica for reports; monitor slow queries (Supabase dashboard) and add indexes as needed; consider rate limiting or throttling for expensive endpoints.

---

## 15. Risk Assessment Before Scaling to 50+ Users

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Items overview timeouts / slow responses | High | High | Paginate/cap; use list endpoint for UI. |
| PDF endpoints timeout or block other requests | Medium | High | Async/background PDF; or dedicated worker. |
| Master DB tenant scan under load | Medium | Medium | Index + cache default tenant. |
| Too many concurrent DB connections | Medium | High | Use Supabase session pooler; limit pool size per tenant. |
| Dashboard perceived lag | High | Medium | Parallelize + skeletons + optional cache. |
| 401 on transient errors causes logout | Low–Medium | Medium | Retry with refresh before globalLogout. |
| Excel import polling load | Low | Low | Keep 2s interval; cap concurrent imports per tenant. |

**Overall:** With items overview and PDF addressed, plus connection pooling and default-tenant optimization, the system is in a reasonable position to scale toward 50+ users. Continue monitoring Supabase metrics (connections, slow queries, CPU) and add caching/workers as traffic grows.

---

*End of audit report.*
