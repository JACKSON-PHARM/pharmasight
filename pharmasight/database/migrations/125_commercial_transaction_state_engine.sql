-- Layer 2: constitutional commercial transaction state + append-only transition audit.
-- Not wired to sales workflow yet; safe additive schema.

CREATE TABLE IF NOT EXISTS commercial_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    constitutional_state VARCHAR(40) NOT NULL DEFAULT 'DRAFT',
    frozen_resume_state VARCHAR(40),
    sales_invoice_id UUID REFERENCES sales_invoices(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_commercial_transactions_constitutional_state CHECK (
        constitutional_state IN (
            'DRAFT',
            'OPERATIONALLY_COMPLETE',
            'COMMERCIALLY_COMPLETE',
            'BILLING_ACCEPTED',
            'FISCAL_READY',
            'FISCAL_EXTERNALIZED',
            'SETTLEMENT_ACTIVE',
            'SETTLEMENT_CLOSED',
            'DISPUTE_FROZEN',
            'EXCEPTION_HOLD',
            'REVERSED',
            'AMENDED'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_commercial_transactions_company_branch
    ON commercial_transactions (company_id, branch_id);

CREATE INDEX IF NOT EXISTS idx_commercial_transactions_sales_invoice_id
    ON commercial_transactions (sales_invoice_id)
    WHERE sales_invoice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS commercial_transaction_transitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    commercial_transaction_id UUID NOT NULL REFERENCES commercial_transactions(id) ON DELETE CASCADE,
    from_state VARCHAR(40) NOT NULL,
    to_state VARCHAR(40) NOT NULL,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    basis TEXT,
    supersedes_transition_id UUID REFERENCES commercial_transaction_transitions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_commercial_transaction_transitions_from_state CHECK (
        from_state IN (
            'DRAFT',
            'OPERATIONALLY_COMPLETE',
            'COMMERCIALLY_COMPLETE',
            'BILLING_ACCEPTED',
            'FISCAL_READY',
            'FISCAL_EXTERNALIZED',
            'SETTLEMENT_ACTIVE',
            'SETTLEMENT_CLOSED',
            'DISPUTE_FROZEN',
            'EXCEPTION_HOLD',
            'REVERSED',
            'AMENDED'
        )
    ),
    CONSTRAINT ck_commercial_transaction_transitions_to_state CHECK (
        to_state IN (
            'DRAFT',
            'OPERATIONALLY_COMPLETE',
            'COMMERCIALLY_COMPLETE',
            'BILLING_ACCEPTED',
            'FISCAL_READY',
            'FISCAL_EXTERNALIZED',
            'SETTLEMENT_ACTIVE',
            'SETTLEMENT_CLOSED',
            'DISPUTE_FROZEN',
            'EXCEPTION_HOLD',
            'REVERSED',
            'AMENDED'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_commercial_transaction_transitions_tx_created
    ON commercial_transaction_transitions (commercial_transaction_id, created_at);

COMMENT ON TABLE commercial_transactions IS
    'Constitutional commercial transaction spine (Layer 2). Optional link to sales_invoices; not yet enforced on invoice APIs.';
COMMENT ON TABLE commercial_transaction_transitions IS
    'Append-only audit trail for constitutional state transitions.';
