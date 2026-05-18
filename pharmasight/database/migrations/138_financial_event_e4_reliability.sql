-- Migration 138: E4 event reliability, settlement links, replay audit (not accounting)

ALTER TABLE financial_events
    ADD COLUMN IF NOT EXISTS operational_status VARCHAR(32) NOT NULL DEFAULT 'emitted',
    ADD COLUMN IF NOT EXISTS emission_channel VARCHAR(32) NOT NULL DEFAULT 'original',
    ADD COLUMN IF NOT EXISTS correlation_group VARCHAR(255),
    ADD COLUMN IF NOT EXISTS replay_source_failure_id UUID NULL
        REFERENCES financial_event_emission_failures(id) ON DELETE SET NULL;

ALTER TABLE financial_events
    ADD CONSTRAINT chk_financial_events_operational_status
    CHECK (operational_status IN ('emitted', 'replayed', 'compensated', 'duplicate_ignored'));

ALTER TABLE financial_events
    ADD CONSTRAINT chk_financial_events_emission_channel
    CHECK (emission_channel IN ('original', 'replay', 'backfill'));

CREATE INDEX IF NOT EXISTS ix_financial_events_correlation_group
    ON financial_events(company_id, correlation_group)
    WHERE correlation_group IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_financial_events_operational_status
    ON financial_events(company_id, operational_status);

-- Append-only settlement lineage (payment reduces receivable, etc.)
CREATE TABLE IF NOT EXISTS financial_event_settlement_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    settlement_event_id UUID NOT NULL REFERENCES financial_events(id) ON DELETE RESTRICT,
    settles_event_id UUID NOT NULL REFERENCES financial_events(id) ON DELETE RESTRICT,
    amount_settled NUMERIC(20, 4) NOT NULL CHECK (amount_settled >= 0),
    settlement_semantic VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_financial_event_settlement_links_idempotency UNIQUE (company_id, idempotency_key),
    CONSTRAINT chk_settlement_semantic CHECK (
        settlement_semantic IN (
            'customer_payment_settles_receivable',
            'supplier_payment_settles_payable',
            'insurance_settlement_settles_claim'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_financial_event_settlement_settlement
    ON financial_event_settlement_links(settlement_event_id);

CREATE INDEX IF NOT EXISTS ix_financial_event_settlement_settles
    ON financial_event_settlement_links(settles_event_id);

-- Replay audit trail (append-only; does not mutate financial_events)
CREATE TABLE IF NOT EXISTS financial_event_replay_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    failure_id UUID NULL REFERENCES financial_event_emission_failures(id) ON DELETE SET NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    replay_result VARCHAR(32) NOT NULL,
    financial_event_id UUID NULL REFERENCES financial_events(id) ON DELETE SET NULL,
    actor_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_financial_event_replay_result CHECK (
        replay_result IN ('created', 'duplicate', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS ix_financial_event_replay_log_company
    ON financial_event_replay_log(company_id, created_at DESC);

ALTER TABLE financial_event_emission_failures
    ADD COLUMN IF NOT EXISTS last_replay_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS last_replay_result VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS resolved_event_id UUID NULL
        REFERENCES financial_events(id) ON DELETE SET NULL;

COMMENT ON TABLE financial_event_settlement_links IS
    'E4 append-only economic settlement relationships between events (not accounting reconciliation).';
