-- Migration 096: Triage records for OPD encounters
-- Separate from consultation notes; one triage snapshot per encounter.

CREATE TABLE IF NOT EXISTS encounter_triage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id UUID NOT NULL UNIQUE REFERENCES encounters(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,

    payment_mode TEXT NULL,
    insurance_scheme TEXT NULL,
    chief_complaint TEXT NULL,
    symptoms TEXT NULL,
    triage_notes TEXT NULL,
    vitals JSONB NULL,

    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_encounter_triage_company_id ON encounter_triage(company_id);
CREATE INDEX IF NOT EXISTS ix_encounter_triage_encounter_id ON encounter_triage(encounter_id);
