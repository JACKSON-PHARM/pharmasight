# Render environment variables checklist

Use this with your **local `.env`** so nothing is missed on Render.

## How to use

1. Open **Render Dashboard** → your PharmaSight service → **Environment**.
2. For each variable in the table below, add it in Render and paste the **value from your local `.env`** (same key name).
3. Variables marked **Required** must be set or the app will not work. **Optional** can be left blank if you don’t use that feature.

---

## Variables to copy from `.env` to Render

| Variable | Required | Where to get the value |
|----------|----------|-------------------------|
| **DEBUG** | No | `False` on Render |
| **DATABASE_URL** | Yes | From your `.env` (Supabase connection string) |
| **SECRET_KEY** | Yes | From your `.env` (or generate a new one on Render) |
| **SUPABASE_URL** | Yes | From your `.env` (e.g. `https://xxx.supabase.co`) |
| **SUPABASE_KEY** | Yes | From your `.env` (Supabase anon key) |
| **SUPABASE_SERVICE_ROLE_KEY** | Yes | From your `.env` (Supabase service role key) |
| **SUPABASE_DB_PASSWORD** | Yes | From your `.env` |
| **SUPABASE_DB_HOST** | Yes | From your `.env` (e.g. `db.xxx.supabase.co`) |
| **SUPABASE_DB_NAME** | No | Usually `postgres` |
| **SUPABASE_DB_PORT** | No | Usually `5432` |
| **SUPABASE_DB_USER** | No | Usually `postgres` |
| **ADMIN_PASSWORD** | Yes | From your `.env` or set a new password for admin panel |
| **CORS_ORIGINS** | No | Include your Render frontend URL so the browser allows API calls, e.g. `https://pharmasight.onrender.com` (or `*` for development). Comma-separated if multiple. |
| **SMTP_HOST** | For email | From your `.env` if you send invite emails (e.g. `smtp.gmail.com`) |
| **SMTP_USER** | For email | From your `.env` |
| **SMTP_PASSWORD** | For email | From your `.env` |
| **SMTP_PORT** | No | Usually `587` |
| **EMAIL_FROM** | No | e.g. `PharmaSight <noreply@yourdomain.com>` |
| **APP_PUBLIC_URL** | No | Optional; if unset, invite links use your Render URL. Set to `https://pharmasight.onrender.com` (or your Render URL). |
| **USE_SUPABASE_POOLER_FOR_TENANTS** | **Yes (Render)** | Set to `true` so tenant DBs use Supabase session pooler (IPv4-friendly). Required for tenant login; avoids "User not found" when tenant DBs use direct URLs. When your DATABASE_URL already uses the pooler (e.g. aws-1-eu-west-1.pooler.supabase.com), the app derives the pooler host for tenant DBs automatically. |
| **SUPABASE_POOLER_HOST** | No | Only if DATABASE_URL is a direct URL; set to your session pooler host (e.g. `aws-1-eu-west-1.pooler.supabase.com`). If DATABASE_URL uses pooler.supabase.com, this is derived automatically. |
| **MASTER_DATABASE_URL** | No | Only if you use a different DB for tenant registry. Otherwise leave unset (app uses DATABASE_URL). |
| **SUPABASE_OWNER_EMAIL** | No | Optional; Supabase account owner email |

---

## Quick list of key names (copy into Render, then fill values from `.env`)

```
DEBUG
DATABASE_URL
SECRET_KEY
SUPABASE_URL
SUPABASE_KEY
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_DB_PASSWORD
SUPABASE_DB_HOST
SUPABASE_DB_NAME
SUPABASE_DB_PORT
SUPABASE_DB_USER
ADMIN_PASSWORD
CORS_ORIGINS
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
EMAIL_FROM
APP_PUBLIC_URL
USE_SUPABASE_POOLER_FOR_TENANTS
```

After adding each key in Render, paste the corresponding value from your local `.env` file.
