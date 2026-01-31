# Database-per-Tenant Implementation Plan

## Goals
- **Master DB**: Unchanged. Tenant management only (tenants, invites, subscriptions, modules).
- **Default / legacy app DB**: Current `DATABASE_URL`. Existing company keeps using it. No tenant record required; "no tenant" = use this DB.
- **Tenant DBs**: New tenants (e.g. PHARMASIGHT MEDS LTD) get their **own** database. Same app schema (company, users, branches, items, etc.). Isolated data.
- **Single codebase**: Same API routes, same frontend. Only the **DB session** switches per tenant. Subscription/modules still apply per tenant.

---

## 1. Tenant Resolution (How we know “which tenant?”)

**Mechanism**: HTTP header `X-Tenant-Subdomain` (or `X-Tenant-ID`).

- **Present**: Look up tenant in master by subdomain (or id). Use `tenant.database_url` for app DB. If tenant has no `database_url` → 503 "Tenant database not provisioned".
- **Missing / empty**: **Default** → use current app DB (`DATABASE_URL`). Existing company, no code change for current usage.

**Later** (optional): Subdomain from `Host` (e.g. `acme.pharmasight.com`) when you have subdomain routing. For now, header is sufficient and works with single origin.

---

## 2. DB Access Layer

### 2.1 Keep as-is
- `get_db()` → unchanged. Still returns session for **default** app DB (current `DATABASE_URL`). Used only for default tenant path.
- `get_master_db()` → unchanged. All tenant-management and admin APIs keep using it.

### 2.2 Add `get_tenant_db()`
- **Input**: Tenant context (from header or dependency that reads it).
- **Logic**:
  - No tenant / default → return session from **default** app DB (same as `get_db()`).
  - Tenant with `database_url` → return session for that DB. Use a **pool of engines** keyed by `database_url` (or tenant id) to avoid opening new connections per request.
- **Output**: SQLAlchemy `Session` for the resolved tenant DB.

### 2.3 Engine/session pool
- One engine per distinct `database_url`. Reuse via a small registry (e.g. `tenant_engines` dict or factory). Lazy-create on first use, reuse thereafter.
- Default app DB uses the existing `engine` / `SessionLocal` from `database.py`.

---

## 3. Where to Use What

| Route group | DB | Change |
|-------------|-----|--------|
| `/api/admin/*` (tenants, invites, subscription, modules) | Master only | Keep `get_master_db()`. No change. |
| `/api/onboarding/*` validate-token, mark_invite_used | Master | Keep `get_master_db()`. No change. |
| `/api/onboarding/*` username derivation, user create | **Tenant DB** | Use `get_tenant_db()`. Tenant comes from **invite token** → tenant → `database_url`. |
| `/api/auth/*` (username-login) | **Tenant DB** | Use `get_tenant_db()`. Tenant from **header** `X-Tenant-Subdomain`. |
| `/api/startup/*`, `/api/company/*`, `/api/users/*`, items, sales, purchases, inventory, suppliers, quotations, stock-take, order-book, excel import | **Tenant DB** | Switch from `get_db` to `get_tenant_db()`. Tenant from header. |

**Summary**: All “app” APIs (company, users, auth, startup, items, sales, etc.) use **tenant DB**. Admin/onboarding (master data) use **master DB**. Onboarding user-create uses **tenant DB** from token.

---

## 4. Tenant DB Provisioning

### 4.1 When
- **New tenant creation** (e.g. admin creates tenant, or onboarding signup).  
- **Explicit “create tenant DB” step** for PHARMASIGHT MEDS LTD (and any existing tenant that should be migrated).

### 4.2 How (same Postgres instance)
1. `CREATE DATABASE pharmasight_<subdomain>;` (or similar naming).
2. Run **app schema** (`schema.sql` or equivalent) on that DB.
3. Run any **required migrations** (or same schema supports both).
4. Set `tenant.database_name` and `tenant.database_url` in **master** (connection string to that DB).  
   Use same host/user/password as default app DB, only `database` name changes.

### 4.3 Alternative (Supabase)
- Use existing `SupabaseProvisioningService` to create a **new project** per tenant when you have `SUPABASE_ACCESS_TOKEN` etc.  
- Store that project’s `database_url` on the tenant.  
- Otherwise, fallback to “same Postgres, new database” as above.

### 4.4 Default / existing company
- **No** tenant DB creation.  
- Current app DB **is** the default. When `X-Tenant-Subdomain` is missing (or “default”), use `get_db()` → default app DB.  
- Existing company continues as today.

---

## 5. PHARMASIGHT MEDS LTD Specifically

- Today: Tenant points at **same** `DATABASE_URL` as default app → duplicate email, shared data.
- **Target**:
  1. Create **new** DB (e.g. `pharmasight_pharmasightmeds`).
  2. Run app schema (+ migrations if any) on it.
  3. Update PHARMASIGHT MEDS LTD tenant in master: `database_url` = that new DB.
  4. All app traffic for that tenant (header `X-Tenant-Subdomain` = their subdomain) uses **that** DB.  
- Existing company stays on current app DB (default, no tenant header or “default”).

---

## 6. Frontend Changes

- **Tenant context**:  
  - **Default tenant** (existing company): No `X-Tenant-Subdomain` or send “default”.  
  - **PHARMASIGHT MEDS LTD / others**: Send `X-Tenant-Subdomain` (e.g. from login response, or stored after tenant-admin setup).
- **Storage**: e.g. `localStorage` / `sessionStorage` for “current tenant” subdomain (or id).  
- **API client**: Add `X-Tenant-Subdomain` (or `X-Tenant-ID`) to **all** app API requests (auth, startup, company, users, items, sales, etc.).  
- **Admin panel**: No tenant header; those APIs use master only.  
- **Login**:  
  - Login request must include tenant (header).  
  - Backend uses **tenant DB** to resolve username → email, then Supabase Auth as today.

---

## 7. Auth Flow (High Level)

1. Frontend sends login (username + password) **with** `X-Tenant-Subdomain`.
2. Backend resolves tenant from master (by subdomain). If none or no `database_url` → 503 or 404.
3. Backend uses **tenant DB** to look up user by username (or email), get email.
4. Frontend uses that email + password with Supabase Auth (unchanged).
5. Subsequent app API calls send same `X-Tenant-Subdomain`; all use **tenant DB**.

---

## 8. Onboarding / Invite Flow

- **Validate token**, **mark invite used**: master DB only (unchanged).
- **Username generation**, **user create**: Use **tenant DB** (from token → tenant → `database_url`).  
- No more “global” app DB for invite completion.  
- Frontend: After tenant-admin sets password, redirect to login. Tenant subdomain can be passed in URL or stored when loading invite setup (from token response or config).

---

## 9. What We Don’t Change

- API **route paths** and **request/response shapes**.
- Supabase Auth usage (username login → email lookup → Supabase).
- Master DB schema and admin/tenant-management APIs.
- Subscription / module checks (still per tenant, from master).  
- Overall app structure; only the **source of the DB session** (default vs tenant-specific) changes.

---

## 10. Implementation Order

1. **Tenant resolution**  
   - Middleware or dependency: read `X-Tenant-Subdomain` (and optionally `X-Tenant-ID`).  
   - Resolve tenant from master.  
   - Attach “current tenant” (or “default”) to request state.

2. **Tenant DB pool**  
   - Implement engine/session pool keyed by `database_url`.  
   - `get_tenant_db()` using that pool + default app DB when no tenant.

3. **Provisioning**  
   - Script or API: create DB, run schema, set `tenant.database_url`.  
   - Run it for PHARMASIGHT MEDS LTD and point their tenant to the new DB.

4. **Switch app APIs**  
   - Replace `get_db` with `get_tenant_db` for auth, startup, company, users, items, sales, purchases, inventory, suppliers, quotations, stock-take, order-book, excel, onboarding user-create.

5. **Frontend**  
   - Tenant context storage.  
   - Send `X-Tenant-Subdomain` (or id) on all app API calls.  
   - Default tenant: no header or “default”.

6. **Tests**  
   - Default tenant (no header) → default app DB.  
   - Tenant with header → correct tenant DB.  
   - PHARMASIGHT MEDS LTD full flow: invite → setup → login → company/branch/users/items in **their** DB only.

---

## 11. Risks / Mitigations

| Risk | Mitigation |
|------|------------|
| Connection pool growth (many tenants) | Cap pool size per engine; evict least-used tenant engines if needed. |
| Tenant DB not provisioned | Return clear 503 + message; admin provisions DB or runs migration. |
| Wrong tenant header | Validate tenant exists and is active; 404 or 403 if invalid. |
| Default vs tenant mix-up | Explicit “default” path in `get_tenant_db`; no tenant = always default DB. |

---

## 12. Summary

- **Global DB** = **master** only (tenant management).  
- **Default app DB** = current `DATABASE_URL`; existing company keeps using it.  
- **Tenant DBs** = new DB per tenant (same schema); PHARMASIGHT MEDS LTD and future tenants.  
- **One codebase**; tenant resolution + `get_tenant_db` switch DB per request.  
- **Header** `X-Tenant-Subdomain` drives tenant resolution for app APIs; default when missing.  
- **Subscription/modules** stay per tenant; same as today.

This keeps the app structure intact, isolates tenant data, and allows enterprise/customized packages per tenant without breaking existing usage.
