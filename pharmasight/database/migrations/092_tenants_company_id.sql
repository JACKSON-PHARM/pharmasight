-- Migration 092: Link tenants to companies (Option B — infra projection must reference business root).
-- PREREQ: public.tenants, public.users, public.user_branch_roles, public.branches, public.companies
-- in the same database as tenants (typical when master and app share DATABASE_URL).

-- 1) Add column (nullable until backfill completes)
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS company_id UUID;

COMMENT ON COLUMN tenants.company_id IS 'FK target to app companies.id (same UUID in app DB); mandatory for auth/routing integrity.';

-- 2) Backfill: tenant.admin_user_id → user_branch_roles → branches.company_id
UPDATE tenants t
SET company_id = x.company_id
FROM (
    SELECT DISTINCT ON (t2.id)
        t2.id AS tenant_id,
        b.company_id AS company_id
    FROM tenants t2
    JOIN users u ON u.id = t2.admin_user_id AND u.deleted_at IS NULL
    JOIN user_branch_roles ubr ON ubr.user_id = u.id
    JOIN branches b ON b.id = ubr.branch_id
    WHERE b.company_id IS NOT NULL
    ORDER BY t2.id, b.company_id
) x
WHERE t.id = x.tenant_id
  AND t.company_id IS NULL;

-- 3) Backfill: tenant.admin_email → users.email → branches (covers demos before admin_user_id was set)
UPDATE tenants t
SET company_id = x.company_id
FROM (
    SELECT DISTINCT ON (t2.id)
        t2.id AS tenant_id,
        b.company_id AS company_id
    FROM tenants t2
    JOIN users u ON lower(trim(u.email)) = lower(trim(t2.admin_email)) AND u.deleted_at IS NULL
    JOIN user_branch_roles ubr ON ubr.user_id = u.id
    JOIN branches b ON b.id = ubr.branch_id
    WHERE b.company_id IS NOT NULL
    ORDER BY t2.id, b.company_id
) x
WHERE t.id = x.tenant_id
  AND t.company_id IS NULL;

-- 4) Legacy fallback: tenant name ↔ company name (multiple tenants may share one company — allowed for migration)
UPDATE tenants t
SET company_id = c.id
FROM companies c
WHERE t.company_id IS NULL
  AND lower(trim(t.name)) = lower(trim(c.name));

-- 5) Single-company DB: any orphan tenant → that company
UPDATE tenants t
SET company_id = (SELECT c.id FROM companies c ORDER BY c.created_at ASC LIMIT 1)
WHERE t.company_id IS NULL
  AND (SELECT COUNT(*) FROM companies) = 1;

-- 6) Last resort: shell company + HQ branch per tenant still NULL (guarantees NOT NULL can succeed)
DO $mig$
DECLARE
    rec RECORD;
    new_company_id UUID;
BEGIN
    FOR rec IN
        SELECT id, name, subdomain
        FROM tenants
        WHERE company_id IS NULL
    LOOP
        INSERT INTO companies (id, name, currency, timezone, is_active)
        VALUES (
            uuid_generate_v4(),
            LEFT(
                COALESCE(NULLIF(trim(rec.name), ''), NULLIF(trim(rec.subdomain), ''), 'Organization'),
                250
            ),
            'KES',
            'Africa/Nairobi',
            TRUE
        )
        RETURNING id INTO new_company_id;

        INSERT INTO branches (id, company_id, name, code, is_active, is_hq)
        VALUES (uuid_generate_v4(), new_company_id, 'Head Office', 'HQ', TRUE, TRUE);

        UPDATE tenants SET company_id = new_company_id WHERE id = rec.id;
    END LOOP;
END
$mig$;

-- 7) Enforce NOT NULL
ALTER TABLE tenants ALTER COLUMN company_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tenants_company_id ON tenants(company_id);
