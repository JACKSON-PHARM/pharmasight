-- Migration 078: Company-scoped module entitlements (single shared DB).
-- Enables per-company feature flags; pharmacy is backfilled for all existing companies.

CREATE TABLE IF NOT EXISTS company_modules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    module_name VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_company_modules_company_module'
    ) THEN
        ALTER TABLE company_modules
            ADD CONSTRAINT uq_company_modules_company_module UNIQUE (company_id, module_name);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_company_modules_company_id ON company_modules(company_id);

-- Existing deployments: explicit pharmacy row (app also treats missing pharmacy row as enabled).
INSERT INTO company_modules (company_id, module_name, is_enabled)
SELECT id, 'pharmacy', true
FROM companies
ON CONFLICT (company_id, module_name) DO NOTHING;
