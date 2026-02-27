# Multi-Company Readiness: JWT, RLS, and Onboarding

This document describes the backend refactor for **single-DB, multi-company** readiness: one Postgres database, multiple companies, isolation by `company_id` and optional RLS. It covers what was implemented, how to validate it, and how to onboard a second company safely.

---

## 1. What Was Implemented

### 1.1 JWT `company_id` claim

- **Access and refresh tokens** now include an optional `company_id` claim (UUID string) derived from the user’s DB record (branch assignments or single company).
- **Login** (`/auth/username-login`): after resolving the user, the backend computes `company_id` via `get_effective_company_id_for_user(db, user)` and injects it into both access and refresh tokens.
- **Refresh** (`/auth/refresh`): the backend loads the user from the DB, resolves `company_id`, and issues new access/refresh tokens that include it.
- **Backward compatibility**: if no company can be resolved (e.g. no branch roles and no company row), `company_id` is omitted from the token; existing single-company behaviour is unchanged.

### 1.2 RLS session GUC

- On every authenticated request, after loading the user, the backend sets the PostgreSQL session variable:
  - `jwt.claims.company_id = <user's company_id>`
- This is done in both `get_current_user` and `get_current_user_optional` (in `app/dependencies.py`).
- RLS policies can use `current_setting('jwt.claims.company_id', true)::uuid` to restrict rows by company. If you have not yet added RLS policies, the GUC is still set so that when you do add policies, they will work without further app changes.

### 1.3 Effective company resolution

- **`get_effective_company_id_for_user(db, user)`** (in `app/dependencies.py`):
  - Prefer: from the user’s branch assignments (`UserBranchRole` → `Branch` → `company_id`), use the first branch’s company.
  - Fallback: if the user has no branch roles, use the single company in the DB (`companies` LIMIT 1) for backward compatibility.

### 1.4 Destructive endpoints hardened

- **`POST /api/excel/clear-for-reimport`**:  
  - Company is taken **only** from the authenticated user (`get_effective_company_id_for_user`).  
  - Request body `company_id` must match the user’s company; otherwise 403.
- **`POST /api/excel/import`**:  
  - Form `company_id` must match the authenticated user’s company.  
  - `branch_id` must belong to that company.  
  - Returns 403 if not.

### 1.5 Legacy one-company DB logic removed

- **Migration `043_drop_single_company_enforcement.sql`**:
  - Drops trigger `check_single_company` on `companies`.
  - Drops functions `enforce_single_company()` and `get_company_id()`.
- After applying this migration, you can insert multiple companies in the same database. The app uses JWT/session `company_id` for scoping; RLS (when enabled) uses the same GUC.

---

## 2. Validation Checklist and Test Snippets

### 2.1 (a) Users from one company cannot see another company’s data

- **Manual check**: Create two companies (A and B), each with a branch and a user assigned to that branch. Log in as user A and call APIs that return company-scoped data (e.g. items, branches, quotations). Verify that only company A’s data is returned. Repeat for user B.
- **Snippet (pytest-style, for inspiration)** — replace with your actual client and DB if needed:

```python
# Pseudo-code: two users in different companies
# 1. Create company_a, branch_a, user_a (assigned to branch_a); company_b, branch_b, user_b.
# 2. Login as user_a -> access_token_a
# 3. GET /api/items/overview with Authorization: Bearer <access_token_a>
# 4. Assert all returned items have company_id == company_a.id
# 5. Login as user_b -> access_token_b
# 6. GET /api/items/overview with Authorization: Bearer <access_token_b>
# 7. Assert all returned items have company_id == company_b.id
```

- **Backend guarantee**: All endpoints that use `get_current_user` receive a DB session on which `SET LOCAL jwt.claims.company_id = <user's company_id>` has been run. If you add RLS policies that filter by `current_setting('jwt.claims.company_id', true)::uuid`, then even raw SQL in the same session will only see that company’s rows (for tables that have RLS enabled and the policy applied).

### 2.2 (b) RLS works correctly when multiple companies exist

- **Prerequisite**: Add RLS policies on the relevant tables (e.g. `items`, `branches`, `quotations`) that restrict rows by `company_id` using the session variable. Example (conceptual):

```sql
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
CREATE POLICY items_company ON items
  FOR ALL
  USING (company_id = current_setting('jwt.claims.company_id', true)::uuid);
```

- **Test**: With two companies and RLS enabled, open two sessions. In each session, `SET jwt.claims.company_id = '<company_id>'` (or use the app so the backend sets it). Run `SELECT * FROM items;` in each session and confirm each sees only that company’s items.

### 2.3 (c) JWTs contain `company_id` and backend uses it exclusively for company scoping

- **Decode JWT after login** (e.g. on [jwt.io](https://jwt.io) or in Python with `jwt.decode`): access and refresh payloads should contain `"company_id": "<uuid>"` when the user has a resolvable company.
- **Backend**: Company for the request is derived from the **user loaded from the DB** (via `get_effective_company_id_for_user`), not from the JWT claim for authorization. The JWT claim is set from that same resolution at login/refresh and can be used for logging or optional validation. Destructive and scoped endpoints (clear-for-reimport, import) use only the server-side–resolved company.

**Quick test (Python):**

```python
import jwt  # PyJWT
payload = jwt.decode(access_token, options={"verify_signature": False})
assert "company_id" in payload
assert payload["company_id"]  # non-empty UUID string
```

---

## 3. Safely Onboarding a Second Company

These steps assume you already have one company in the DB and want to add a second without breaking existing users.

1. **Apply migration 043**  
   Run `pharmasight/database/migrations/043_drop_single_company_enforcement.sql` so the trigger and `get_company_id()` / `enforce_single_company()` are dropped.

2. **Insert the second company**  
   Insert a new row into `companies` (name, registration_number, etc.). No trigger will block it.

3. **Create branches and users for the new company**  
   Insert into `branches` (with the new `company_id`) and `users`. Assign users to branches via `user_branch_roles` so `get_effective_company_id_for_user` returns the new company’s ID.

4. **Optional: enable RLS**  
   If you want DB-level isolation, add RLS on the relevant tables and use `current_setting('jwt.claims.company_id', true)::uuid` in policies. The app already sets this GUC on every request.

5. **No frontend or report changes required**  
   API request/response shapes are unchanged. Existing reports and dashboards that filter by company (or rely on the single company) continue to work. New company users get JWTs with their own `company_id` and only see their company’s data when the backend (and optionally RLS) scopes by it.

6. **Tenant vs single-DB**  
   If you still use tenant-specific DBs (different `database_url` per tenant), the same JWT and GUC logic applies per tenant DB. When you consolidate to a single DB, keep one tenant row pointing at that DB and rely on `company_id` + RLS for isolation.

---

## 4. Optional Feature Flag (Phased Rollout)

If you want to phase rollout (e.g. only set RLS GUC when a flag is on):

- In `app/config.py` add e.g. `USE_RLS_COMPANY_SCOPE: bool = True`.
- In `get_current_user` / `get_current_user_optional`, only run the `SET LOCAL jwt.claims.company_id = :cid` block when `settings.USE_RLS_COMPANY_SCOPE` is true.

This does not change JWT contents; it only controls whether the session GUC is set so RLS policies can use it.

---

## 5. File Reference

| Area              | File(s) |
|-------------------|--------|
| JWT creation      | `backend/app/utils/auth_internal.py` (`create_access_token`, `create_refresh_token`, `CLAIM_COMPANY_ID`) |
| Login/refresh     | `backend/app/api/auth.py` (`_build_login_response`, `auth_refresh`) |
| Company resolution & GUC | `backend/app/dependencies.py` (`get_effective_company_id_for_user`, `get_current_user`, `get_current_user_optional`, `RLS_CLAIM_COMPANY_ID`) |
| Destructive endpoints | `backend/app/api/excel_import.py` (`clear_for_reimport`, `import_excel`) |
| Migration         | `database/migrations/043_drop_single_company_enforcement.sql` |

---

## 6. Summary

- **JWTs** include `company_id` for all users with a resolvable company (login and refresh).
- **RLS GUC** `jwt.claims.company_id` is set on every authenticated request.
- **Company** for authorization is taken only from the DB (user’s branches or single company); destructive and import endpoints are locked to that company.
- **Legacy** one-company trigger and helpers are removed by migration 043.
- **Onboarding** a second company is: run migration, insert company/branches/users, optionally enable RLS; no frontend or report changes required.
