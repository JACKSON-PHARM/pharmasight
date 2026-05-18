-- Migration 139: Finance E5 — treasury routing dimension + projection/backfill infrastructure
-- cashbook_accounts are treasury routing dimensions ONLY (not GL / ledger accounts).

-- Branch-level finance policy pack override (nullable → inherit from sales_type / workflow)
ALTER TABLE branches
    ADD COLUMN IF NOT EXISTS finance_policy_pack VARCHAR(40);

COMMENT ON COLUMN branches.finance_policy_pack IS
    'Optional override: RETAIL_SIMPLE | WHOLESALE_AR | HOSPITAL_INSURANCE. Not accounting config.';

-- Treasury routing dimension (NOT chart of accounts; no balances stored)
CREATE TABLE IF NOT EXISTS cashbook_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE CASCADE,
    account_code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    routing_type VARCHAR(30) NOT NULL,
    payment_mode VARCHAR(20),
    classification VARCHAR(30) NOT NULL DEFAULT 'branch_finance',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cashbook_accounts_routing_type_check CHECK (
        routing_type IN ('till', 'mpesa', 'bank', 'insurance_pool', 'company_treasury')
    ),
    CONSTRAINT cashbook_accounts_payment_mode_check CHECK (
        payment_mode IS NULL OR payment_mode IN ('cash', 'mpesa', 'bank')
    ),
    CONSTRAINT cashbook_accounts_classification_check CHECK (
        classification IN (
            'operational', 'branch_finance', 'management',
            'confidential', 'executive', 'audit'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cashbook_accounts_company_code
    ON cashbook_accounts(company_id, account_code);

CREATE INDEX IF NOT EXISTS idx_cashbook_accounts_branch
    ON cashbook_accounts(company_id, branch_id) WHERE branch_id IS NOT NULL;

COMMENT ON TABLE cashbook_accounts IS
    'Treasury routing dimension only. NOT ledger accounts; no authoritative balances.';

-- Optional link from operational cashbook entries to treasury bucket
ALTER TABLE cashbook_entries
    ADD COLUMN IF NOT EXISTS cashbook_account_id UUID REFERENCES cashbook_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_cashbook_entries_account
    ON cashbook_entries(cashbook_account_id) WHERE cashbook_account_id IS NOT NULL;

-- Controlled lineage backfill audit (reconstruction runs, not data patching)
CREATE TABLE IF NOT EXISTS finance_backfill_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE CASCADE,
    correlation_group VARCHAR(255) NOT NULL,
    policy_pack_id VARCHAR(40) NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    event_types_filter JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    events_created INTEGER NOT NULL DEFAULT 0,
    events_duplicate INTEGER NOT NULL DEFAULT 0,
    events_failed INTEGER NOT NULL DEFAULT 0,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    detail_json JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT finance_backfill_runs_status_check CHECK (
        status IN ('running', 'completed', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_finance_backfill_runs_company
    ON finance_backfill_runs(company_id, started_at DESC);
