-- Company organizational operating model (platform governance layer 3).
-- Branch fiscal doctrine remains on branches.invoice_workflow_type.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS organization_operating_model VARCHAR(40);

ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_organization_operating_model_check;
ALTER TABLE companies ADD CONSTRAINT companies_organization_operating_model_check
    CHECK (
        organization_operating_model IS NULL
        OR organization_operating_model IN (
            'PHARMACY_RETAIL',
            'OUTPATIENT_CLINIC',
            'HYBRID_HOSPITAL',
            'ENTERPRISE_NETWORK'
        )
    );

COMMENT ON COLUMN companies.organization_operating_model IS
    'Platform-defined organizational governance intent. Parent doctrine for branch fiscal workflow; does not replace company_modules capabilities.';
