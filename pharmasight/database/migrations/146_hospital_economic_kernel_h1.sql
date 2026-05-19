-- Migration 146: Hospital Economic Kernel H1 — PFJ + care_charges (constitutional accrual layer)
-- Does NOT alter invoice/claim authority; bridges via nullable FKs only.

CREATE TABLE IF NOT EXISTS patient_financial_journeys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'accruing', 'pending_discharge', 'financial_closed', 'archived')),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ NULL,
    intake_payment_mode_hint TEXT NULL,
    intake_insurance_scheme_hint TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pfj_company_patient ON patient_financial_journeys(company_id, patient_id);
CREATE INDEX IF NOT EXISTS ix_pfj_company_status ON patient_financial_journeys(company_id, status);

-- One open PFJ per patient per company (enforced at app layer; partial unique for active statuses)
CREATE UNIQUE INDEX IF NOT EXISTS uq_pfj_company_patient_open
    ON patient_financial_journeys(company_id, patient_id)
    WHERE status IN ('open', 'accruing', 'pending_discharge');

CREATE TABLE IF NOT EXISTS care_charges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    pfj_id UUID NOT NULL REFERENCES patient_financial_journeys(id) ON DELETE CASCADE,
    encounter_id UUID NULL REFERENCES encounters(id) ON DELETE SET NULL,
    charge_kind VARCHAR(40) NOT NULL
        CHECK (charge_kind IN (
            'consultation', 'lab', 'pharmacy', 'procedure', 'accommodation', 'radiology', 'other'
        )),
    accrual_status VARCHAR(20) NOT NULL DEFAULT 'accrued'
        CHECK (accrual_status IN ('provisional', 'accrued', 'reversed')),
    clinical_trigger VARCHAR(30) NOT NULL DEFAULT 'performed'
        CHECK (clinical_trigger IN (
            'ordered', 'performed', 'resulted', 'dispensed', 'completed', 'scheduled'
        )),
    source_entity_type VARCHAR(80) NOT NULL,
    source_entity_id UUID NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    item_id UUID NULL REFERENCES items(id) ON DELETE SET NULL,
    clinical_service_id UUID NULL REFERENCES clinical_services(id) ON DELETE SET NULL,
    quantity NUMERIC(20, 4) NOT NULL DEFAULT 1,
    unit_name VARCHAR(50) NULL,
    amount_exclusive NUMERIC(20, 4) NOT NULL DEFAULT 0,
    vat_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    amount_inclusive NUMERIC(20, 4) NOT NULL DEFAULT 0,
    currency_code VARCHAR(3) NOT NULL DEFAULT 'KES',
    accrued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reversed_at TIMESTAMPTZ NULL,
    reversal_of_charge_id UUID NULL REFERENCES care_charges(id) ON DELETE SET NULL,
    -- Transitional bridge to retail invoice artifact (NOT authoritative)
    sales_invoice_id UUID NULL REFERENCES sales_invoices(id) ON DELETE SET NULL,
    sales_invoice_item_id UUID NULL REFERENCES sales_invoice_items(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_care_charges_pfj ON care_charges(pfj_id, accrued_at DESC);
CREATE INDEX IF NOT EXISTS ix_care_charges_encounter ON care_charges(encounter_id) WHERE encounter_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_care_charges_company_accrued ON care_charges(company_id, accrued_at DESC);

-- Idempotent accrual: one active accrued row per operational source
CREATE UNIQUE INDEX IF NOT EXISTS uq_care_charges_source_active
    ON care_charges(company_id, source_entity_type, source_entity_id)
    WHERE accrual_status = 'accrued' AND reversed_at IS NULL;

ALTER TABLE encounters
    ADD COLUMN IF NOT EXISTS pfj_id UUID NULL REFERENCES patient_financial_journeys(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_encounters_pfj_id ON encounters(pfj_id) WHERE pfj_id IS NOT NULL;

COMMENT ON TABLE patient_financial_journeys IS
    'Hospital economic root — longitudinal container; not an invoice or claim.';
COMMENT ON TABLE care_charges IS
    'Immutable accrued care value facts; liabilities/claims/invoices derive from charges.';
COMMENT ON COLUMN care_charges.sales_invoice_id IS
    'Transitional OPD bridge only — invoice is presentation artifact, not economic root.';
