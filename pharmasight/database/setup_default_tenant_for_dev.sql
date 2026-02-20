-- =====================================================
-- Register default DB as a tenant (development / demos)
-- =====================================================
-- Run this on the MASTER database (the DB that contains
-- the `tenants` table). Replace YOUR_DATABASE_URL below
-- with your app's DATABASE_URL (same as in .env).
--
-- After this, stamp upload, signature upload, and PO
-- approve/PDF work without sending X-Tenant-ID or
-- X-Tenant-Subdomain (the app uses this tenant as default).
-- =====================================================

INSERT INTO tenants (
    id,
    name,
    subdomain,
    database_url,
    status,
    admin_email
) VALUES (
    'a0000000-0000-0000-0000-000000000001'::uuid,
    'Default (Development)',
    'default',
    'YOUR_DATABASE_URL',  -- e.g. postgresql://user:pass@host:5432/dbname
    'active',
    'dev@localhost'
)
ON CONFLICT (subdomain) DO UPDATE SET
    database_url = EXCLUDED.database_url,
    name = EXCLUDED.name,
    status = EXCLUDED.status,
    updated_at = CURRENT_TIMESTAMP;
