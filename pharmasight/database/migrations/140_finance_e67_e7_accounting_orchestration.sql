-- Migration 140: E6.7 authority hooks + E7 accounting orchestration (interpretation layer only)
-- journal_proposals are derived interpretations — NOT authoritative GL, NOT lineage mutation.

CREATE TABLE IF NOT EXISTS journal_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    proposal_number VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    policy_pack_id VARCHAR(40) NOT NULL DEFAULT 'STANDARD_KENYA',
    source_financial_event_id UUID NOT NULL REFERENCES financial_events(id) ON DELETE RESTRICT,
    reversal_of_proposal_id UUID REFERENCES journal_proposals(id) ON DELETE SET NULL,
    commercial_transaction_id UUID REFERENCES commercial_transactions(id) ON DELETE SET NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    proposal_schema_version INTEGER NOT NULL DEFAULT 1,
    currency_code VARCHAR(3) NOT NULL DEFAULT 'KES',
    total_amount NUMERIC(20, 4) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    governance_metadata_json JSONB NOT NULL DEFAULT '{}',
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    posted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT journal_proposals_status_check CHECK (
        status IN ('draft', 'approved', 'posted', 'superseded', 'voided')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_proposals_company_idempotency
    ON journal_proposals(company_id, idempotency_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_proposals_company_number
    ON journal_proposals(company_id, proposal_number);

CREATE INDEX IF NOT EXISTS idx_journal_proposals_event
    ON journal_proposals(source_financial_event_id);

CREATE TABLE IF NOT EXISTS journal_proposal_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_proposal_id UUID NOT NULL REFERENCES journal_proposals(id) ON DELETE CASCADE,
    line_order INTEGER NOT NULL,
    account_semantic VARCHAR(80) NOT NULL,
    line_direction VARCHAR(10) NOT NULL,
    amount NUMERIC(20, 4) NOT NULL,
    description TEXT,
    CONSTRAINT journal_proposal_lines_direction_check CHECK (
        line_direction IN ('debit', 'credit')
    )
);

CREATE INDEX IF NOT EXISTS idx_journal_proposal_lines_proposal
    ON journal_proposal_lines(journal_proposal_id);

CREATE TABLE IF NOT EXISTS journal_proposal_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_proposal_id UUID NOT NULL REFERENCES journal_proposals(id) ON DELETE CASCADE,
    financial_event_id UUID NOT NULL REFERENCES financial_events(id) ON DELETE RESTRICT,
    link_semantic VARCHAR(50) NOT NULL DEFAULT 'primary_source',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_journal_proposal_evidence UNIQUE (journal_proposal_id, financial_event_id)
);

CREATE TABLE IF NOT EXISTS accounting_posting_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    journal_proposal_id UUID NOT NULL REFERENCES journal_proposals(id) ON DELETE RESTRICT,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    posting_semantic VARCHAR(50) NOT NULL DEFAULT 'interpretation_committed',
    detail_json JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT uq_accounting_posting_records_proposal UNIQUE (journal_proposal_id)
);

COMMENT ON TABLE journal_proposals IS
    'E7 derived accounting interpretation proposals — never mutates financial_events.';
