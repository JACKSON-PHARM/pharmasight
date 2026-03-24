-- Migration: Add demo/plan fields to tenants (MASTER database only)
--
-- Apply this to the same Postgres instance your app uses for MASTER_DB_URL /
-- tenant registry (e.g. Supabase project for master metadata, or Render env).
-- NOT the per-tenant Supabase databases.
--
-- If this migration is missing, the API returns 500 on any code path that loads
-- Tenant via SQLAlchemy (e.g. GET /api/users/..., POST /api/onboarding/complete-tenant-invite,
-- authenticated routes that resolve the default tenant).
-- Symptom in logs: psycopg2.errors.UndefinedColumn: column tenants.plan_type does not exist
--
-- Safe to run on existing master database; defaults preserve current behaviour.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) NOT NULL DEFAULT 'paid',
    ADD COLUMN IF NOT EXISTS demo_expires_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS product_limit INT NULL,
    ADD COLUMN IF NOT EXISTS branch_limit INT NULL,
    ADD COLUMN IF NOT EXISTS user_limit INT NULL;

