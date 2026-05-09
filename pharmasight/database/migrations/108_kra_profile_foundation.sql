-- Migration 108: KRA tenant/profile foundation (control plane, pre-async engine)
-- Additive and backward-compatible:
-- 1) company_kra_profiles table (company-level capability/onboarding/health)
-- 2) branch_etims_credentials lifecycle + credential metadata fields

CREATE TABLE IF NOT EXISTS company_kra_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    module_enabled BOOLEAN NOT NULL DEFAULT false,
    default_environment VARCHAR(20) NOT NULL DEFAULT 'sandbox',
    integrator_pin VARCHAR(50),
    onboarding_status VARCHAR(30) NOT NULL DEFAULT 'draft',
    activation_status VARCHAR(30) NOT NULL DEFAULT 'inactive',
    last_health_check_at TIMESTAMPTZ,
    last_successful_sync_at TIMESTAMPTZ,
    last_validation_status VARCHAR(30),
    last_validation_error TEXT,
    credential_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_company_kra_profiles_company_id'
    ) THEN
        ALTER TABLE company_kra_profiles
            ADD CONSTRAINT uq_company_kra_profiles_company_id UNIQUE (company_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_company_kra_profiles_activation_status
    ON company_kra_profiles(activation_status);
CREATE INDEX IF NOT EXISTS idx_company_kra_profiles_module_enabled
    ON company_kra_profiles(module_enabled);

COMMENT ON TABLE company_kra_profiles IS
    'Company-level KRA capability profile: module gate, onboarding/activation state, and health metadata.';

ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS activation_status VARCHAR(30) NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS last_validation_error TEXT,
    ADD COLUMN IF NOT EXISTS last_validation_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_successful_sync_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS apigee_app_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS client_tax_pin VARCHAR(50),
    ADD COLUMN IF NOT EXISTS integrator_pin VARCHAR(50),
    ADD COLUMN IF NOT EXISTS consumer_key VARCHAR(255),
    ADD COLUMN IF NOT EXISTS consumer_secret_encrypted TEXT,
    ADD COLUMN IF NOT EXISTS credential_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS credential_updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS token_last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS token_status VARCHAR(30) NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_branch_etims_credentials_activation_status
    ON branch_etims_credentials(activation_status);
CREATE INDEX IF NOT EXISTS idx_branch_etims_credentials_validation_status
    ON branch_etims_credentials(validation_status);

COMMENT ON COLUMN branch_etims_credentials.activation_status IS
    'draft | configured | validated | active | degraded | disabled | revoked';
COMMENT ON COLUMN branch_etims_credentials.validation_status IS
    'unknown | passed | failed';
COMMENT ON COLUMN branch_etims_credentials.consumer_key IS
    'KRA consumer key / client id (non-secret)';
COMMENT ON COLUMN branch_etims_credentials.consumer_secret_encrypted IS
    'KRA consumer secret (sensitive; masked in APIs)';
