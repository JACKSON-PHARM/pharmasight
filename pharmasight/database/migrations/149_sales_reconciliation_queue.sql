-- Durable async reconciliation tracking for batched sales (FEFO/ledger/GL after operational commit).

CREATE TABLE IF NOT EXISTS sales_reconciliation_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    state VARCHAR(40) NOT NULL DEFAULT 'OPERATIONALLY_POSTED',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    operational_posted_at TIMESTAMPTZ,
    inventory_allocated_at TIMESTAMPTZ,
    financially_posted_at TIMESTAMPTZ,
    fully_reconciled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_reconciliation_queue_invoice UNIQUE (sales_invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_reconciliation_queue_state
    ON sales_reconciliation_queue (state)
    WHERE state NOT IN ('FULLY_RECONCILED');

CREATE INDEX IF NOT EXISTS idx_sales_reconciliation_queue_branch_pending
    ON sales_reconciliation_queue (company_id, branch_id, created_at DESC)
    WHERE state IN ('OPERATIONALLY_POSTED', 'FAILED_RETRY_PENDING');

COMMENT ON TABLE sales_reconciliation_queue IS
    'Tracks post-operational-batch reconciliation: FEFO, SALE ledger, GL/KRA side effects.';
