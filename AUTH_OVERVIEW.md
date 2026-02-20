# Auth system overview: permissions, sessions, branch access, password

This doc ties together how your **users** table, **permissions**, **session timeouts**, **branch access**, and **password reset** work, and how to fix **reset emails not being sent**.

---

## 1. Your `public.users` table

Your table is correct for the current auth design:

| Column | Purpose |
|--------|--------|
| `id`, `email`, `username`, `full_name`, `phone` | Identity |
| `is_active`, `deleted_at` | Access control (inactive/deleted users cannot log in) |
| **`password_hash`** | Internal login: bcrypt hash checked at login; JWT then issued by backend |
| **`password_set`**, **`password_updated_at`** | Track whether user has set/changed password |
| **`invitation_token`**, **`invitation_code`**, **`is_pending`** | **Invite flow only**: link/code for “set your password” when an admin invites a user. Not used for JWT or session. |

There is **no JWT table**. JWTs are stateless (signed with `SECRET_KEY`); nothing is stored in the DB for tokens.

---

## 2. How the app regulates behaviour

### Permissions (RBAC)

- **Tables**: `user_roles`, `role_permissions`, **`user_branch_roles`** (user → branch → role).
- **Config**: `permission_config.py` defines **HQ-only permissions** (e.g. create items, create users); those are only allowed when the user is at the HQ branch.
- **Usage**: APIs that need a permission check the current user’s role(s) for the current branch via `user_branch_roles` and `role_permissions`. No role at that branch → no access.

### Session timeouts

- **Access token**: `ACCESS_TOKEN_EXPIRE_MINUTES` (default **30**). After that, the frontend must use the refresh token.
- **Refresh token**: `REFRESH_TOKEN_EXPIRE_DAYS` (default **7**). After that, the user must log in again.
- **Reset token** (in email link): `RESET_TOKEN_EXPIRE_MINUTES` (default **60**).

All are in `app/config.py` (and `.env`: not typically set, so defaults apply).

### Branch access

- **Only** branches in **`user_branch_roles`** for that user are allowed. No row → no access to that branch.
- The frontend sends `X-Tenant-Subdomain` and the backend resolves the tenant; the JWT can carry `tenant_subdomain`. Branch is chosen in the app (e.g. branch selector); APIs that are branch-scoped check the user has a role for that branch where needed.

### Password

- **Login**: Backend checks `users.password_hash` (bcrypt), then issues access + refresh JWT.
- **Reset**: User requests reset → backend finds user, creates one-time reset token, **sends email in background** → user clicks link → `POST /api/auth/reset-password` with token + new password → backend updates `users.password_hash`.

---

## 3. Why password reset emails might not be sent

The flow is: **request-reset** → enqueue background task → **EmailService.send_password_reset** (SMTP). If the email never arrives, work through the list below.

### 3.1 SMTP not configured (e.g. on Render)

The backend only sends if **all** of these are set:

- `SMTP_HOST`
- `SMTP_USER`
- `SMTP_PASSWORD`

- **Local**: Your `.env` has these (e.g. Gmail), so local is usually fine.
- **Render**: Set the same three (and optionally `EMAIL_FROM`) in the **backend service** Environment tab. If any is missing, the API still returns “you will receive a reset link” but **no email is sent** and you’ll see in logs:  
  `[request-reset] Email NOT sent to ... (SMTP failed or not configured …)`.

### 3.2 Gmail: app password and security

- Use an **App Password** (not your normal Gmail password): Google Account → Security → 2-Step Verification → App passwords. Put that in `SMTP_PASSWORD`.
- If 2FA or the app password was changed/removed, SMTP will fail. Update `SMTP_PASSWORD` and restart.
- **From address**: Gmail often requires the sender to match the account. Use something like:  
  `EMAIL_FROM=PharmaSight <pharmasightsolutions@gmail.com>`  
  with `SMTP_USER=pharmasightsolutions@gmail.com`.

### 3.3 Background task failure

The email is sent in a **FastAPI BackgroundTask**. If that task raises (e.g. SMTP error), the exception is logged and a line is printed:

- `[request-reset] Email send ERROR for <email>: <error>`

Check **backend logs** (local terminal or Render logs) right after someone requests a reset. If you see that line, the message explains the failure (e.g. authentication failed, connection refused).

### 3.4 Quick check: test SMTP from the server

From the **same environment** that runs the API (same machine and env as the backend), run:

```bash
cd pharmasight
python -m pharmasight.backend.scripts.test_smtp
```

Or to send the test email to a specific address:

```bash
python -m pharmasight.backend.scripts.test_smtp someone@example.com
```

The script prints whether SMTP is configured and tries to send one password-reset email. If it fails, the traceback shows the reason (wrong password, network, From address, etc.).

---

## 4. Checklist: reset emails not working

1. **Backend env** (local `.env` or Render): `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` set.
2. **Render**: Backend service has those three (and optional `EMAIL_FROM`); redeploy after changing env.
3. **Gmail**: Use an App Password in `SMTP_PASSWORD`; `EMAIL_FROM` address should match the Gmail account.
4. **Logs**: After a reset request, look for:
   - `[request-reset] Email sent to ...` → sent.
   - `[request-reset] Email NOT sent ...` or `Email send ERROR ...` → use the message to fix SMTP or env.
5. **Test**: Run the small Python snippet above from the same environment as the backend to confirm SMTP works.

---

## 5. Render vs localhost: sync, loading, and request-reset

### 5.1 Keep Render in sync with local

- Deploy from the same branch you use locally (e.g. `main`). After pushing fixes (auth, migrations, SMTP, timeout), trigger a redeploy on Render so the backend and frontend match.
- Ensure **backend** env on Render matches what you need: `DATABASE_URL`, `SECRET_KEY`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, optional `EMAIL_FROM` and `APP_PUBLIC_URL`.

### 5.2 Why request-reset fails on Render (“Failed to load response data”)

Often the **API request** never reaches the backend:

- **Two services**: If the frontend is one Render service (e.g. static site) and the API is another (e.g. `pharmasight-api.onrender.com`), the app uses a **relative** URL (`/api/auth/request-reset`). That request goes to the **frontend** host, which has no `/api` route, so it fails. **Fix**: In the app, open **Settings** and set **API Base URL** to your backend URL (e.g. `https://pharmasight-api.onrender.com`). Save; the value is stored in localStorage and used for all API calls.
- **Single service**: If the same Render service serves both the app and the API (e.g. FastAPI serves static files and `/api`), relative URLs are correct. Then failure is usually cold start (request times out) or SMTP not set (see §3).

### 5.3 Loading icon / “Sending…” stuck

The reset page shows “Sending…” while the request is in flight. If the request **never completes** (wrong host, timeout, or server error), the button could stay in that state. The app now:

- Uses a **~28 s timeout** for the reset request. After that, the request is aborted and an error is shown (e.g. “Request timed out. The server may be starting (e.g. on Render). Please try again in a moment.”).
- On network/parse errors, shows a clear message and re-enables the button (no success message).

So the loading state should no longer stay forever: either you get success, or an error and the button back. If you still see a stuck spinner, check the Network tab for the `request-reset` call (correct URL, status, or timeout).

### 5.4 Backend config for the frontend

`GET /api/config` returns `api_base_url` (and `app_public_url`, `smtp_configured`). When the frontend is served from the **same origin** as the API, it can use this to know the API base (e.g. after a cold start). If you run **two** Render services, the frontend must get the backend URL from **Settings** (API Base URL), not from `/api/config`, because the first request would have to go to the correct host.

### 5.5 Render: “Network is unreachable” (tenant DB or SMTP)

On Render you may see:

- **Tenant DB:** `connection to server at "db.xxx.supabase.co" ... Network is unreachable` — Render’s network often can’t reach Supabase’s direct DB host (IPv6). **Fix:** Use the **Supabase connection pooler** URL for that tenant’s `database_url` (see **RENDER.md**).
- **SMTP:** `[Errno 101] Network is unreachable` when sending reset email — Render’s **free tier** usually **blocks outbound SMTP** (port 587). **Fix:** Use a paid Render plan, or an email API over HTTPS (e.g. Resend, SendGrid); see **RENDER.md**.

---

## 6. Summary

| Concern | Where it’s handled |
|--------|--------------------|
| **User identity & password** | `public.users`: `password_hash`, `username`, `email`, `is_active`, `deleted_at` |
| **Invitations** | `users.invitation_token`, `invitation_code`, `is_pending` (invite flow only; not JWT) |
| **Permissions** | `user_roles`, `role_permissions`, `user_branch_roles` + `permission_config.py` (HQ-only) |
| **Session timeout** | JWT `exp`: access 30 min, refresh 7 days (config in `config.py` / `.env`) |
| **Branch access** | `user_branch_roles`: user can only use branches they’re assigned to |
| **Password reset** | `POST /api/auth/request-reset` → background email with link → `POST /api/auth/reset-password`; requires SMTP configured and working |

If reset emails still don’t arrive after fixing SMTP and checking logs, use the test script above from the backend environment to see the exact SMTP error. For “request-reset” failing on Render (e.g. “Failed to load response data”), see **§5 Render vs localhost** (API URL, one vs two services, timeout).
