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

## 4. After fixing `tenants`: Render env and deploy

- **USE_SUPABASE_POOLER_FOR_TENANTS** = `true` on Render (so tenant DBs use the pooler; no need to change `database_url` in the DB).
- **DATABASE_URL** on Render = master DB URL (pooler format is fine).
- Redeploy so the app (and any pooler logic) is up to date.

---

## 5. What you’ll see in logs after a fix

After the next deploy, when someone tries to log in as a tenant user, you should see a log line like:

- **Tenant discovery: N tenant(s) with database_url and active status (subdomains: ['harte-pharmacy-ltd', ...])**

If **N** is 0 or the list does **not** include `harte-pharmacy-ltd`, then either:

- No row has `database_url` set and non‑cancelled/non‑suspended status, or  
- The Harte row is missing or has `database_url` NULL or `status` in `('cancelled','suspended')`.

Fix the **`tenants`** row as above, then try again.
