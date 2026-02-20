# JWT tokenization and database schema (Supabase as PostgreSQL only)

You’re using **internal auth** (username/password in your DB, JWTs issued by your backend) and **Supabase only as PostgreSQL**. This doc clarifies how JWTs work and where each set of tables lives.

---

## 1. JWT: who issues and validates

- **Supabase Auth is not used** for login, refresh, or password reset. No tokens are issued by Supabase for your app users.
- **Your FastAPI backend** issues and validates JWTs using `app/utils/auth_internal.py` and `SECRET_KEY` from env.

### 1.1 Who issues the tokens

| Token type   | Issued by              | When |
|-------------|------------------------|------|
| Access      | Your backend           | After successful `POST /api/auth/username-login` (when user has `password_hash`) |
| Refresh     | Your backend           | Same as access; used to get new access tokens via `POST /api/auth/refresh` |
| Reset       | Your backend           | When sending password-reset email; one-time use in `POST /api/auth/reset-password` |

All are **signed with `SECRET_KEY`** (from `.env` / Render), algorithm **HS256**, issuer **`pharmasight-internal`**.

### 1.2 What’s inside the JWT (claims)

- **Access / refresh** (internal):
  - `sub` – user UUID (string)
  - `email` – user email
  - `tenant_subdomain` – tenant subdomain (or null for legacy/single-tenant)
  - `type` – `"access"` or `"refresh"`
  - `exp` – expiry
  - `iss` – `"pharmasight-internal"`

- **Reset** (internal):
  - `sub` – user UUID
  - `tenant_subdomain` – tenant (or `"__default__"` for legacy)
  - `type` – `"reset"`
  - `exp`, `iss` as above

### 1.3 How the backend validates the JWT

1. **Request**: frontend sends  
   `Authorization: Bearer <access_token>`
2. **Dependency** (e.g. `get_current_user` in `app/dependencies.py`):
   - Reads `Authorization` and strips `Bearer ` to get the token.
   - Calls **`decode_token_dual(token)`** in `auth_internal.py`:
     - Tries **internal JWT** first: `decode_internal_token(token)` with `SECRET_KEY` and issuer `pharmasight-internal`.
     - If that fails and **SUPABASE_JWT_SECRET** is set, tries **Supabase JWT** (legacy): `decode_supabase_token(token)`.
   - If a payload is returned, it must have `sub` (user id).
   - **Tenant**: from token claim `tenant_subdomain` (internal) or from header `X-Tenant-Subdomain` (Supabase path).
   - Backend loads **tenant** from **master DB**, then opens that tenant’s DB and loads **user** by `sub` from the **tenant DB** (or legacy DB if no tenant).
3. **Result**: `(user, tenant_db_session)` for protected routes.

So: **normal path is internal JWT only**. Supabase JWT is only a fallback if you still have old tokens and have set `SUPABASE_JWT_SECRET`.

### 1.4 Flow summary

- **Login** → backend checks password against `users.password_hash` in DB → issues **access + refresh** (internal JWT).
- **API calls** → frontend sends **access token** in `Authorization: Bearer ...` → backend validates with `SECRET_KEY`, resolves tenant, loads user from tenant DB.
- **Refresh** → frontend sends **refresh token** to `POST /api/auth/refresh` → backend validates (internal), issues new access (and optionally refresh).
- **Password reset** → backend creates one-time **reset** token, puts it in email link; user submits token + new password to `POST /api/auth/reset-password`; backend validates reset token and updates `users.password_hash` in the correct tenant DB.

---

## 2. Database schema: one DB is both master and (default) tenant

Your app is designed so that **the master DB is also the default tenant DB**. The same physical database:

- Stores **tenant management** (tenants, invites, subscriptions).
- Stores **full app data** (companies, branches, users, items, sales, etc.) when that DB is used as the default/legacy tenant.

So everything that happens on a “tenant DB” also happens on the master DB when it is the single shared DB. There is only one set of tables: **both** master tables and app tables live in the **same** `public` schema in that one Supabase project.

### 2.1 What must exist in that one DB (Option A – single project)

| Table set | Source | Purpose |
|-----------|--------|--------|
| **Master** | `database/master_schema.sql` | `tenants`, `tenant_invites`, `subscription_plans`, `tenant_subscriptions`, `tenant_modules` |
| **App** | `database/migrations/001_initial.sql` + all other `00X_*.sql` | `companies`, `users`, `branches`, `items`, `sales_invoices`, `schema_migrations`, etc. |

- **Connection**: `DATABASE_URL` (and usually `MASTER_DATABASE_URL` is not set, so the same URL is used for both “master” and “tenant”).
- **Supabase**: In the Table Editor, choose the **public** schema. You should see **both** `tenants` (and related) **and** `companies`, `users`, `branches`, `items`, etc. in that one project.

### 2.2 Why you don’t see app tables (companies, users, branches, …)

Common causes:

1. **App migrations never run on this DB**  
   The app schema (`companies`, `users`, `branches`, …) is created only by running the migration service against that database. If you only ran `master_schema.sql` (or only created master tables), the **app** tables were never created. The backend does **not** auto-create them on first connect; something must run `run_migrations_for_url(DATABASE_URL)` (or the same URL) once.

2. **Looking in the wrong place in Supabase**  
   All app and master tables are in the **`public`** schema. In Supabase Dashboard → Table Editor, make sure you’re viewing **public**, not only `auth` or `storage`.

3. **Separate “tenant” Supabase project**  
   If you created a **second** Supabase project and added it as a tenant’s `database_url`, that project will only get app tables when **tenant provisioning** runs (e.g. “Initialize database” in admin with that project’s DB URL). Until then, that project has no tables (or only empty `public`). So for that “tenant DB” you must run the app migrations (via provisioning) to see companies, users, branches, etc.

### 2.3 How to get app tables on the shared (master = tenant) DB

You need to run the **app migrations** once against your current `DATABASE_URL` (the same DB that has your master tables). Two ways:

**A. Using the provided script (recommended)**

From `pharmasight/` or `pharmasight/backend/` with `.env` loaded (same `DATABASE_URL` as your app):

```bash
cd pharmasight
python -m pharmasight.backend.scripts.run_migrations_on_shared_db
```

Or from `pharmasight/backend/`:

```bash
cd pharmasight/backend
python scripts/run_migrations_on_shared_db.py
```

This applies all `database/migrations/00X_*.sql` files to the shared DB. You should then see `companies`, `users`, `branches`, `items`, `schema_migrations`, etc. in Supabase → Table Editor → **public**.

**A2. From Python (interactive)**

```python
from app.config import settings
from app.services.migration_service import run_migrations_for_url

run_migrations_for_url(settings.database_connection_string)
```

**B. From command line (psql or Supabase SQL editor)**

Not ideal for many files; prefer (A). If you do it manually, run in order the contents of:

- `pharmasight/database/migrations/001_initial.sql`
- then `002_*.sql`, `003_*.sql`, … through `028_*.sql`

against the **same** database that you use as `DATABASE_URL` (and that already has `tenants`, etc.).

After migrations run successfully, in Supabase → **public** you should see `schema_migrations` plus `companies`, `users`, `branches`, `items`, `sales_invoices`, and the rest of the app schema.

### 2.4 Quick reference

| Table set | Same DB (Option A) | Separate tenant DB |
|-----------|--------------------|---------------------|
| tenants, tenant_invites, subscription_plans, tenant_subscriptions, tenant_modules | ✅ In the one project (master_schema.sql) | ❌ Only in master project |
| companies, users, branches, items, sales_invoices, … | ✅ In the one project (run app migrations on DATABASE_URL) | ✅ After provisioning (run_migrations_for_url(tenant.database_url)) |

So: **JWT is fully handled by your backend.** **Supabase is only PostgreSQL.** In your design, the **master DB is also the viable tenant DB**; that one DB must have **both** master tables and app tables. If you don’t see app tables there or in a tenant project, run the app migrations for that database (shared DB or tenant DB) as above.
