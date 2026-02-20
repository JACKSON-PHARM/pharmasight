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

## 5. Summary

| Concern | Where it’s handled |
|--------|--------------------|
| **User identity & password** | `public.users`: `password_hash`, `username`, `email`, `is_active`, `deleted_at` |
| **Invitations** | `users.invitation_token`, `invitation_code`, `is_pending` (invite flow only; not JWT) |
| **Permissions** | `user_roles`, `role_permissions`, `user_branch_roles` + `permission_config.py` (HQ-only) |
| **Session timeout** | JWT `exp`: access 30 min, refresh 7 days (config in `config.py` / `.env`) |
| **Branch access** | `user_branch_roles`: user can only use branches they’re assigned to |
| **Password reset** | `POST /api/auth/request-reset` → background email with link → `POST /api/auth/reset-password`; requires SMTP configured and working |

If reset emails still don’t arrive after fixing SMTP and checking logs, use the test script above from the backend environment to see the exact SMTP error.
