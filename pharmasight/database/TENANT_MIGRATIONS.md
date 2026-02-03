# Tenant Migrations – Transmitting Schema Changes Across Tenants

This doc explains how schema changes (new columns, tables, etc.) are applied to **all tenants** so the app stays consistent without manually running SQL on each tenant.

## How It Works

- **Migrations live in** `database/migrations/` as **numbered SQL files**: `001_initial.sql`, `002_*.sql`, … `011_ensure_item_pricing.sql`, etc.
- Each database (default/master and each tenant) has a `schema_migrations` table that records which versions have been applied.
- **Master DB** holds the `tenants` table. Each tenant row has a `database_url` pointing to **that tenant’s own Supabase project** (e.g. “PHARMASIGHT MEDS LTD” and “pharmasightsolutions's Project” are two separate projects = two tenant DBs). Migrations are **transmitted** to all of them from that one place.
- **New tenants**: When a tenant is provisioned, all migrations in `database/migrations/` are run in order. New tenants therefore get the full current schema (all features).
- **Default/master app DB** (DATABASE_URL): Used for tenant management (tenants table) and for app transactions when no tenant header is sent. On **backend startup**, the app runs the same app migrations on this DB first, so it stays in sync.
- **Existing tenants**: On **backend startup**, the app applies **missing** migrations to every tenant that has a `database_url` and status **trial** or **active** (suspended/cancelled tenants are skipped).
- So: **one place to add a change** → it is applied to the **default/master DB** and to **each tenant project** on the next deploy/restart, and to **new** tenants at provision time.

## Adding a New Schema Change (So All Tenants Get It)

1. **Add a new migration file** in `database/migrations/` with the next number, e.g.:
   - `005_add_my_feature.sql`
   - Use `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` so it is safe to run on DBs that might already have the change.

2. **Deploy** (or restart the backend). On startup, the app will:
   - Run missing migrations on the **default/master app DB** (DATABASE_URL) so tenant management and no-tenant transactions stay in sync
   - List all tenants with `database_url` and status `trial` or `active`
   - For each tenant, run any migration whose version is not in `schema_migrations`
   - Record the new version in `schema_migrations` after a successful run

3. **New tenants** created after the deploy will run 001 → 002 → … → 005 when provisioned, so they inherit the new feature.

You do **not** need to run SQL manually on each tenant DB for changes that are in `database/migrations/`.

## Subscription / Status Respect

- **Startup migrations** only run for tenants with status **trial** or **active**. Tenants that are **suspended** or **cancelled** are skipped (no schema changes applied to them on startup).
- **Subscription control** (e.g. premium features, limits) is intended to be enforced in **application logic** (API/UI), not by withholding schema. Schema migrations keep the database shape the same for all active tenants so the app code can run; you then gate **which features or APIs** a tenant can use based on their plan.

## Manual / One-Off Migrations

- For a **single** tenant DB (e.g. debugging or a one-off fix), you can still run a SQL file manually against that DB (e.g. `psql "<tenant_url>" -f database/add_something.sql`).
- For changes that should **propagate to all tenants**, put them in `database/migrations/` as a new numbered file instead of running them by hand everywhere.

## Summary

| Scenario | How the change is applied |
|---------|---------------------------|
| **Default/master app DB** | Next backend startup runs any new migration on DATABASE_URL (tenant management + transactions when no tenant). |
| **New tenant created today** | Provisioning runs all migrations (001 … 004 …); new tenant gets full schema. |
| **Existing tenant (trial/active)** | Next backend startup runs any new migration (e.g. 004) on that tenant’s DB. |
| **Existing tenant (suspended/cancelled)** | Skipped on startup; no automatic migration. |
| **You add 005_*.sql and deploy** | Default/master DB and all active/trial tenant DBs get 005 on next startup; new tenants get it at provision. |

## Current migrations (reference)

- **001_initial.sql** – Base schema (companies, branches, users, items, sales_invoices, etc.)
- **002_add_user_username_and_invitation.sql** – User username and invitation fields
- **003_quotations_orders_stocktake_import.sql** – Quotations, orders, stock take, import jobs; sales_invoices status/batched/customer_phone
- **004_add_items_vat_category.sql** – items.vat_category
- **005_add_sales_invoices_missing_columns.sql** – sales_invoices.total_inclusive, sales_type (for tenants created from older schema)
- **006_fix_stock_take_session_code_length.sql** – stock take session code length
- **007_add_wholesale_units_per_supplier.sql** – items.wholesale_units_per_supplier
- **008_deprecate_items_price_columns.sql** – Deprecate items price columns (cost/price from inventory_ledger only)
- **009_items_simplified_schema.sql** – items: add description, is_controlled, is_cold_chain, track_expiry; drop deprecated price/VAT columns
- **010_items_default_cost_and_supplier.sql** – items: default_cost_per_base, default_supplier_id (fallbacks when no ledger data)
- **011_ensure_item_pricing.sql** – ensures `item_pricing` table exists (idempotent)

So you do **not** run `add_items_vat_category.sql` on each tenant by hand. The same change is in `database/migrations/004_add_items_vat_category.sql` and is applied to all relevant tenants automatically.

## If Supabase (or a tenant DB) is empty after import

1. **Backend must use the tenant DB for the import.** The Excel import background thread now uses the same database as the API (tenant DB when `X-Tenant-ID` or `X-Tenant-Subdomain` is set). If you previously saw progress in the UI but no rows in Supabase `items` or `inventory_ledger`, that was because the background job was writing to the default DB; that is fixed.

2. **Schema must match the app.** The app expects the simplified items schema (migration 009). If you use a tenant DB (e.g. Supabase) that was created or last migrated before 008/009, run the migrations on that DB so the schema matches:
   - **Automatic:** Restart the backend; it runs missing migrations for all active/trial tenants (see above).
   - **Manual (e.g. Supabase SQL Editor):** Run in order on the **tenant** database:
     - `migrations/008_deprecate_items_price_columns.sql`
     - `migrations/009_items_simplified_schema.sql`
     If the tenant DB was created from scratch, run `001_initial.sql` through `009_items_simplified_schema.sql` in order so all tables (including `import_jobs`, `items`, `inventory_ledger`) exist and match the app.

3. **Backend must be able to reach Supabase.** If the backend cannot connect to the tenant DB (e.g. `aws-1-eu-west-1.pooler.supabase.com`), you will see "Name or service not known" or "timeout expired". In that case no data is written to Supabase and the progress API may return 503. Fix by: checking Supabase status/maintenance, ensuring your network (or VPN) allows outbound port 5432 to the pooler host, and retrying after connectivity is restored.

4. **Use the tenant URL so import and progress use Supabase.** The Excel import and progress API use the **same database as the request**: with `X-Tenant-Subdomain` (or `X-Tenant-ID`) they use the tenant DB (Supabase); without it they use the default DB. If you open the app at `http://localhost:3000` and never set a tenant, the import runs against the default DB and progress shows numbers from that DB — so Supabase (tenant DB) stays empty. To import into Supabase, open the app from your **tenant URL** (e.g. `https://your-tenant.pharmasight.com` or whatever sets the tenant in the app) so the frontend sends the tenant header and both import and progress use the tenant DB. The progress API now returns `database_scope`: `"tenant"` or `"default"` so you can confirm which DB the numbers are from.
