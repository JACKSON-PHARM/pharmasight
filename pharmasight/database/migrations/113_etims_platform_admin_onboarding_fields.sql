-- Migration 113: eTIMS platform-admin onboarding (Gava Connect / developer.go.ke trace fields)
-- Additive: company trader app name; branch solution label; widen PIN columns for encrypted values.

ALTER TABLE company_kra_profiles
    ADD COLUMN IF NOT EXISTS kra_trader_invoicing_system_name VARCHAR(255);

ALTER TABLE company_kra_profiles
    ALTER COLUMN integrator_pin TYPE TEXT;

ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS etims_solution VARCHAR(50) NOT NULL DEFAULT 'OSCU';

ALTER TABLE branch_etims_credentials
    ALTER COLUMN integrator_pin TYPE TEXT;

COMMENT ON COLUMN company_kra_profiles.kra_trader_invoicing_system_name IS
    'KRA “Trader Invoicing System Name” from developer portal / validation (ops traceability; not sent as OAuth client id).';
COMMENT ON COLUMN branch_etims_credentials.etims_solution IS
    'eTIMS solution type from KRA onboarding (e.g. OSCU); stored for admin traceability.';
