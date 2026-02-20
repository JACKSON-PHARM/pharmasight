# Authentication flow (internal / database auth)

This doc describes how login and password reset work after moving auth to the database, and why some requests can be slow and what was done to improve them.

## Overview

- **Login**: `POST /api/auth/username-login` — username + password; user can be in legacy DB or a tenant DB.
- **Password reset**: `POST /api/auth/request-reset` — email or username; sends reset link by email (internal JWT, no Supabase).
- **Set password**: `POST /api/auth/set-password` — invite/setup flow.
- **Reset password**: `POST /api/auth/reset-password` — one-time token from email.

All user lookups and password checks use the **database** (legacy DB or per-tenant DB). Supabase is used only as PostgreSQL.

---

## Login flow (`/api/auth/username-login`)

1. **Tenant resolution**  
   - If `X-Tenant-Subdomain` (or `X-Tenant-ID`) is present: resolve tenant from master DB, get that tenant’s DB.  
   - If no header: use **legacy/default** DB (single-DB setup).

2. **User lookup**  
   - **With tenant header**: one query in that tenant’s DB for username/email.  
   - **Without tenant header**:  
     - First lookup in legacy DB.  
     - If not found, **tenant discovery**: search up to `MAX_TENANTS_TO_SEARCH` (50) tenant DBs sequentially until the user is found.  
     - Each tenant = one DB connection + one query. With many tenants or slow DB (e.g. Render + Supabase), this can take several seconds.

3. **Password**  
   - If user has `password_hash`: verify with `verify_password`, then issue internal JWT (access + refresh).  
   - If no `password_hash`: return email for legacy Supabase Auth UI (rare now).

4. **Response**  
   - `access_token`, `refresh_token`, `tenant_subdomain`, etc., so the frontend can store tokens and tenant context.

**Why login can be slow**

- **No tenant in URL/header**: tenant discovery runs and can open many DB connections (up to 50). On Render (cold start, network latency to Supabase) each connection can add hundreds of ms.  
- **Mitigation**: Use invite links or `?tenant=SUBDOMAIN` so the frontend sends `X-Tenant-Subdomain`. Then only one tenant DB is used and login is fast.

---

## Password reset flow (`/api/auth/request-reset`)

1. **User lookup**  
   - Same tenant search as login: legacy DB first, then up to `MAX_TENANTS_TO_SEARCH` tenant DBs until the user is found.  
   - So request-reset can also be slow when there are many tenants (bounded by 50 DB lookups).

2. **Build reset link**  
   - Create one-time JWT (`type=reset`), build URL from `get_public_base_url(request)` (APP_PUBLIC_URL or request Origin for Render).

3. **Send email**  
   - **Previously**: SMTP was called **synchronously** in the request. The HTTP response waited for the email to be sent (often 5–30+ seconds or timeout). Users saw no response and clicked again.  
   - **Now**: Email is sent in a **background task**. The handler returns immediately after queuing the send. Response time is dominated by the tenant search (and master DB), not SMTP.

4. **Response**  
   - Always 200 with a generic message. `email_sent: true` means the send was queued (and SMTP is configured).

**Why request-reset was “taking forever”**

- Blocking on SMTP in the request.  
- **Fix**: Use FastAPI `BackgroundTasks` so the API returns right after finding the user and queuing the email. Frontend also shows “Sending...” and disables the button to avoid double-clicks.

---

## Tenant search cap

- `_find_user_in_all_tenants()` is used by both login (when no tenant) and request-reset.  
- It now limits the number of tenant DBs searched to **50** (`MAX_TENANTS_TO_SEARCH`) so that:
  - Login and request-reset have a bounded worst-case time.
  - On Render, cold start + many tenants no longer cause multi-minute requests.

If you have more than 50 active tenants, ensure users sign in via invite link or `?tenant=SUBDOMAIN` so the tenant header is set and tenant discovery is skipped.

---

## Summary of performance-related changes

| Issue | Cause | Change |
|-------|--------|--------|
| Request-reset “taking forever” | SMTP send blocked the HTTP request | Send password-reset email in a **background task**; API returns after queueing. |
| User clicks “Send” multiple times | No loading state; slow response | **Frontend**: “Sending...” + disable submit until request completes. |
| Login / request-reset slow with many tenants | Unbounded sequential tenant DB search | **Cap tenant search** at 50 DBs; recommend tenant in URL/header for fast path. |

---

## Quick reference

- **Backend auth**: `pharmasight/backend/app/api/auth.py`  
- **Tenant search**: `_find_user_in_all_tenants()` (used by username-login and request-reset)  
- **Reset link base URL**: `app/utils/public_url.py` → `get_public_base_url(request)`  
- **Email**: `app/services/email_service.py`; invite emails already use background tasks in `tenants.py`.
