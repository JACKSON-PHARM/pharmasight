# Tenant DB Provisioning

Locked architecture: **one Supabase project per tenant**. Human creates the project; admin pastes the DB URL once. We run migrations and register. `database_url` is **immutable** after provisioning.

## 1. Create Supabase project (manual)

Create a new Supabase project for the tenant (e.g. "PharmaSight – PHARMASIGHT MEDS LTD"). Each project = one Postgres database.

## 2. Get direct Postgres URL

In the project: **Settings → Database → Connection string → URI** (direct, port 5432). Use the project’s database password.

## 3. Provision tenant DB (automated)

From repo root:

```bash
cd pharmasight/backend
python provision_tenant_db.py "PHARMASIGHT MEDS LTD" --url "postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres"
```

Or by subdomain:

```bash
python provision_tenant_db.py --subdomain pharmasight-meds-ltd --url "postgresql://..."
```

This will:

- Run all migrations from `pharmasight/database/migrations/` on that database
- Set `tenant.database_name` and `tenant.database_url` in the master DB
- **Refuse** if the tenant already has a `database_url` (immutable)

## 4. Migrations

- **On provision:** all migrations are applied to the new tenant DB.
- **On app startup:** missing migrations are applied for **all** tenants with a `database_url`.
- Migrations live in `pharmasight/database/migrations/` as ordered SQL files (`001_*.sql`, `002_*.sql`, …).
- Each tenant DB has a `schema_migrations` table used to track applied versions.

No manual per-tenant migration scripts. Schema changes only via new migration files.
