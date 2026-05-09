-- Migration 111: KRA execution-plane phase 1 transactional outbox (sale.completed only)
-- Additive, durable, retry-capable, replay-safe.

CREATE TABLE IF NOT EXISTS kra_event_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    payload_json JSONB NOT NULL,
    processing_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 12,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    leased_until TIMESTAMPTZ,
    lease_owner VARCHAR(120),
    processed_at TIMESTAMPTZ,
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kra_event_outbox_status_available
    ON kra_event_outbox(processing_status, available_at, created_at);
CREATE INDEX IF NOT EXISTS idx_kra_event_outbox_lease
    ON kra_event_outbox(leased_until, lease_owner);
CREATE INDEX IF NOT EXISTS idx_kra_event_outbox_company_branch
    ON kra_event_outbox(company_id, branch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kra_event_outbox_event_type
    ON kra_event_outbox(event_type, created_at DESC);

-- Prevent duplicate sale.completed event creation for same invoice aggregate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_kra_outbox_sale_completed_aggregate
    ON kra_event_outbox(event_type, aggregate_id)
    WHERE event_type = 'sale.completed';
