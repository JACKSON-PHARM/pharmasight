# PharmaSight Security Implementation Summary

This document summarizes the security improvements implemented following the backend security audit. Architecture and business logic were preserved; only security hardening was applied.

---

## 1. Summary of Code Modifications

### Phase 1 – Migration endpoint (critical)

- **`app/api/migrations.py`**
  - `POST /api/admin/migrations/run` now requires **PLATFORM_ADMIN** via `Depends(get_current_admin)`.
  - Request body no longer accepts arbitrary SQL. Only a **version** field is accepted (e.g. `069_items_setup_complete`).
  - Handler calls `run_predefined_migration_by_version(database_url, version)`, which runs only SQL from files under `database/migrations/*.sql`.
  - `GET /api/admin/migrations/status` now also requires `get_current_admin`.

- **`app/services/migration_service.py`**
  - New `run_predefined_migration_by_version(database_url, version)`:
    - Resolves migration files with `_discover_migration_files()`.
    - If `version` is not in the discovered list, returns an error (no execution).
    - Reads SQL from the file and executes it on the given database URL.
    - Records the version in `schema_migrations`.

### Phase 2 – Hard-coded secrets removed

- Replaced real database passwords and project refs in docs and config with placeholders:
  - `YOUR_PASSWORD`, `db.YOUR_PROJECT_REF.supabase.co`, `postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres`.
- Updated files include: `RENDER_SETUP_CHECKLIST.md`, `RENDER_DEPLOY.md`, `QUICK_COMMANDS.md`, `GITHUB_SETUP.md`, `LOCAL_ENV_SETUP.md`, `COMPLETE_SETUP_GUIDE.md`, `SUPABASE_SETUP.md`, `DEPLOYMENT.md`, `RENDER_ENV_SETUP.md`, `render-env-variables.txt`, `database/RUN_FIX_SESSION_CODE.md`, `LOCAL_RUN_GUIDE.md`, `backend/ENV_SETUP.txt`, `test_db_connection.py`.

### Phase 3 – Utility script

- **`set_simple_password.py`**
  - Removed hard-coded email, password, and Supabase URL.
  - Email and password come from CLI (`--email`, `--password`) or env (`SET_PASSWORD_EMAIL`, `SET_PASSWORD_NEW_PASSWORD`).
  - Supabase URL from `--supabase-url` or `SUPABASE_URL`.
  - Service key still from `SUPABASE_SERVICE_KEY` (required).

### Phase 4 – Authentication on previously unauthenticated endpoints

- **`app/api/items.py`**
  - `GET /api/items/{item_id}/pricing/3tier`: added `Depends(get_current_user)`.
  - `GET /api/items/company/{company_id}`: added `Depends(get_current_user)` and company isolation (Phase 5).
- **`app/api/stock_take.py`**
  - `GET /api/stock-take/sessions/{session_id}/progress`: added `Depends(get_current_user)`.
- **`app/api/startup.py`**
  - `POST /api/startup`: added `Depends(get_current_user)`.
  - `GET /api/startup/status`: added `Depends(get_current_user)`.

### Phase 5 – Company isolation (items)

- **`app/api/items.py`**
  - `get_items_count`, `get_items_overview`, `get_items_by_company` now:
    - Resolve the current user’s company via `get_effective_company_id_for_user(db, user)`.
    - If `requested_company_id != effective_company_id`, respond with **403** and message "Access denied to this company's data."
  - Import added: `get_effective_company_id_for_user`.

### Phase 6 – Token security

- **`app/config.py`**
  - `ACCESS_TOKEN_EXPIRE_MINUTES`: default changed from 720 to **30**.
  - `REFRESH_TOKEN_EXPIRE_DAYS`: default changed from 60 to **14**.
- Refresh token rotation and logout behavior were already correct: issuing a new refresh token deactivates the previous one; logout revokes the access token and deactivates all refresh tokens for the user. No code change.

### Phase 7 – Rate limiting

- **`app/rate_limit.py`** (new)
  - Defines `Limiter(key_func=get_remote_address)` (slowapi).
- **`app/main.py`**
  - `limiter.init_app(app)` after creating the FastAPI app.
- Limits applied (per IP):
  - **Login** (`POST /api/auth/username-login`): 5/minute.
  - **Refresh** (`POST /api/auth/refresh`): 10/minute.
  - **Request password reset** (`POST /api/auth/request-reset`): 5/minute.
  - **Reset password** (`POST /api/auth/reset-password`): 5/minute.
  - **Signup** (`POST /api/onboarding/signup`): 10/hour.
  - **Invite accept** (`POST /api/invite/accept`): 10/minute.
- **`requirements.txt`**: added `slowapi==0.1.9`.

### Phase 8 – Production hardening

- **`app/config.py`**
  - Added `ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")`.
  - After loading settings, if `ENVIRONMENT == "production"` and `SECRET_KEY` is missing or still `"change-me-in-production"`, the app raises **RuntimeError** at startup (SECRET_KEY must be set in production).
- **`app/main.py`**
  - `GET /api/debug/tenants`: if `ENVIRONMENT == "production"`, responds with **404** (not found). No tenant list or debug info in production.
- **`render.yaml`**
  - Added `ENVIRONMENT: production`.
  - `CORS_ORIGINS`: set to `sync: false` so the value must be set in the Render dashboard (e.g. to the frontend domain, not `*`).
  - Comment added: in production set `CORS_ORIGINS` to the actual frontend domain.

### Phase 9 – Database defense-in-depth (RLS)

- **No RLS changes applied.** The codebase already sets `jwt.claims.company_id` in the session for the current user’s company. Migration `043_drop_single_company_enforcement.sql` references RLS and app-level company_id. Adding or changing RLS policies would require a full schema and tenant-logic review; this was left for a separate, focused change. Application-level company checks (e.g. `get_effective_company_id_for_user`, `require_document_belongs_to_user_company`) remain the primary enforcement.

---

## 2. Endpoints That Now Require Authentication

- **PLATFORM_ADMIN (admin token)**  
  - `POST /api/admin/migrations/run`  
  - `GET /api/admin/migrations/status`  

- **Company user (JWT)**  
  - `GET /api/items/{item_id}/pricing/3tier`  
  - `GET /api/items/company/{company_id}`  
  - `GET /api/items/company/{company_id}/count`  
  - `GET /api/items/company/{company_id}/overview`  
  - `GET /api/stock-take/sessions/{session_id}/progress`  
  - `POST /api/startup`  
  - `GET /api/startup/status`  

All other business endpoints that already used `Depends(get_current_user)` or `Depends(get_current_admin)` are unchanged in terms of auth.

---

## 3. Arbitrary SQL Execution Removed

- **Before:** `POST /api/admin/migrations/run` accepted a body with `migration_sql`, `version`, and optional `tenant_ids`, and executed the provided SQL on tenant DBs.  
- **After:** The same endpoint accepts only a **version** (e.g. `069_items_setup_complete`). The server runs only the corresponding predefined migration file from `database/migrations/`. No SQL from the request body is ever executed.  
- **Confirmation:** Arbitrary SQL execution from API requests has been removed.

---

## 4. Company Isolation Enforcement

- **Items:** `get_items_count`, `get_items_overview`, and `get_items_by_company` now enforce that the path parameter `company_id` equals the authenticated user’s effective company (from branch assignments). If not, the response is **403** with "Access denied to this company's data."  
- **Confirmation:** Company isolation is enforced on these endpoints. Other endpoints that take a company or branch context continue to rely on existing patterns (`get_effective_company_id_for_user`, tenant DB, RLS session variable, etc.) as before.

---

## 5. No Secrets in Repository

- Real database passwords and connection strings have been removed from documentation and replaced with placeholders (`YOUR_PASSWORD`, `YOUR_PROJECT_REF`, etc.).  
- `set_simple_password.py` no longer contains hard-coded email, password, or Supabase URL; values come from CLI or environment variables.  
- **Confirmation:** No credentials or connection strings are stored in the repo; secrets are expected from environment variables or CLI args.

---

## 6. PLATFORM_ADMIN vs COMPANY_ADMIN Separation

- **PLATFORM_ADMIN** is enforced by the **admin** interface and token: `get_current_admin` validates the admin Bearer token (from `POST /api/admin/auth/login`). Only these callers can use:
  - `POST /api/admin/migrations/run`
  - `GET /api/admin/migrations/status`
  - Other existing `/api/admin/*` routes (tenants, etc.).
- **Company-scoped** endpoints use `get_current_user` (JWT with user and company/branch context). Company isolation is enforced by comparing `company_id` (or equivalent) to the user’s effective company. Company admins and users cannot call admin-only endpoints without an admin token.  
- **Confirmation:** PLATFORM_ADMIN (admin token) and company users (JWT) are clearly separated; admin endpoints require the admin token and are not accessible with a normal user JWT.

---

## Public Endpoints (no auth)

These remain intentionally public:

- `GET /health` – health check  
- `GET /api/config` – public config (no secrets)  
- `POST /api/auth/username-login` – login (rate limited)  
- `POST /api/auth/refresh` – refresh (rate limited)  
- `POST /api/auth/request-reset` – request reset (rate limited)  
- `POST /api/auth/reset-password` – reset with token (rate limited)  
- `POST /api/auth/logout` – optional token, no auth required  
- `POST /api/onboarding/signup` – signup (rate limited)  
- `GET /api/onboarding/validate-token/{token}` – validate invite token  
- `POST /api/invite/accept` – accept invite with token (rate limited)  
- `POST /api/auth/set-password` – set password with invitation token  
- `POST /api/admin/auth/login` – admin login  

---

## Deployment Checklist

1. Set **SECRET_KEY** in production (and **ENVIRONMENT=production**).  
2. Set **CORS_ORIGINS** in Render to the frontend origin(s), e.g. `https://app.pharmasight.com`.  
3. Ensure no real credentials remain in any copied or legacy docs.  
4. Run migrations via the admin UI/API with a valid admin token, using only version identifiers for predefined migration files.
