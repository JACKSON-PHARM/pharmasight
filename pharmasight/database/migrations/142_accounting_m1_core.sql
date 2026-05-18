-- Migration 142: M1 authoritative GL (chart of accounts, fiscal periods, journal entries)

CREATE TABLE IF NOT EXISTS chart_of_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(20) NOT NULL,
    parent_id UUID REFERENCES chart_of_accounts(id) ON DELETE SET NULL,
    control_role VARCHAR(50),
    is_control_account BOOLEAN NOT NULL DEFAULT FALSE,
    normal_balance VARCHAR(10) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chart_of_accounts_category_check CHECK (
        category IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'COGS', 'EXPENSE')
    ),
    CONSTRAINT chart_of_accounts_normal_balance_check CHECK (
        normal_balance IN ('DEBIT', 'CREIT')
    ),
    CONSTRAINT uq_chart_of_accounts_company_code UNIQUE (company_id, code)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chart_of_accounts_company_control_role
    ON chart_of_accounts(company_id, control_role)
    WHERE control_role IS NOT NULL AND is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_chart_of_accounts_company ON chart_of_accounts(company_id);

CREATE TABLE IF NOT EXISTS fiscal_periods (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(40) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    closed_at TIMESTAMPTZ,
    closed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    close_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fiscal_periods_status_check CHECK (status IN ('OPEN', 'CLOSED')),
    CONSTRAINT fiscal_periods_dates_check CHECK (start_date <= end_date),
    CONSTRAINT uq_fiscal_periods_company_name UNIQUE (company_id, name)
);

CREATE INDEX IF NOT EXISTS idx_fiscal_periods_company_dates ON fiscal_periods(company_id, start_date, end_date);

CREATE TABLE IF NOT EXISTS gl_journal_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    fiscal_period_id UUID NOT NULL REFERENCES fiscal_periods(id) ON DELETE RESTRICT,
    journal_number VARCHAR(40) NOT NULL,
    posting_date DATE NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'POSTED',
    source_type VARCHAR(50) NOT NULL,
    source_id UUID NOT NULL,
    posting_kind VARCHAR(50) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    reversal_of_entry_id UUID REFERENCES gl_journal_entries(id) ON DELETE SET NULL,
    posted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    currency_code CHAR(3) NOT NULL DEFAULT 'KES',
    metadata_json JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT gl_journal_entries_status_check CHECK (status IN ('POSTED', 'VOIDED')),
    CONSTRAINT uq_gl_journal_entries_company_idempotency UNIQUE (company_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_gl_journal_entries_company_date ON gl_journal_entries(company_id, posting_date);
CREATE INDEX IF NOT EXISTS idx_gl_journal_entries_source ON gl_journal_entries(company_id, source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_gl_journal_entries_branch ON gl_journal_entries(branch_id, posting_date);

CREATE TABLE IF NOT EXISTS gl_journal_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_entry_id UUID NOT NULL REFERENCES gl_journal_entries(id) ON DELETE CASCADE,
    line_order INTEGER NOT NULL,
    account_id UUID NOT NULL REFERENCES chart_of_accounts(id) ON DELETE RESTRICT,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    debit NUMERIC(20, 4) NOT NULL DEFAULT 0,
    credit NUMERIC(20, 4) NOT NULL DEFAULT 0,
    description TEXT,
    CONSTRAINT gl_journal_lines_debit_credit_check CHECK (
        debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_gl_journal_lines_journal ON gl_journal_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_gl_journal_lines_account ON gl_journal_lines(account_id);

CREATE TABLE IF NOT EXISTS gl_posting_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE SET NULL,
    source_type VARCHAR(50) NOT NULL,
    source_id UUID NOT NULL,
    posting_kind VARCHAR(50) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    error_message TEXT NOT NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_gl_posting_failures_open UNIQUE (company_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_gl_posting_failures_unresolved
    ON gl_posting_failures(company_id, created_at)
    WHERE resolved_at IS NULL;

-- Enforce balanced journals at insert time
CREATE OR REPLACE FUNCTION enforce_gl_journal_balanced()
RETURNS TRIGGER AS $$
DECLARE
    total_debit NUMERIC(20, 4);
    total_credit NUMERIC(20, 4);
BEGIN
    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
    INTO total_debit, total_credit
    FROM gl_journal_lines
    WHERE journal_entry_id = NEW.journal_entry_id;

    IF ABS(total_debit - total_credit) > 0.01 THEN
        RAISE EXCEPTION 'GL journal % is not balanced: debit=% credit=%',
            NEW.journal_entry_id, total_debit, total_credit;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_gl_journal_lines_balanced ON gl_journal_lines;
CREATE CONSTRAINT TRIGGER trg_gl_journal_lines_balanced
    AFTER INSERT OR UPDATE ON gl_journal_lines
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION enforce_gl_journal_balanced();

COMMENT ON TABLE gl_journal_entries IS 'M1 authoritative GL headers — operational source documents only.';
COMMENT ON TABLE chart_of_accounts IS 'Company chart of accounts; control_role resolves system accounts.';
