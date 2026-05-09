-- Backfill columns for environments where clinical_services table
-- existed before allowed_departments/strict_department_only were introduced.
-- Safe/idempotent.

ALTER TABLE IF EXISTS clinical_services
    ADD COLUMN IF NOT EXISTS allowed_departments JSONB NULL,
    ADD COLUMN IF NOT EXISTS strict_department_only BOOLEAN NOT NULL DEFAULT FALSE;

-- Ensure unique indexes exist even when table pre-existed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_clinical_services_company_name_ci
    ON clinical_services(company_id, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS uq_clinical_services_company_code_ci
    ON clinical_services(company_id, lower(code))
    WHERE code IS NOT NULL AND length(trim(code)) > 0;
