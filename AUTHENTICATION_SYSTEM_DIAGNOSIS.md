# PharmaSight — Full Authentication System Diagnosis

**Purpose:** Prepare for removing Supabase Auth and replacing with fully internal authentication (password hashing + JWT in FastAPI).  
**Constraints:** Application is LIVE; users must not notice any change; no downtime; no forced logout; no forced password reset; Supabase remains only as PostgreSQL.

---

## PHASE 1 — COMPLETE AUTH FLOW TRACE

### 1.1 Current login flow (step-by-step)

| Step | Location | What happens |
|------|----------|--------------|
| 1 | **Frontend** `pharmasight/frontend/js/pages/login.js` | User submits login form (username + password). Form handler in `form.onsubmit` (≈ line 262). |
| 2 | **Frontend** `login.js` | If username is `admin`, branch to admin login: `POST /api/admin/auth/login`; store `admin_token` and redirect to `/admin.html`. |
| 3 | **Frontend** `login.js` | For regular user: `POST /api/auth/username-login` with `{ username, password }`. **No tenant header**; no `Authorization` header. |
| 4 | **Backend** `pharmasight/backend/app/api/auth.py` → `username_login()` | Resolves tenant from `get_tenant_from_header` (optional). Looks up user by username (or email if `@` in input) in tenant DB or discovers tenant by searching all tenant DBs. **Does not verify password.** Returns `UsernameLoginResponse`: `email`, `user_id` (local `users.id`), `username`, `full_name`, `tenant_subdomain`. |
| 5 | **Frontend** `login.js` | On 200: stores `tenant_subdomain` in `sessionStorage` and `localStorage` (`pharmasight_tenant_subdomain`), stores `pharmasight_username` in localStorage. |
| 6 | **Frontend** `login.js` | Calls `AuthBootstrap.signIn(userEmail, password)` with the **email** returned from backend. |
| 7 | **Frontend** `pharmasight/frontend/js/services/auth_bootstrap.js` → `signIn()` | Calls `supabaseClientInstance.auth.signInWithPassword({ email, password })`. |
| 8 | **Supabase Auth** | Validates password and returns session (access_token, refresh_token, user). |
| 9 | **Frontend** | Supabase JS client stores session in **localStorage** (default Supabase behavior). `CONFIG.USER_ID = data.user.id` (Supabase UID). `AuthBootstrap.refresh()` runs; `onAuthStateChange` updates cached user/session. |
| 10 | **Frontend** | Renders app layout, may redirect to password-set or branch-select; `loadPage('branch-select')` or dashboard. |

**Where username login starts:** `pharmasight/frontend/js/pages/login.js` — form `#loginForm` submit handler.  
**How email is resolved:** Backend `auth.py` → `username_login()` looks up user by username/email in tenant DB(s) and returns `email` in the response.  
**Where Supabase signIn is called:** `auth_bootstrap.js` → `signIn(email, password)` → `supabaseClientInstance.auth.signInWithPassword({ email, password })`.  
**What is returned to frontend from backend:** From `/api/auth/username-login`: `email`, `user_id`, `username`, `full_name`, `tenant_subdomain`. From Supabase (client-side): session object with `user`, `access_token`, `refresh_token`.  
**What is stored in localStorage/sessionStorage:**  
- `pharmasight_tenant_subdomain` (sessionStorage + localStorage)  
- `pharmasight_username` (localStorage)  
- Supabase session (localStorage, by Supabase client: keys like `sb-<project>-auth-token`)  
- `CONFIG.USER_ID` in memory (and possibly persisted elsewhere)  
- Admin: `admin_token`, `is_admin` (localStorage)  

**How token is attached to API requests:** **It is not.** The app API client in `pharmasight/frontend/js/api.js` only adds:  
- `Content-Type: application/json`  
- `X-Tenant-Subdomain` (when `pharmasight_tenant_subdomain` is set)  
There is **no** `Authorization: Bearer <token>` (or any JWT) sent to backend for tenant app APIs.

---

### 1.2 Token validation flow (backend)

- **Where is JWT verified?** **Nowhere** for tenant app routes. No backend code verifies a JWT for `/api/items`, `/api/sales`, `/api/users`, etc.  
- **What library verifies Supabase JWT?** Not used on backend for tenant auth.  
- **Signature / decode / issuer / audience:** N/A — no JWT verification on tenant APIs.  
- **get_current_user:** **Does not exist** for tenant APIs. No dependency that extracts “current user” from a token.  
- **Tenant resolution during authenticated requests:** Done only via **headers**: `get_tenant_from_header()` in `pharmasight/backend/app/dependencies.py` reads `X-Tenant-Subdomain` or `X-Tenant-ID`, looks up tenant in **master DB**, then `get_tenant_db()` yields a DB session for that tenant’s DB (or legacy/default DB if no header). No user identity is validated; only tenant context is set.

**Summary:** Tenant APIs are **not** protected by JWT. They are protected only by the frontend not calling them until the user has a Supabase session. Backend trusts `X-Tenant-Subdomain` (or `X-Tenant-ID`) for tenant selection and does not verify who the user is.

---

### 1.3 All Supabase dependencies (file paths + function names)

| Area | File(s) | Usage |
|------|---------|--------|
| **Frontend – client init** | `pharmasight/frontend/js/services/supabase_client.js` | `initSupabaseClient()` — `supabase.createClient(supabaseUrl, supabaseAnonKey)`. |
| **Frontend – auth** | `pharmasight/frontend/js/auth.js` | `getClient()` → `initSupabaseClient()`; `getCurrentUser()` → `supabaseClient.auth.getUser()`; `getCurrentSession()` → `getSession()`; `signIn()` → `signInWithPassword()`; `signOut()` → `signOut()`; `onAuthStateChange()` → `auth.onAuthStateChange()`. |
| **Frontend – auth bootstrap** | `pharmasight/frontend/js/services/auth_bootstrap.js` | Same client; `refreshAuthState()` → `getSession()`; `signIn()` → `signInWithPassword()`; `signOut()`; `updatePassword()` → `auth.updateUser({ password })`; `onAuthStateChange`. |
| **Frontend – login** | `pharmasight/frontend/js/pages/login.js` | `AuthBootstrap.signIn(userEmail, password)`; `sendUnlockLinkForUsername()` → `supabase.auth.resetPasswordForEmail(email, { redirectTo })`. |
| **Frontend – password reset** | `pharmasight/frontend/js/pages/password_reset.js` | `supabase.auth.resetPasswordForEmail(email, { redirectTo })`; after token in URL: `supabase.auth.getSession()` then `supabase.auth.updateUser({ password })`; then `signOut()`. |
| **Frontend – password set** | `pharmasight/frontend/js/pages/password_set.js` | `AuthBootstrap.updatePassword(newPassword)` (Supabase `updateUser({ password })`). |
| **Frontend – settings** | `pharmasight/frontend/js/pages/settings.js` | “Send reset link” → `supabase.auth.resetPasswordForEmail(email, { redirectTo })`. |
| **Frontend – items** | `pharmasight/frontend/js/pages/items.js` | “Verify password” flow: `supabase.auth.signInWithPassword({ email: userEmail, password })`. |
| **Frontend – app shell** | `pharmasight/frontend/js/app.js` | `initSupabaseClient()`; `supabaseClient.auth.getSession()` for auth check; routing and recovery token handling (`access_token`, `type=recovery`). |
| **Frontend – session timeout** | `pharmasight/frontend/js/utils/session_timeout.js` | On timeout: `supabase.auth.signOut()`. |
| **Backend – invite service** | `pharmasight/backend/app/services/invite_service.py` | `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)`; `invite_admin_user()` → `auth.admin.create_user()`, `auth.admin.invite_user_by_email()`; `create_user_with_password()` → `auth.admin.create_user(payload)`; `update_user_password()` → `auth.admin.update_user_by_id(uid, {"password": password})`; `update_user_metadata()`, `mark_setup_complete()`; `_find_auth_user_by_email()` / `_find_auth_user_by_email_http()` (Auth Admin API). |
| **Backend – config** | `pharmasight/backend/app/config.py` | `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and DB-related Supabase env vars. |
| **Backend – tenants** | `pharmasight/backend/app/api/tenants.py` | `is_supabase_owner_email(tenant_data.admin_email)` to block owner email as tenant admin. |
| **Backend – provisioning** | `pharmasight/backend/app/services/supabase_provisioning.py` | Management API (Bearer token); not Auth. |
| **Backend – onboarding** | `pharmasight/backend/app/api/onboarding.py` | `InviteService.create_user_with_password()` for tenant-invite completion. |
| **Backend – users** | `pharmasight/backend/app/api/users.py` | `InviteService.invite_admin_user()` when creating user (invite email). |
| **External** | `pharmasight/frontend/index.html` | Script: `@supabase/supabase-js@2`. |
| **External** | `pharmasight/backend/requirements.txt` | `supabase==2.0.0`. |

**Summary:**  
- **Frontend:** One Supabase client (`supabase_client.js`); used for sign-in, sign-out, getSession/getUser, updatePassword, resetPasswordForEmail, onAuthStateChange. Session stored in localStorage by Supabase.  
- **Backend:** Invite/create/update password and metadata via `InviteService` (Supabase Admin Auth API). No backend JWT verification for tenant app.

---

## PHASE 2 — DATABASE AUTH STRUCTURE ANALYSIS

### 2.1 Users table schema (tenant DBs)

**Source:** `pharmasight/database/migrations/001_initial.sql`, `002_add_user_username_and_invitation.sql`.

- **id:** UUID PRIMARY KEY (no default in 001; intended to match Supabase Auth user id where linked).  
- **email:** VARCHAR(255) NOT NULL UNIQUE.  
- **username:** VARCHAR(100) UNIQUE (nullable) — added in 002.  
- **full_name, phone, is_active, created_at, updated_at:** standard.  
- **invitation_token:** VARCHAR(255) UNIQUE nullable (002).  
- **invitation_code:** VARCHAR(50) UNIQUE nullable (002).  
- **is_pending:** BOOLEAN DEFAULT FALSE (002).  
- **password_set:** BOOLEAN DEFAULT FALSE (002).  
- **deleted_at:** TIMESTAMPTZ nullable (002).

**There is no `password_hash` column.**  
**There is no `supabase_user_id` column** — the design uses `users.id` as the link (same as Supabase Auth UID when linked).  
**Email:** UNIQUE. **Username:** UNIQUE.  
**Constraints:** PK on `id`; unique on `email`, `username`; unique partial indexes on `invitation_token` and `invitation_code` where not null.

### 2.2 Migrations history (auth-related)

- **001_initial.sql:** Initial schema; `users` with `id`, `email`, no username, no password column.  
- **002_add_user_username_and_invitation.sql:** Added `username`, `invitation_token`, `invitation_code`, `is_pending`, `password_set`, `deleted_at`. No `password_hash`; no removal of auth fields.  
- No migration introduces Supabase by name; Supabase is used at app level. No legacy password column in tenant schema.

### 2.3 Supabase user ID usage and mapping

- **Are we storing Supabase user IDs?** Yes, **as `users.id`** when the user is created/linked to Supabase:  
  - **Tenant invite (onboarding):** `onboarding.py` → `complete_tenant_invite` creates local `User` with `id=uid` where `uid` is the Supabase Auth user ID returned from `InviteService.create_user_with_password()`.  
  - **In-app invite (settings):** `users.py` creates local user with a **temporary UUID** and then calls `InviteService.invite_admin_user()`. Comment says “Supabase Auth user_id will be linked when user sets password” but **no code found updates the local user’s `id` to the Supabase UID**. So in-app invited users may have local `users.id` = temp UUID and Supabase Auth UID different; `API.users.get(session.user.id)` would then 404 for them.  
- **Mapping:** For tenant-invite flow, local `users.id` = Supabase Auth UID. For in-app invite, design intent is “link on first login/set password” but the link step is not implemented.  
- **Foreign keys:** `user_branch_roles.user_id`, `inventory_ledger.created_by`, etc. reference `users.id`. No separate `supabase_user_id` column; the single `id` is used as the link when applicable.

---

## PHASE 3 — SESSION & TENANT RESOLUTION ANALYSIS

### 3.1 How tenant is determined

- **From header:** Yes. `get_tenant_from_header()` in `dependencies.py` reads `X-Tenant-Subdomain` or `X-Tenant-ID`.  
- **From JWT:** No. Backend does not read or validate JWT for tenant APIs.  
- **From subdomain:** No. Tenant is not derived from hostname in the code; frontend sends `X-Tenant-Subdomain` from stored value (from login or invite URL).  
- **From database lookup:** Only for **resolution**: given subdomain or tenant ID, master DB `tenants` table is queried to get `Tenant` and `database_url`. No DB lookup of “which tenant does this user belong to” on every request — that discovery happens only at login (`username_login` when no tenant header).

### 3.2 Is tenant ID embedded in Supabase JWT?

Supabase JWTs typically contain `sub` (user UID), `email`, etc. Tenant/subdomain is **not** added by the app to the Supabase JWT. The app does not read JWT on backend for tenant APIs, so this is moot for current behavior.

### 3.3 Are we trusting frontend headers?

Yes. Tenant is taken solely from `X-Tenant-Subdomain` or `X-Tenant-ID`. Any client that sends a valid tenant header gets a DB session for that tenant. There is no verification that the authenticated user belongs to that tenant.

### 3.4 What prevents cross-tenant access today?

- **Frontend:** Only sends `X-Tenant-Subdomain` after login (or invite), and only shows app when Supabase session exists. So in normal use, the header matches the logged-in user’s tenant.  
- **Backend:** Nothing. There is no check that “this request is from user X and user X is in tenant Y.” So anyone who can send requests with a chosen `X-Tenant-Subdomain` (e.g. another tenant’s subdomain) could theoretically access that tenant’s data. Mitigation is only by not exposing the API to untrusted clients and by frontend not sending wrong tenant.

### 3.5 Request lifecycle: Incoming HTTP request → DB session

1. Request hits FastAPI (e.g. `GET /api/items/...`).  
2. Route depends on `get_tenant_db`.  
3. `get_tenant_db` depends on `get_tenant_from_header`.  
4. `get_tenant_from_header(request, db=get_master_db)` reads `X-Tenant-Subdomain` / `X-Tenant-ID`, queries **master** DB for `Tenant`, validates status and `database_url`.  
5. If no header: `tenant is None` → `get_tenant_db` yields **legacy/default** DB session (`SessionLocal()`).  
6. If header present and tenant found: `get_tenant_db` yields session from pool for `tenant.database_url`.  
7. No step extracts or validates a user or JWT.

---

## PHASE 4 — PASSWORD & RESET FLOW

### 4.1 Password reset implementation

- **Supabase magic link:** Yes. “Forgot password” and “unlock” flows call `supabase.auth.resetPasswordForEmail(email, { redirectTo })`. User gets Supabase email with link that lands with `#access_token=...&type=recovery`.  
- **Custom reset endpoint:** Backend has no custom “reset password” endpoint for tenant users. Reset is entirely Supabase (request email + set new password via Supabase session).  
- **SMTP:** Supabase sends the email (Supabase project email config). App has SMTP settings for other uses (e.g. tenant invites) but password reset email is Sent by Supabase.

**Locations:**  
- Request reset: `login.js` `sendUnlockLinkForUsername()`, `password_reset.js` form submit, `settings.js` “Send reset link”.  
- Handle recovery link: `password_reset.js` — when URL has `access_token` and `type=recovery`, show new password form; then `supabase.auth.updateUser({ password })`, then `API.users.update(userId, { password_set: true })`, then `signOut()` and redirect to login.

### 4.2 Where password hashing happens

- **Supabase:** Passwords are hashed and stored in Supabase Auth (e.g. `auth.users`). The app never sees the hash.  
- **Backend:** Only admin auth has local hashing: `AdminAuthService` in `admin_auth_service.py` uses SHA-256 (plain comparison). Tenant user passwords are not hashed or stored on the backend.

### 4.3 Are passwords ever stored locally?

No. Tenant user passwords are only sent to Supabase (login and password set/reset). They are not stored in app DB or in backend code.

### 4.4 Can a user log in without Supabase today?

No. For tenant users, the only successful path is: backend returns email from username → frontend calls Supabase `signInWithPassword(email, password)`. If Supabase Auth is removed and nothing replaces it, login cannot succeed (no internal password check, no internal session).

---

## PHASE 5 — RISK ASSESSMENT

**If Supabase Auth is removed today (and no replacement):**

1. **What would break?**  
   - All tenant login (no password check, no session).  
   - All “forgot password” and “unlock” flows (no reset email, no recovery link).  
   - Password set for invited users (no Supabase `updateUser({ password })`).  
   - Tenant invite emails that rely on Supabase invite (no Supabase user creation / invite).  
   - Session refresh and “remember me” (no Supabase session in localStorage).  
   - Any frontend logic that uses `getCurrentUser()` / `getSession()` (would be null after removal).

2. **Which endpoints would fail?**  
   - **Backend:** `/api/auth/username-login` would still return 200 and email for valid username (it doesn’t check password). So backend would not “fail” per se, but the next step (Supabase sign-in) would fail, so effective login would fail.  
   - No tenant API endpoints depend on Supabase directly; they’d still run if called with the right tenant header. So “failure” is mainly frontend: no session → app shows login; no way to get a session without Supabase.

3. **Would existing sessions continue working?**  
   - No. Session lives in Supabase (and in localStorage as Supabase tokens). If Supabase Auth is turned off or frontend stops using it, existing sessions would not be refreshed and would eventually be treated as logged out.

4. **Would frontend crash?**  
   - Not necessarily a hard crash, but: `initSupabaseClient()` would still run (or fail if Supabase URL/key removed). After “login,” `signInWithPassword` would fail; user would stay on login. If Supabase is fully removed, missing client or missing config could cause runtime errors where Supabase is called. So partial breakage or errors, depending on how removal is done.

5. **Would user creation break?**  
   - **Tenant invite (onboarding):** Yes — `InviteService.create_user_with_password()` creates the user in Supabase; without it, no Auth user and no UID to use as local `users.id`.  
   - **In-app invite (settings):** Yes — `InviteService.invite_admin_user()` creates Supabase user and sends invite email; without Supabase Auth, no user creation and no email.

---

## PHASE 6 — TRANSITION BLUEPRINT (NO IMPLEMENTATION)

### 6.1 Schema changes required

- **Tenant DBs (users table):**  
  - Add `password_hash` (e.g. VARCHAR(255) or TEXT) nullable at first.  
  - Optionally add `password_updated_at` (TIMESTAMPTZ) for rotation/audit.  
  - Keep `users.id` as primary key. For existing users linked to Supabase, keep current `id` (Supabase UID) to avoid breaking FKs and existing sessions if we dual-auth.  
- **No** `supabase_user_id` column needed if we phase out Supabase and use only internal auth; if we run dual-auth temporarily, we can keep mapping by `id` (existing Supabase UID) and use same `id` for internal JWT `sub`.  
- **New users** (after cutover): can be created with internal UUID and no Supabase user.  
- **Migrations:** One migration per tenant schema (and legacy) adding `password_hash` (nullable), plus optional `password_updated_at`.

### 6.2 New endpoints required

- **POST /api/auth/login** (or keep and extend username-login): Accept username (or email) + password; verify password against `password_hash` in tenant DB (and tenant discovery as today); issue internal JWT (e.g. `sub=user_id`, `tenant_subdomain` or `tenant_id`, `email`, exp). Return same shape as today where possible (e.g. token + user info + tenant_subdomain) so frontend can stay unchanged.  
- **POST /api/auth/refresh:** Accept valid refresh token (or long-lived token); issue new access token.  
- **POST /api/auth/set-password:** For invite/password-set flow: accept token (invitation_token or one-time token) + new password; hash and set `password_hash`, set `password_set=true`, invalidate one-time token.  
- **POST /api/auth/request-reset:** Accept email (or username); look up user in tenant(s), send reset email (app SMTP) with link to app reset page with one-time token (no Supabase).  
- **POST /api/auth/reset-password:** Accept one-time token + new password; validate token, set `password_hash`, clear token.  
- **Optional:** GET /api/auth/me: Return current user from JWT (for frontend that currently uses Supabase user object).

### 6.3 Middleware / dependency changes required

- **New dependency:** e.g. `get_current_user_optional()` and `get_current_user()` that:  
  - Read `Authorization: Bearer <token>`.  
  - Verify JWT (signature, issuer, audience, exp) using a server-side secret.  
  - Extract `sub` (user_id), tenant claim (subdomain or tenant_id).  
  - Optionally load user from tenant DB and attach to request.  
- **Tenant resolution:** Keep `get_tenant_from_header()` for backward compatibility; add resolution from JWT when Bearer is present (tenant from token overrides or validates header). So: if Bearer present → tenant from JWT and require header to match (or set header from JWT); if no Bearer → current behavior (header only).  
- **Protect routes:** Add `Depends(get_current_user)` (or equivalent) to all tenant API routes that should require auth. Today none require it; adding this is a behavioral change that should be done in the same rollout as issuing JWTs so existing clients can send the new token.

### 6.4 Order of deployment

1. **Backend:** Add schema migration (`password_hash` nullable). Deploy.  
2. **Backend:** Add internal auth endpoints (login, set-password, request-reset, reset-password, refresh) and JWT issue/verify; **do not** remove Supabase yet.  
3. **Backend:** Add dual-auth support: e.g. `get_current_user` accepts **either** (A) internal JWT **or** (B) Supabase JWT (verify with Supabase JWT secret if still available). Resolve tenant from JWT when possible; fall back to header.  
4. **Frontend:** When calling login, if backend returns an `access_token` (and optionally `refresh_token`), store them and send `Authorization: Bearer <access_token>` on API requests (in addition to or instead of relying only on Supabase). Prefer internal login when available (e.g. backend returns token). Keep Supabase login path as fallback.  
5. **Backend:** On login (internal), if user has no `password_hash` but exists in Supabase, optional: trigger “migrate password” flow (e.g. one-time token to set password) so we can eventually turn off Supabase.  
6. **Data migration (optional):** For users who only have Supabase passwords, either: (a) force “forgot password” flow (reset via app) or (b) keep dual-auth until natural password resets. Avoid forced reset if possible.  
7. **Frontend:** Switch password reset and “unlock” to use new backend endpoints (request-reset, reset-password).  
8. **Frontend:** Switch invite/set-password to use new set-password endpoint and stop creating Supabase users for new invites.  
9. **Backend:** Stop creating/updating Supabase Auth users in invite and onboarding flows; rely on internal `password_hash` and tokens.  
10. **Backend:** Remove Supabase JWT acceptance from `get_current_user`; require only internal JWT.  
11. **Frontend:** Remove Supabase Auth calls (signIn, signOut, getSession, updateUser, resetPasswordForEmail); remove Supabase script tag and client init (or keep client only for non-Auth use if any).  
12. **Backend:** Remove InviteService Supabase Auth usage; remove or refactor `invite_service` to use SMTP + app tokens only.

### 6.5 Rollback strategy

- **Before removing Supabase:** Keep Supabase Auth live and dual-auth in place. If issues arise, frontend can be reverted to Supabase-only login; backend can again accept Supabase JWT.  
- **Schema:** `password_hash` nullable so rollback does not require dropping column.  
- **Config:** Keep Supabase env vars until full cutover; flip a feature flag or deploy revert to re-enable Supabase login.  
- **Sessions:** During dual-auth, existing Supabase sessions continue to work until they expire; new logins can use internal JWT. Rollback = point frontend back to Supabase login only and re-enable Supabase JWT in backend.

### 6.6 Risk mitigation

- **No forced logout:** Dual-auth period where both Supabase and internal JWT are accepted; existing Supabase sessions valid until expiry.  
- **No forced password reset:** New internal login only required when user next logs in; optional “migrate password” on first internal login (set `password_hash` via one-time token after verifying Supabase session or email).  
- **Frontend unchanged UX:** Same login form (username + password), same post-login redirects; only change is backend returning app-issued token and frontend sending it as Bearer.  
- **Tenant resolution:** JWT carries tenant; backend validates header matches token (or sets tenant from token) to prevent cross-tenant misuse.  
- **In-app invite linking:** Fix the missing “link local user to Supabase UID” step if we still use Supabase during transition (e.g. on first password set via Supabase, update local `users.id` to Supabase UID or create a mapping). Alternatively, move invite flow fully to internal auth and create users with internal UUID + `password_hash` from the start.

### 6.7 Estimated complexity

- **Medium–high.**  
- **Reasons:** Many frontend touch points (login, reset, set-password, invite, session timeout, auth state); backend today has no tenant user auth (no JWT, no get_current_user); invite and onboarding flows deeply tied to Supabase Auth; two user-creation paths (tenant invite vs in-app invite) with different id-handling.  
- **Simplifiers:** Backend already has username→email and tenant discovery; admin auth already uses local password; config already has SECRET_KEY/ALGORITHM for JWT; no current JWT verification to conflict with.

---

## Summary table

| Topic | Finding |
|-------|--------|
| **Login** | Frontend: username + password → backend returns email (no password check) → Supabase `signInWithPassword(email, password)`. |
| **Token to API** | No Bearer token sent; only `X-Tenant-Subdomain`. |
| **Backend JWT** | None for tenant APIs. |
| **Tenant** | From header only; no user identity check. |
| **Users table** | No `password_hash`; `users.id` = Supabase UID when linked (tenant-invite); in-app invite uses temp UUID with no link step. |
| **Password reset** | 100% Supabase (magic link + `updateUser`). |
| **User creation** | Invite and onboarding use Supabase Auth admin API. |
| **If Supabase Auth removed** | Login, reset, set-password, invite break; existing sessions stop working; no crash but no way to log in. |

This document is diagnostic and planning only; no code or schema has been changed.
