# Tables Not Required by Current App Flow (Cleanup Candidates)

With the new single-DB multi-company model (JWT `company_id`, RLS, no tenant-per-DB dependency for core ERP), the following tables are **not used by the current backend app flow** or are **optional**. Listed with comments for safe cleanup.

---

## Tables safe to remove (no backend usage)

### 1. `expense_categories`

- **Comment:** No backend API or model. Table exists in schema/migrations; frontend has nav placeholders (`expenses`, `expenses-categories`, `expenses-reports`) but no endpoints or ORM models. Permissions exist in seeds (`expenses.view`, etc.) but are never enforced by any expense API.
- **If you remove:** Drop table (and `expenses` first due to FK). Optionally remove frontend menu items and permission seeds for expenses to avoid dead UI.

### 2. `expenses`

- **Comment:** No backend API or model. Depends on `expense_categories`. Same as above: schema and frontend placeholders only.
- **If you remove:** Drop after `expense_categories` if you keep categories for future use, or drop both. Optionally remove related frontend routes and permission seeds.

---

## Optional (single use or legacy; removable if you change behavior)

### 3. `admin_audit_log`

- **Comment:** Only used in one place: `INSERT` when an admin creates a user (`app/api/users.py` admin-create-user endpoint). No reads in app flow. Column `tenant_id` is legacy; with company-in-JWT you could store `company_id` instead if you keep the table.
- **If you remove:** Drop the table and remove the try/except `INSERT` block in the admin-create-user endpoint (audit becomes optional/no-op). Optionally add a simple file or external audit later.

---

## Tables to keep (in use)

All other tables in your schema are referenced by the backend:

- **Tenant / SaaS:** `tenants`, `tenant_invites`, `tenant_modules`, `tenant_subscriptions`, `subscription_plans` — used by tenants API, onboarding, Stripe, and auth tenant resolution (master DB or same DB when `MASTER_DATABASE_URL = DATABASE_URL`).
- **Auth:** `refresh_tokens`, `revoked_tokens` — used by login/refresh/logout. `refresh_tokens.tenant_id` is still written for compatibility; you can make it nullable or backfill from JWT `company_id` later without dropping the table.
- **Snapshots:** `inventory_balances`, `item_branch_purchase_snapshot`, `item_branch_search_snapshot` — used by items API and snapshot service.
- **Core ERP:** companies, branches, users, items, sales, purchases, order book, stock take, etc. — all in use.
- **Schema tracking:** `schema_migrations` — used by migration runner.

---

## Summary table

| Table | Required by app flow? | Comment |
|-------|------------------------|--------|
| `expense_categories` | No | No API/model; frontend placeholders only |
| `expenses` | No | No API/model; FK to expense_categories |
| `admin_audit_log` | Optional | Only written on admin user create; removable if you drop that audit |

All other tables in the schema are required by the current app flow (auth, tenant/SaaS, ERP, snapshots, migrations).
