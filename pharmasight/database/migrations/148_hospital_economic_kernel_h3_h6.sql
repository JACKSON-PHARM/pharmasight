-- Migration 148: Hospital kernel H3–H6 — authorizations, recognition ledger, claim lines, discharge

CREATE TABLE IF NOT EXISTS care_authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    pfj_id UUID NOT NULL REFERENCES patient_financial_journeys(id) ON DELETE CASCADE,
    care_charge_id UUID NULL REFERENCES care_charges(id) ON DELETE SET NULL,
    insurance_provider_id UUID NULL REFERENCES insurance_providers(id) ON DELETE SET NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'approved', 'partial', 'denied', 'expired')),
    reference_number VARCHAR(100) NULL,
    requested_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    approved_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    valid_from DATE NULL,
    valid_until DATE NULL,
    notes TEXT NULL,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_care_authorizations_pfj ON care_authorizations(pfj_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hospital_recognition_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    pfj_id UUID NOT NULL REFERENCES patient_financial_journeys(id) ON DELETE CASCADE,
    care_charge_id UUID NOT NULL REFERENCES care_charges(id) ON DELETE CASCADE,
    allocation_line_id UUID NOT NULL REFERENCES liability_allocation_lines(id) ON DELETE CASCADE,
    obligor_type VARCHAR(20) NOT NULL,
    recognized_amount NUMERIC(20, 4) NOT NULL,
    financial_event_id UUID NULL REFERENCES financial_events(id) ON DELETE SET NULL,
    recognized_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (allocation_line_id, obligor_type)
);

CREATE TABLE IF NOT EXISTS insurance_claim_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insurance_claim_id UUID NOT NULL REFERENCES insurance_claims(id) ON DELETE CASCADE,
    care_charge_id UUID NOT NULL REFERENCES care_charges(id) ON DELETE CASCADE,
    amount_inclusive NUMERIC(20, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (insurance_claim_id, care_charge_id)
);
CREATE INDEX IF NOT EXISTS ix_insurance_claim_lines_charge ON insurance_claim_lines(care_charge_id);

ALTER TABLE insurance_claims
    ADD COLUMN IF NOT EXISTS pfj_id UUID NULL REFERENCES patient_financial_journeys(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_insurance_claims_pfj ON insurance_claims(pfj_id) WHERE pfj_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS pfj_discharge_settlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    pfj_id UUID NOT NULL REFERENCES patient_financial_journeys(id) ON DELETE CASCADE,
    patient_residual NUMERIC(20, 4) NOT NULL DEFAULT 0,
    insurer_outstanding NUMERIC(20, 4) NOT NULL DEFAULT 0,
    notes TEXT NULL,
    closed_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pfj_id)
);
