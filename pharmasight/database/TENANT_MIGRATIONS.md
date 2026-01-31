# Tenant Migrations – Transmitting Schema Changes Across Tenants

This doc explains how schema changes (new columns, tables, etc.) are applied to **all tenants** so the app stays consistent without manually running SQL on each tenant.

## How It Works

- **Migrations live in** `database/migrations/` as **numbered SQL files**: `001_initial.sql`, `002_*.sql`, `003_*.sql`, `004_*.sql`, …
- Each **tenant database** has a `schema_migrations` table that records which versions have been applied.
- **New tenants**: When a tenant is provisioned, all migrations in `database/migrations/` are run in order. New tenants therefore get the full current schema (all features).
- **Existing tenants**: On **backend startup**, the app runs `run_tenant_migrations()` and applies **missing** migrations to every tenant that has a `database_url` and status **trial** or **active** (suspended/cancelled tenants are skipped).
- So: **one place to add a change** → it is applied to **new** tenants at provision time and to **existing** tenants on the next deploy/restart.

## Adding a New Schema Change (So All Tenants Get It)

1. **Add a new migration file** in `database/migrations/` with the next number, e.g.:
   - `005_add_my_feature.sql`
   - Use `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` so it is safe to run on DBs that might already have the change.

2. **Deploy** (or restart the backend). On startup, the migration service will:
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
| **New tenant created today** | Provisioning runs all migrations (001 … 004 …); new tenant gets full schema. |
| **Existing tenant (trial/active)** | Next backend startup runs any new migration (e.g. 004) on that tenant’s DB. |
| **Existing tenant (suspended/cancelled)** | Skipped on startup; no automatic migration. |
| **You add 005_*.sql and deploy** | All active/trial tenants get 005 on next startup; new tenants get it at provision. |

## Current migrations (reference)

- **001_initial.sql** – Base schema (companies, branches, users, items, sales_invoices, etc.)
- **002_add_user_username_and_invitation.sql** – User username and invitation fields
- **003_quotations_orders_stocktake_import.sql** – Quotations, orders, stock take, import jobs; sales_invoices status/batched/customer_phone
- **004_add_items_vat_category.sql** – items.vat_category
- **005_add_sales_invoices_missing_columns.sql** – sales_invoices.total_inclusive, sales_type (for tenants created from older schema)

So you do **not** run `add_items_vat_category.sql` on each tenant by hand. The same change is in `database/migrations/004_add_items_vat_category.sql` and is applied to all relevant tenants automatically.
