# Re-onboarding Legacy Tenants (Single Supabase)

This guide explains how to get **existing clients** (created with the old “one Supabase project per tenant” setup) working again after you have moved to **one Supabase project** and deleted their old projects.

---

## 1. Current situation

- **Old model**: Each tenant had its own Supabase project (DB + Auth). Users lived in that tenant’s DB.
- **New model**: One Supabase project = one app database. All organizations share it; isolation is by `company_id` (and optional RLS).
- **What you did**: Deleted the old Supabase projects for those tenants. Their data in those projects is gone.
- **What remains**: Rows in the **master** database `tenants` table (e.g. PharmaSage, HARTE, Default). The **app** database (single Supabase) may already have one company (e.g. Default) and its users/branches.

To get a legacy client “started again” you need to:

1. Point their **tenant** row at the **single** app database.
2. Ensure they have a **Company** (and Branch) in that app database, with **name matching** the tenant’s name (so invite completion can link the user to the right company).
3. **Re-invite** them; when they complete the invite, they get a user in the single DB and are linked to their company via `UserBranchRole`.

---

## 2. Step-by-step re-onboarding

### 2.1 Get the single app database URL

Use the same connection string your app uses for the single Supabase DB (e.g. from `DATABASE_URL` or `SUPABASE` connection string). You will set this on each tenant row.

---

### 2.2 Point each tenant at the single DB (master DB)

In the **master** database (where `tenants` lives), run for each tenant you want to re-onboard (replace `YOUR_SINGLE_DATABASE_URL` and the tenant name/subdomain as needed):

```sql
-- Example: point "PharmaSage Pharmaceuticals LDT" at the single DB
UPDATE tenants
SET
  database_url   = 'YOUR_SINGLE_DATABASE_URL',
  database_name  = 'pharmasight_pharmasage-pharmaceuticals-ldt',  -- or pharmasight_<subdomain>
  is_provisioned = true,
  provisioned_at = NOW()
WHERE subdomain = 'pharmasage-pharmaceuticals-ldt';  -- or use id / name
```

Repeat for each other tenant (e.g. HARTE, or any other). Use the same `YOUR_SINGLE_DATABASE_URL` for all.

- **Important**: `database_url` must be set so that:
  - “Validate token” and “Complete invite” can open a session to the app DB.
  - Login can resolve the tenant and use that same DB to find the user.

---

### 2.3 Ensure each tenant has a Company (and Branch) in the app DB

The app DB needs one **Company** per re-onboarded tenant, with **name exactly matching** the tenant’s `name` in the master DB. The invite completion flow matches on `Company.name == tenant.name` to attach the user to the correct company.

In the **app** database (single Supabase), for each tenant:

1. **Create Company** (if it doesn’t already exist). Use the **exact** name from `tenants.name` (e.g. `PharmaSage Pharmaceuticals LDT`, `HARTE PHARMACY LTD`).

```sql
-- Run in APP DB (single Supabase). Use the exact tenant name from master.tenants.
-- If a company with this name already exists, skip this insert.
INSERT INTO companies (id, name, currency, timezone, created_at, updated_at)
SELECT gen_random_uuid(), 'PharmaSage Pharmaceuticals LDT', 'KES', 'Africa/Nairobi', NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM companies WHERE name = 'PharmaSage Pharmaceuticals LDT');
```

2. **Create Branch** for that company (if none exists). One branch per company is enough for re-onboarding.

```sql
-- Replace <company_id> with the id of the company you just created/found.
INSERT INTO branches (id, company_id, name, code, is_active, is_hq, created_at, updated_at)
VALUES (
  gen_random_uuid(),
  '<company_id>',
  'Head Office',
  'HQ',  -- or a short code like 'PSG' for PharmaSage
  true,
  true,
  NOW(),
  NOW()
);
```

3. Ensure the **admin** role exists in `user_roles` (it usually does from migrations):

```sql
INSERT INTO user_roles (id, role_name, description, created_at)
SELECT gen_random_uuid(), 'admin', 'Company admin', NOW()
WHERE NOT EXISTS (SELECT 1 FROM user_roles WHERE role_name = 'admin');
```

You can repeat the Company + Branch steps for each legacy tenant (PharmaSage, HARTE, etc.), using the same app DB.

---

### 2.4 Re-invite from the admin UI

1. Log in to the **admin** panel (e.g. `/admin.html`) with an **admin** account (admin token), not a regular company user.
2. Open **Organization management** and find the tenant (e.g. PharmaSage, HARTE).
3. Click **Invite** for that tenant.
4. Create the invite (with or without “send email” depending on your SMTP setup).
5. Share the **setup URL** with the client (e.g. copy from the modal or from the email). The URL looks like:  
   `https://your-app-domain/setup?token=<invite_token>`.

---

### 2.5 Client completes the invite

1. Client opens the setup URL and sets their **password**.
2. Backend:
   - Creates or updates the user in **Supabase Auth** (single project).
   - Creates or updates the **User** in the **app** database (single DB).
   - **Automatically** creates a **UserBranchRole** linking that user to their company’s branch by matching `Company.name` to `tenant.name` (so they get the correct `company_id` in the JWT and RLS).
3. Client can then log in with **username + password**; they will see only their company’s data (and any branch they’re assigned to).

---

### 2.6 If the client’s email already exists in Supabase Auth

If you had previously invited them to the **old** project and their email was created in Supabase Auth there, that Auth user is gone with the deleted project. In the **new** single Supabase project:

- Either they have **no** Auth user yet → invite completion will **create** a new Auth user and app DB user.
- Or they were already created in the new Supabase (e.g. for another company or a test) → invite completion will **set/update** the password and create/update the app DB user and link them to the correct company (via `UserBranchRole`).

No extra steps are required beyond the invite flow.

---

## 3. Checklist per tenant

- [ ] Master DB: `tenants.database_url` = single app DB URL, `is_provisioned = true`.
- [ ] App DB: Company with **name** = `tenants.name`, and at least one Branch; admin role exists.
- [ ] Admin UI: Invite created and setup link shared with client.
- [ ] Client: Opens link, sets password, then logs in with username/password.

---

## 4. Optional: one-off script to create Companies/Branches

If you have many tenants, you can script step 2.3 by:

1. Connecting to the **master** DB and listing `tenants` (e.g. `id`, `name`, `subdomain`) where you want to re-onboard.
2. Connecting to the **app** DB and for each tenant:
   - Insert `companies` with `name = tenant.name` (if not exists).
   - Insert `branches` for that company (if none).
3. Then run step 2.2 (update `tenants.database_url` and `is_provisioned`) for the same list.

The important part is that **company name in the app DB** matches **tenant name in the master DB** so that when the user completes the invite, they are attached to the right company.

---

## 5. Summary

- **Re-inviting is the right way** to get them started again: you create an invite from the admin UI and they complete the setup flow.
- **Before re-inviting**: Point each tenant at the single DB and ensure a matching Company (and Branch) exists in the app DB.
- **After they complete the invite**: They get a user in the single DB and a `UserBranchRole` to the correct company/branch, so they get the correct `company_id` and can use the app normally.
