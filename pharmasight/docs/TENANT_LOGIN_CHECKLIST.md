# Tenant login checklist (Render / “User not found”)

When a **tenant** user (e.g. G-GRACE1 for Harte Pharmacy) gets **“User not found”** on Render while default-DB users work, check the following. Login does **not** use `tenant_subscriptions`; it only uses the **`public.tenants`** table.

---

## 1. Login does **not** use `tenant_subscriptions`

- **`tenant_subscriptions`** is used for billing/Stripe (plans, periods, Stripe IDs).
- **Login** only reads **`public.tenants`**: it looks up tenants where `database_url` is set and `status` is not `cancelled` or `suspended`, then connects to each tenant’s DB to find the user.
- So a missing or empty `tenant_subscriptions` row for Harte is **not** the cause of “User not found”.

---

## 2. What **must** be true in `public.tenants` for Harte (and any tenant)

For the app to search a tenant’s database during login (with or without `?tenant=...`), that tenant’s row in **`public.tenants`** (in the **master** DB – pharmasightsolutions’s project) must have:

| Column          | Required | Notes |
|-----------------|----------|--------|
| **`database_url`** | **Yes**  | Must be **non-NULL**. This is the Postgres URI for that tenant’s Supabase DB (e.g. Harte’s project). If this is NULL, that tenant is **never** searched, so “User not found” is expected. |
| **`status`**       | **Yes**  | Must **not** be `cancelled` or `suspended`. Use `trial` or `active`. |
| **`subdomain`**    | Yes      | Must match how you call the app (e.g. `harte-pharmacy-ltd`). |
| **`name`**         | No       | Display only (e.g. "HARTE PHARMACY LTD"). |

Project **name** in Supabase (e.g. “HARTE PHARMACY”) does **not** need to match the **`name`** in `tenants` exactly; the app matches tenants by **`subdomain`** (and optionally tenant id), not by display name.

---

## 3. How to check in Supabase (master project)

1. Open the **master** project (pharmasightsolutions’s Project) in Supabase.
2. Go to **Table Editor** → **`public.tenants`**.
3. Find the row for Harte (e.g. `name = 'HARTE PHARMACY LTD'` or `subdomain = 'harte-pharmacy-ltd'`).
4. Confirm:
   - **`database_url`** is **not** empty/NULL. It should look like:  
     `postgresql://postgres:YOUR_PASSWORD@db.dcgfmjbhnvakiuuobxwz.supabase.co:5432/postgres`
   - **`status`** is `trial` or `active` (not `cancelled` or `suspended`).

If **`database_url`** is NULL, the app will **never** try to connect to Harte’s DB, so G-GRACE1 will always get “User not found”. Set it via your admin “Initialize tenant database” flow (or by updating the row) using the **Harte** Supabase project’s connection string (Settings → Database).

---

## 4. Render: pooler and IPv4

- **USE_SUPABASE_POOLER_FOR_TENANTS** = `true` on Render.
- **DATABASE_URL** on Render = master DB URL; use the **session pooler** URL (e.g. `aws-1-eu-west-1.pooler.supabase.com:5432`) so the app can derive the pooler host for tenant DBs. Tenant direct URLs (`db.xxx.supabase.co:5432`) are then rewritten to the same regional session pooler with `postgres.TENANT_PROJECT_REF` (IPv4-friendly).
- If you still get **"FATAL: Tenant or user not found"** when using the shared pooler, set that tenant’s **`database_url`** in `public.tenants` to the **session pooler** connection string from **that tenant’s** Supabase project (Dashboard → Connect → Session pooler). Then the app uses that URL as-is (no rewrite).
- If you get **"Network is unreachable"** to `db.xxx.supabase.co`, the app is trying the transaction pooler (port 6543) on that host (IPv6). Ensure DATABASE_URL uses the session pooler so the session-pooler rewrite runs, or set the tenant’s `database_url` to that tenant’s session pooler URL as above.

---

## 5. What you’ll see in logs after a fix

After the next deploy, when someone tries to log in as a tenant user, you should see a log line like:

- **Tenant discovery: N tenant(s) with database_url and active status (subdomains: ['harte-pharmacy-ltd', ...])**

If **N** is 0 or the list does **not** include `harte-pharmacy-ltd`, then either:

- No row has `database_url` set and non‑cancelled/non‑suspended status, or  
- The Harte row is missing or has `database_url` NULL or `status` in `('cancelled','suspended')`.

Fix the **`tenants`** row as above, then try again.
