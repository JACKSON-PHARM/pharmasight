# Render: Default Company Redirected to Setup (Multi-Tenant Fix)

## What was happening

- You log in as the **default/master company** (the one in the default DB).
- The app redirects you to **company setup** as if the company didn’t exist.
- On **localhost** the same login works and you go to the dashboard.

## Root cause

The app supports **multi-tenant** (database per tenant). Two things were in play:

1. **Setup status** (`/api/setup/status`) was deciding “does a company exist?” using the database chosen by the **request header** `X-Tenant-Subdomain`, not by the **logged-in user’s** tenant.
2. On Render you often use a **single origin** (e.g. `https://yourapp.onrender.com`) for both the default company and client tenants. If you had previously opened a **client’s** link (invite or `?tenant=client-subdomain`), the browser stored that tenant in `localStorage` / `sessionStorage`. So when you later signed in as the **default** company, the frontend still sent `X-Tenant-Subdomain: client-subdomain`. The backend then checked “company exists?” in the **client’s** DB (empty) instead of the **default** DB (where your company exists) → `company_exists = false` → redirect to setup.

So it was **not** that Render “can’t support multi-tenant login.” It was that the setup check used the **header** (which can be the wrong tenant) instead of the **user’s actual tenant** from the JWT.

## Fix applied (backend)

- **File:** `backend/app/api/invite.py`
- **Change:** `/api/setup/status` now uses the database session from **`get_current_user`** (i.e. the DB for the user identified by the JWT) to run `check_company_exists`, instead of using **`get_tenant_db`** (which was driven only by `X-Tenant-Subdomain`).
- So “company exists?” is always answered in the **same** DB the user belongs to, regardless of what tenant is in the browser’s storage or URL.

After redeploying the backend on Render, default-company logins should no longer be wrongly sent to setup.

## Workarounds (before or without redeploy)

1. **Clear tenant from URL and storage**
   - Open the app **without** `?tenant=...` in the URL (e.g. `https://yourapp.onrender.com/#login`).
   - After opening the login page, open DevTools → Application → Local Storage / Session Storage for your site and remove the key `pharmasight_tenant_subdomain` if it’s set.
   - Then log in with your default company credentials. The frontend will clear tenant on successful login; the next request may then hit the backend without a tenant header so the old behavior might not trigger.

2. **Use a clean profile or incognito**
   - Use an incognito/private window (or a browser profile that has never opened a client link) and log in at the main app URL without `?tenant=...`. No stored tenant → no wrong header → correct DB can be used when the backend falls back correctly.

3. **Redeploy with the fix**
   - Deploy the updated `invite.py` so `/api/setup/status` uses the token-based DB. Then default and tenant logins can be used on the same Render service without being mis-routed to setup.

## Summary

- **Cause:** Setup status used **header** tenant (browser storage) instead of **JWT** tenant (actual user).
- **Fix:** Setup status now uses the DB from the authenticated user (JWT) for the “company exists?” check.
- **Multi-tenant on Render:** The same Render service **can** support multiple tenants and default-company login at the same time; the bug was in which DB was used for the setup check, not in Render itself.
