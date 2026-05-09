-- Migration 110: KRA control-plane audit trail
-- Additive table for operational observability and support tooling.

CREATE TABLE IF NOT EXISTS kra_audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE CASCADE,
    actor_user_id UUID,
    event_type VARCHAR(80) NOT NULL,
    event_status VARCHAR(30) NOT NULL DEFAULT 'info',
    message TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kra_audit_events_company_created_at
    ON kra_audit_events(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kra_audit_events_branch_created_at
    ON kra_audit_events(branch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kra_audit_events_event_type
    ON kra_audit_events(event_type);
