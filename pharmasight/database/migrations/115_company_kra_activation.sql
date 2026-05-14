-- Tenant-scoped KRA execution activation (SaaS onboarding).
-- Infrastructure capability remains ENV-only (worker toggle, Redis, API URLs).

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS kra_enabled BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS kra_mode TEXT NOT NULL DEFAULT 'sandbox';

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS kra_onboarded_at TIMESTAMPTZ NULL;

ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_kra_mode_check;
ALTER TABLE companies
  ADD CONSTRAINT companies_kra_mode_check CHECK (kra_mode IN ('sandbox', 'production'));

COMMENT ON COLUMN companies.kra_enabled IS 'Tenant: allow KRA outbox enqueue and worker-side execution for this company.';
COMMENT ON COLUMN companies.kra_mode IS 'Company fiscal mode label (sandbox vs production); branch credential environment remains authoritative for API calls.';
COMMENT ON COLUMN companies.kra_onboarded_at IS 'First time KRA execution was enabled for this company (set when kra_enabled flips to true).';

-- Preserve behavior for companies already running branch submission before this migration.
UPDATE companies c
SET kra_enabled = true
WHERE EXISTS (
  SELECT 1
  FROM branch_etims_credentials bec
  WHERE bec.company_id = c.id AND bec.enabled IS TRUE
);
