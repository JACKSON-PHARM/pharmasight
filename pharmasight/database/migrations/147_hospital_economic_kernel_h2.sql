-- Migration 147: Hospital Economic Kernel H2 — coverage profiles + versioned liability allocation

CREATE TABLE IF NOT EXISTS pfj_coverage_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    pfj_id UUID NOT NULL REFERENCES patient_financial_journeys(id) ON DELETE CASCADE,
    coverage_role VARCHAR(20) NOT NULL DEFAULT 'primary'
        CHECK (coverage_role IN ('primary', 'secondary')),
    obligor_route VARCHAR(20) NOT NULL DEFAULT 'self_pay'
        CHECK (obligor_route IN ('self_pay', 'insurance', 'employer', 'mixed')),
    insurance_provider_id UUID NULL REFERENCES insurance_providers(id) ON DELETE SET NULL,
    employer_name TEXT NULL,
    member_id TEXT NULL,
    policy_number TEXT NULL,
    insurer_coverage_percent NUMERIC(8, 4) NOT NULL DEFAULT 80,
    patient_copay_percent NUMERIC(8, 4) NULL,
    patient_copay_fixed NUMERIC(20, 4) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pfj_coverage_profiles_pfj ON pfj_coverage_profiles(pfj_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pfj_coverage_primary_active
    ON pfj_coverage_profiles(pfj_id, coverage_role)
    WHERE is_active = TRUE AND coverage_role = 'primary';

CREATE TABLE IF NOT EXISTS liability_allocation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    pfj_id UUID NOT NULL REFERENCES patient_financial_journeys(id) ON DELETE CASCADE,
    care_charge_id UUID NOT NULL REFERENCES care_charges(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    allocation_reason VARCHAR(40) NOT NULL DEFAULT 'initial'
        CHECK (allocation_reason IN (
            'initial', 'coverage_change', 'denial_reallocation', 'manual', 'self_pay_default'
        )),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded')),
    gross_amount_inclusive NUMERIC(20, 4) NOT NULL DEFAULT 0,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_at TIMESTAMPTZ NULL,
    superseded_by_run_id UUID NULL REFERENCES liability_allocation_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_liability_runs_charge ON liability_allocation_runs(care_charge_id, version DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_liability_run_active_per_charge
    ON liability_allocation_runs(care_charge_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS liability_allocation_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES liability_allocation_runs(id) ON DELETE CASCADE,
    obligor_type VARCHAR(20) NOT NULL
        CHECK (obligor_type IN ('patient', 'insurer', 'employer', 'guarantor')),
    insurance_provider_id UUID NULL REFERENCES insurance_providers(id) ON DELETE SET NULL,
    employer_ref TEXT NULL,
    amount_inclusive NUMERIC(20, 4) NOT NULL DEFAULT 0,
    line_kind VARCHAR(30) NOT NULL DEFAULT 'obligated'
        CHECK (line_kind IN ('obligated', 'pending_authorization', 'denied')),
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_liability_lines_run ON liability_allocation_lines(run_id);

COMMENT ON TABLE pfj_coverage_profiles IS 'Who may pay for a PFJ — hints for split logic; not AR.';
COMMENT ON TABLE liability_allocation_runs IS 'Versioned liability split for a care charge; one active run per charge.';
COMMENT ON TABLE liability_allocation_lines IS 'Obligor slices; sum on active run must equal charge gross.';
