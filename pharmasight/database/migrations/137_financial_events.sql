-- Migration 137: E3 immutable financial_events (economic lineage only — not accounting)

CREATE TABLE IF NOT EXISTS financial_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    operational_domain VARCHAR(40) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    classification VARCHAR(20) NOT NULL,
    event_schema_version INTEGER NOT NULL DEFAULT 1,
    occurred_at TIMESTAMPTZ NOT NULL,
    emitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    amount NUMERIC(20, 4) NOT NULL CHECK (amount >= 0),
    currency_code VARCHAR(3) NOT NULL DEFAULT 'KES',
    economic_direction VARCHAR(32) NOT NULL,
    source_entity_type VARCHAR(80) NOT NULL,
    source_entity_id UUID NOT NULL,
    source_reference VARCHAR(255),
    idempotency_key VARCHAR(255) NOT NULL,
    reversal_of_event_id UUID NULL REFERENCES financial_events(id) ON DELETE RESTRICT,
    caused_by_event_id UUID NULL REFERENCES financial_events(id) ON DELETE RESTRICT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    governance_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_financial_events_company_idempotency UNIQUE (company_id, idempotency_key),
    CONSTRAINT chk_financial_events_classification CHECK (
        classification IN (
            'operational', 'branch_finance', 'management', 'confidential', 'executive', 'audit'
        )
    ),
    CONSTRAINT chk_financial_events_economic_direction CHECK (
        economic_direction IN ('inflow', 'outflow', 'accrual', 'reduction', 'adjustment')
    )
);

CREATE INDEX IF NOT EXISTS ix_financial_events_company_occurred
    ON financial_events(company_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_financial_events_company_branch_occurred
    ON financial_events(company_id, branch_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_financial_events_company_type
    ON financial_events(company_id, event_type);

CREATE INDEX IF NOT EXISTS ix_financial_events_source
    ON financial_events(company_id, source_entity_type, source_entity_id);

CREATE INDEX IF NOT EXISTS ix_financial_events_reversal
    ON financial_events(reversal_of_event_id)
    WHERE reversal_of_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_financial_events_caused_by
    ON financial_events(caused_by_event_id)
    WHERE caused_by_event_id IS NOT NULL;

COMMENT ON TABLE financial_events IS
    'E3 append-only economic lineage. Corrections via compensating events only — not GL postings.';

-- Repair queue for failed emissions (observable, replayable — not async workers)
CREATE TABLE IF NOT EXISTS financial_event_emission_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NULL REFERENCES branches(id) ON DELETE SET NULL,
    operational_domain VARCHAR(40) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    source_entity_type VARCHAR(80) NOT NULL,
    source_entity_id UUID NOT NULL,
    source_reference VARCHAR(255),
    occurred_at TIMESTAMPTZ NOT NULL,
    amount NUMERIC(20, 4) NOT NULL,
    currency_code VARCHAR(3) NOT NULL DEFAULT 'KES',
    economic_direction VARCHAR(32) NOT NULL,
    classification VARCHAR(20) NOT NULL,
    event_schema_version INTEGER NOT NULL DEFAULT 1,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    governance_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financial_event_emission_failures_unresolved
    ON financial_event_emission_failures(company_id, created_at DESC)
    WHERE resolved_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_event_emission_failures_idempotency
    ON financial_event_emission_failures(company_id, idempotency_key)
    WHERE resolved_at IS NULL;
