# Deploying PharmaSight on Render

This doc covers common issues when running the app on Render, especially **“Network is unreachable”** for tenant DBs and for SMTP.

---

## 1. Tenant DB: “Network is unreachable” (migrations / tenant DB)

**Symptom:** Startup logs show:

```text
connection to server at "db.xxxxx.supabase.co" (2a05:d018:...), port 5432 failed: Network is unreachable
```

**Cause:** Render’s network may not have working IPv6 connectivity to Supabase. The direct DB host `db.<ref>.supabase.co` can resolve to IPv6, so the connection fails.

**Fix: Use Supabase connection pooler (IPv4-friendly)**

1. In **Supabase Dashboard** → your project → **Settings** → **Database**, find the **Connection string** section.
2. Use the **Connection pooling** (Session mode) URI, which looks like:
   ```text
   postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres
   ```
   (Region is e.g. `eu-west-1` or `us-east-1`.)
3. Update the **tenant’s** `database_url` in your **master** DB to this pooler URL (not the direct `db.xxx.supabase.co` URL).

Where to update:

- If you use an admin/API to edit tenants: set that tenant’s `database_url` to the pooler URI.
- Or run SQL on the master DB, for example:
  ```sql
  UPDATE tenants
  SET database_url = 'postgresql://postgres.[REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres'
  WHERE id = '5bb3bedf-a4c1-4090-967d-d0441410252e';
  ```
  (Replace `[REF]`, `[PASSWORD]`, `[REGION]` with the real values from the Supabase pooler string.)

After that, redeploy or restart so migrations run again. The migration error message also points to this doc (`RENDER.md`).

**Optional:** If a tenant is deleted or you no longer use that DB, you can skip it on startup by marking the tenant cancelled (see main migration logs for the `mark_tenant_cancelled.py` command).

---

## 2. SMTP: “Network is unreachable” (password reset emails)

**Symptom:** Logs show:

```text
OSError: [Errno 101] Network is unreachable
Failed to send password reset email to ... (check SMTP)
```

when connecting to `smtp.gmail.com` (or another SMTP host).

**Cause:** On **Render’s free tier**, outbound SMTP (e.g. port 587) is often **blocked** to limit abuse. So even with correct `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD`, the TCP connection to the mail server fails with “Network is unreachable”.

**Options:**

1. **Upgrade Render**  
   Use a **paid** Render plan that allows outbound SMTP. Then your current Gmail SMTP setup can work as-is.

2. **Use an email API over HTTPS (recommended if staying on free tier)**  
   Use a provider that sends mail via **HTTP API** instead of SMTP, so it’s not blocked:

   - **Resend** – https://resend.com (has a free tier, simple API).
   - **SendGrid** – https://sendgrid.com  
   - **Mailgun** – https://www.mailgun.com  

   The app would need a small change to support e.g. `RESEND_API_KEY` and call their API instead of SMTP when that key is set. Until then, SMTP on Render free tier will keep failing with “Network is unreachable”.

3. **Keep SMTP for local only**  
   Use SMTP in `.env` for localhost; on Render, accept that password reset emails won’t send unless you use (1) or (2).

---

## 3. Quick reference

| Issue | What you see | Fix |
|------|----------------|-----|
| Tenant DB unreachable | `connection to ... db.xxx.supabase.co ... Network is unreachable` | Use Supabase **pooler** URL for that tenant’s `database_url` (see §1). |
| SMTP unreachable | `[Errno 101] Network is unreachable` when sending reset email | Render free tier blocks SMTP; use paid plan or an HTTPS email API (see §2). |

After changing tenant `database_url` or enabling an email API, redeploy or restart the service so changes take effect.
