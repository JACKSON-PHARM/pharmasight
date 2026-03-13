# PharmaSight Backend Security Audit Report

**Date:** March 14, 2025  
**Scope:** Full backend security audit (AI-assisted development review)  
**Deployment context:** Render (backend), Supabase PostgreSQL (database only), internal JWT auth

---

## Executive Summary

The audit identified **critical** and **high** risk issues that should be addressed before or immediately after production use: unauthenticated execution of arbitrary SQL on all tenant databases, hard-coded credentials in documentation and scripts, default/weak secret configuration, and several API endpoints that lack authentication or proper tenant/company scoping. Rate limiting is absent. The following sections detail findings by category and risk level.

---

## 1. Critical Vulnerabilities

### 1.1 Unauthenticated Arbitrary SQL Execution (Migration API)

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/api/migrations.py` |
| **Lines** | 32–49 |
| **Risk** | Any client can POST raw SQL to be executed on **all tenant databases** (or specified tenants). No authentication or authorization. |

**Description:**  
`POST /api/admin/migrations/run` accepts `migration_sql`, `version`, and optional `tenant_ids`. The handler uses only `Depends(get_master_db)` and does **not** use `get_current_admin` or `get_current_user`. `MigrationService.run_migration_for_all_tenants()` passes the request body’s SQL to `cursor.execute(migration_sql)` on each tenant DB.

**Impact:**  
- Full compromise of every tenant database (data exfiltration, modification, or deletion).  
- Possible privilege escalation and persistence (e.g. new users, backdoors).

**Recommended fix:**  
- Require admin authentication: e.g. `_admin: None = Depends(get_current_admin)` on `run_migration`.  
- Restrict this endpoint to a dedicated admin role or separate admin-only deployment; do not expose it to the same audience as tenant APIs.  
- Consider removing “run arbitrary SQL” from the API and only allow running predefined migration files (by version id), not user-supplied SQL.

---

### 1.2 Hard-Coded Database Password in Documentation and Config Files

| Field | Detail |
|-------|--------|
| **Files** | Multiple (see list below) |
| **Risk** | Real database password appears in repo; anyone with repo access (or history) can connect to production DB. |

**Affected paths (examples):**  
Password value `6iP.zRY6QyK8L*Z` and/or full connection strings appear in:

- `pharmasight/RENDER_SETUP_CHECKLIST.md` (line 22)
- `pharmasight/LOCAL_ENV_SETUP.md` (line 21)
- `pharmasight/SUPABASE_SETUP.md` (line 80)
- `pharmasight/RENDER_DEPLOY.md` (line 69)
- `pharmasight/RENDER_ENV_SETUP.md` (lines 45, 88, 115)
- `pharmasight/render-env-variables.txt` (line 16)
- `pharmasight/LOCAL_RUN_GUIDE.md` (lines 36, 113)
- `pharmasight/DEPLOYMENT.md` (multiple lines)
- `pharmasight/COMPLETE_SETUP_GUIDE.md` (multiple lines)
- `pharmasight/QUICK_COMMANDS.md` (lines 48, 89)
- `pharmasight/database/RUN_FIX_SESSION_CODE.md` (line 26)
- `pharmasight/OPTION_A_SETUP.md` (line 60 – placeholder, but pattern is risky)
- `pharmasight/GET_SESSION_POOLER.md`, `pharmasight/FIX_DATABASE_CONNECTION.md`, etc.

**Recommended fix:**  
- Rotate the database password immediately in Supabase.  
- Replace all real passwords in docs with placeholders (e.g. `YOUR_PASSWORD`, `postgresql://...@host/db`).  
- Add repo rules and pre-commit checks to block commits containing connection strings or secrets.  
- Prefer secret references (e.g. Render secret env vars) in runbooks instead of pasting values.

---

### 1.3 Hard-Coded Credentials in Utility Script

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/set_simple_password.py` |
| **Lines** | 9–15 |
| **Risk** | Email and plaintext password and Supabase project URL hard-coded in source. |

**Description:**  
- `SUPABASE_URL = "https://kwvkkbofubsjiwqlqakt.supabase.co"`  
- `EMAIL = "jackmwas102@gmail.com"`  
- `NEW_PASSWORD = "9542"`  

**Impact:**  
- Credential theft from repo; account takeover if script is ever run against production.  
- Supabase project identifier exposed.

**Recommended fix:**  
- Remove hard-coded email, password, and URL. Use environment variables or CLI arguments.  
- Add `set_simple_password.py` to `.gitignore` if it contains local-only usage, or refactor to a generic “set password by email” script with no default credentials.  
- Rotate the password for the affected account.

---

## 2. High-Risk Vulnerabilities

### 2.1 Default SECRET_KEY in Production

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/config.py` |
| **Line** | 133 |
| **Risk** | JWT signing key defaults to `"change-me-in-production"` if `SECRET_KEY` env is unset. |

**Description:**  
```python
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
```  
If Render (or any deployment) does not set `SECRET_KEY`, tokens can be forged by an attacker who knows or guesses the default.

**Impact:**  
- Forged JWTs (arbitrary user/tenant/company_id).  
- Full authentication bypass and tenant/company impersonation.

**Recommended fix:**  
- Require `SECRET_KEY` in production (no default, or fail startup if `SECRET_KEY == "change-me-in-production"` when not in dev).  
- Ensure Render (and any other env) always sets a strong, unique `SECRET_KEY` (e.g. from `generate-secret-key.py`).

---

### 2.2 Startup and Status Endpoints Without Authentication

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/api/startup.py` |
| **Lines** | 17–19, 73–74 |
| **Risk** | Company initialization and status checks are reachable without any auth. |

**Description:**  
- `POST /api/startup` – `initialize_company(startup, db=Depends(get_tenant_db))` – no `get_current_user` or token.  
- `GET /api/startup/status` – `get_startup_status(db=Depends(get_tenant_db))` – no auth.

**Impact:**  
- Unauthenticated caller with tenant context (e.g. `X-Tenant-Subdomain` or default DB) could create or overwrite company/branch/admin data.  
- Status endpoint leaks whether a tenant DB has been initialized (information disclosure).

**Recommended fix:**  
- For `POST /api/startup`: protect with invite/setup token or short-lived JWT (e.g. from onboarding link), not only tenant DB. Do not allow unauthenticated arbitrary company creation.  
- For `GET /api/startup/status`: require valid user or at least a signed token tied to the tenant so only legitimate clients can probe initialization state.

---

### 2.3 Item and Stock-Take Endpoints Without Authentication

| Field | Detail |
|-------|--------|
| **Files** | `pharmasight/backend/app/api/items.py`, `pharmasight/backend/app/api/stock_take.py` |
| **Lines** | items.py: 789–801; stock_take.py: 1080–1082 |
| **Risk** | Unauthenticated access to item pricing and stock-take progress. |

**Description:**  
- `GET /api/items/{item_id}/pricing/3tier` – only `Depends(get_tenant_db)`; no `get_current_user`.  
- `GET /api/items/company/{company_id}` – `get_items_by_company` uses only `get_tenant_db`; no auth.  
- `GET /api/stock-take/sessions/{session_id}/progress` – `get_progress(session_id, db=Depends(get_tenant_db))` – no auth.

**Impact:**  
- Anyone who can reach the API (and optionally send tenant headers) can read 3-tier pricing for any item, list items by company, and read stock-take progress for any session.  
- Enables scraping and competitive/financial disclosure.

**Recommended fix:**  
- Add `current_user_and_db: tuple = Depends(get_current_user)` (or equivalent) to all three.  
- For `get_items_by_company`, enforce that `company_id` is one of the current user’s allowed companies (e.g. via `effective_company_id` or branch membership).

---

### 2.4 Missing Company ID Validation (Cross-Tenant / Cross-Company Data Access)

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/api/items.py` |
| **Lines** | 826–834 (get_items_count), 841–858 (get_items_overview), 1016–1044 (get_items_by_company) |
| **Risk** | Authenticated user can pass an arbitrary `company_id` in the path and read another company’s data (single-DB multi-tenant). |

**Description:**  
- `get_items_count(company_id, ...)` and `get_items_overview(company_id, ...)` use `get_current_user` but do **not** check that `company_id` equals the user’s effective company (or allowed companies).  
- `get_items_by_company(company_id, ...)` has no auth and no company check.  
- Query is `filter(Item.company_id == company_id)` with path parameter only.

**Impact:**  
- In single-DB multi-tenant, any authenticated user can enumerate or guess `company_id` and read item counts, overviews, or full item lists for other companies.  
- Violates tenant isolation.

**Recommended fix:**  
- Resolve `effective_company_id` (or allowed company set) from the current user.  
- For every endpoint that takes `company_id` in path or body, enforce `company_id in allowed_companies` (e.g. `company_id == effective_company_id` if single-company-per-user).  
- Return 403/404 when the requested company is not allowed.

---

### 2.5 Long-Lived Access Token and Refresh Token

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/config.py` |
| **Lines** | 134–137 |
| **Risk** | Access token ~12 hours; refresh token ~60 days. Stolen token gives long-lived access. |

**Description:**  
- `ACCESS_TOKEN_EXPIRE_MINUTES = 720` (~12 h)  
- `REFRESH_TOKEN_EXPIRE_DAYS = 60`  
- No evidence of token binding (e.g. device/fingerprint) or revocation list for access tokens beyond logout.

**Impact:**  
- Stolen access token: up to 12 hours of full user access.  
- Stolen refresh token: new access tokens for up to 60 days.  
- Combined with missing company checks, a stolen token can be used to access other companies’ data if the attacker knows company IDs.

**Recommended fix:**  
- Shorten access token lifetime (e.g. 15–60 minutes) and rely on refresh for long sessions.  
- Implement refresh token rotation and optional device/session listing and revoke.  
- Consider optional binding (e.g. IP or fingerprint) for high-privilege actions.

---

## 3. Medium-Risk Issues

### 3.1 Debug and Config Endpoints

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/main.py` |
| **Lines** | 87–104, 106–122 |
| **Risk** | Debug endpoint exposes tenant list when DEBUG=true; config endpoint exposes SMTP configuration flag. |

**Description:**  
- `GET /api/debug/tenants` – returns tenant count and subdomains when `settings.DEBUG` is true.  
- `GET /api/config` – returns `app_public_url`, `smtp_configured`, `api_base_url` (no secrets, but reveals whether SMTP is configured).

**Impact:**  
- If DEBUG is ever enabled in production, tenant enumeration is possible.  
- Config helps attackers know if password reset emails are available.

**Recommended fix:**  
- Disable or remove `/api/debug/tenants` in production; if kept, require admin auth and do not depend on DEBUG.  
- Ensure DEBUG is always false on Render (already default in render.yaml).  
- Accept that `/api/config` is public but avoid exposing more than necessary (e.g. no version or internal URLs).

---

### 3.2 Stripe Webhook Test Endpoint

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/api/stripe_webhooks.py` |
| **Lines** | 85–87 |
| **Risk** | `GET /api/webhooks/stripe/test` is unauthenticated and confirms webhook base URL. |

**Description:**  
Returns `{"status": "ok", "message": "Webhook endpoint is active"}` with no auth.

**Impact:**  
- Low: confirms that the Stripe webhook route exists; does not expose secrets (signature verification protects POST).  
- Slight information disclosure.

**Recommended fix:**  
- Remove in production or restrict to internal/admin only (e.g. by IP or admin token).

---

### 3.3 SQL Built from Fixed Table List (Clear-for-Reimport)

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/services/clear_for_reimport_service.py` |
| **Lines** | 70–82 |
| **Risk** | SQL is built with f-strings from a fixed list of table/where clauses; no user input in table names. |

**Description:**  
- `sql = f'DELETE FROM "{table}" WHERE {where}'` and `count_sql = f'SELECT COUNT(*) FROM "{table}" WHERE {where}'`  
- `table` and `where` come from the hardcoded `DELETIONS` list; `params` is `{"company_id": str(company_id)}` and is passed to `execute(text(...), params)`.  
- So this is **not** currently an injection bug, but the pattern is fragile.

**Impact:**  
- If future code ever allows `table` or `where` to be user-controlled, it becomes SQL injection.  
- Defense in depth: avoid building DML from string interpolation when possible.

**Recommended fix:**  
- Keep table names and where clauses in a strict whitelist (as now).  
- Prefer a single parameterized pattern (e.g. fixed queries per table keyed by name) so that adding new tables does not introduce interpolation.  
- Add a short comment in code that table/where must never come from user input.

---

### 3.4 Admin Token Store Is In-Memory Only

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/services/admin_token_store.py` |
| **Risk** | Admin tokens are stored only in process memory; they are lost on restart. |

**Description:**  
- `_admin_tokens: dict[str, float]` with 24-hour TTL.  
- No persistence; Render restarts (e.g. deploy or idle spin-down) invalidate all admin sessions.

**Impact:**  
- Not a direct security bug; admin must re-login after deploy.  
- If admin tokens were ever persisted (e.g. in DB or cache), they must be stored and transmitted securely (e.g. hashed).

**Recommended fix:**  
- Document that admin sessions do not survive restarts.  
- If persistence is added later, use secure storage and consider short TTL and revocation.

---

### 3.5 Invite/Accept and Onboarding Endpoints (Intentional Public)

| Field | Detail |
|-------|--------|
| **Files** | `pharmasight/backend/app/api/invite.py`, `pharmasight/backend/app/api/onboarding.py` |
| **Risk** | Some endpoints are public by design (invite token, signup). Token strength and expiry matter. |

**Description:**  
- `POST /api/invite/accept` – uses invitation token in body; no user JWT.  
- `POST /api/onboarding/signup` – public signup.  
- `GET /api/onboarding/validate-token/{token}` – validates token in path.

**Impact:**  
- If invite or signup tokens are guessable or long-lived, account takeover or spam signups.  
- Token in URL can leak in Referer or logs.

**Recommended fix:**  
- Ensure invite/signup tokens are cryptographically random and have short expiry.  
- Prefer POST body for token in accept flow where possible; if token must be in URL, use one-time links and short TTL.  
- Add rate limiting (see below) to signup and invite-accept to prevent abuse.

---

## 4. Low-Risk / Improvements

### 4.1 No Rate Limiting

| Field | Detail |
|-------|--------|
| **Scope** | Entire API |
| **Risk** | No application-level rate limiting; brute force, enumeration, and DoS are easier. |

**Description:**  
- No `rate_limit`, `limiter`, or similar middleware found in the codebase.  
- Login, password reset, signup, and token validation are not throttled.

**Recommended fix:**  
- Add rate limiting (e.g. by IP and optionally by user) for auth endpoints (login, refresh, request-reset, reset-password, signup, invite-accept).  
- Consider global per-IP limits and stricter limits for sensitive routes (e.g. login).  
- Use Render or a reverse proxy for DDoS protection where applicable.

---

### 4.2 Pagination and Query Limits

| Field | Detail |
|-------|--------|
| **Scope** | Various list endpoints |
| **Risk** | Some endpoints cap results (e.g. items overview 2000); others allow large limit/offset. |

**Description:**  
- Items overview: `MAX_ITEMS_OVERVIEW = 2000` – good.  
- Tenants: `limit: int = Query(100, ge=1, le=1000)` – bounded.  
- Order book and others use `limit`/`offset` with bounds; not all list endpoints have a strict maximum.

**Recommended fix:**  
- Enforce a maximum page size (e.g. 100 or 500) on all list endpoints that accept limit/offset.  
- Document limits in API docs and return clear errors when exceeded.

---

### 4.3 CORS and Health

| Field | Detail |
|-------|--------|
| **File** | `pharmasight/backend/app/main.py`, `pharmasight/render.yaml` |
| **Risk** | CORS set to `"*"` in render.yaml; health check is public. |

**Description:**  
- `CORS_ORIGINS: "*"` in render.yaml allows any origin when credentials are still required for API (mixed setup).  
- `GET /health` is unauthenticated – appropriate for Render health checks.

**Recommended fix:**  
- In production, set `CORS_ORIGINS` to the exact frontend origin(s) (e.g. `https://app.pharmasight.com`) instead of `*`.  
- Keep `/health` public for load balancer/health checks; do not expose internal details there.

---

### 4.4 RLS and Company Scoping in DB

| Field | Detail |
|-------|--------|
| **Scope** | Database |
| **Risk** | Application sets `jwt.claims.company_id`; actual RLS policies using it were not found in the audited migrations. |

**Description:**  
- `dependencies.py` sets `SET LOCAL jwt.claims.company_id` for the request.  
- Migration `043_drop_single_company_enforcement.sql` mentions “RLS and app-level company_id” but no POLICY definitions were found in the scanned SQL.  
- Tenant isolation appears to rely on application-level checks (e.g. `get_effective_company_id_for_user`, `require_document_belongs_to_user_company`) and correct use of tenant DB per request.

**Recommended fix:**  
- If using single-DB multi-tenant, consider adding RLS policies that restrict `SELECT/UPDATE/DELETE` by `current_setting('jwt.claims.company_id', true)` so that even a bug in app code cannot bypass company scope.  
- Ensure every table that holds tenant/company data has an RLS policy and that the GUC is always set when a user context is present.

---

## 5. Token Theft Impact Summary

If a valid user access or refresh token is stolen:

| Capability | With access token | With refresh token |
|------------|-------------------|---------------------|
| Act as that user until expiry | Yes (up to ~12 h) | No (use to get new access tokens) |
| Issue new access tokens | No | Yes (up to ~60 days) |
| Read/write within user’s company | Yes | Yes (after refresh) |
| Read other companies’ data | Yes, for endpoints that do not validate company_id (e.g. items by company_id) | Same |
| Change password | Yes (change-password endpoint) | No (refresh does not issue password change) |
| Create users / change permissions | Only if user has permissions | Same |
| Invalidate sessions | Yes (logout revokes token and refresh tokens) | Yes (logout) |

**Recommendations:**  
- Shorten access token lifetime; use refresh rotation.  
- Enforce company_id checks on every endpoint that takes company_id.  
- Optional: token revocation list or short-lived tokens with frequent re-auth for sensitive operations.  
- Log and alert on sensitive actions (e.g. password change, role change, bulk export).

---

## 6. Infrastructure and Deployment

- **Render:** Backend runs on Render; env vars (e.g. `DATABASE_URL`, `SECRET_KEY`) should be set in dashboard as secrets, not in repo.  
- **DEBUG:** `render.yaml` sets `DEBUG: "False"` – good; ensure it is never overridden to true in production.  
- **SECRET_KEY:** render.yaml uses `generateValue: true` – good; ensure it is a strong random value and not the default from config.  
- **Database:** Supabase PostgreSQL; connection string and credentials must come only from environment.  
- **SSL:** Supabase enforces SSL; ensure connection strings use `sslmode=require` or equivalent when required.

---

## 7. Summary Table

| Severity  | Count | Main items |
|-----------|-------|------------|
| Critical  | 3     | Unauthenticated SQL execution on all tenant DBs; hard-coded DB password in docs; hard-coded credentials in set_simple_password.py |
| High      | 5     | Default SECRET_KEY; unauthenticated startup/status; unauthenticated item/stock-take endpoints; missing company_id checks; long-lived tokens |
| Medium    | 5     | Debug/config exposure; Stripe test endpoint; clear-for-reimport SQL pattern; in-memory admin tokens; invite/onboarding token handling |
| Low       | 4     | No rate limiting; pagination limits; CORS; RLS not evident |

**Next steps (no code changes in this audit):**  
1. Fix criticals first: add admin auth to migrations run; rotate DB password and remove from docs; remove or parameterize credentials in set_simple_password.py.  
2. Require SECRET_KEY in production; add auth and company checks to startup, items, and stock-take as above.  
3. Then address high and medium items (token lifetime, rate limiting, debug/config, RLS).  
4. Re-scan after changes and before production launch.
