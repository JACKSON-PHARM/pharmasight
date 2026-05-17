-- Migration 129: Customer AR (mirror supplier management)

ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS amount_paid NUMERIC(20, 4) NOT NULL DEFAULT 0;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS balance NUMERIC(20, 4);

COMMENT ON COLUMN sales_invoices.due_date IS 'Payment due date for AR aging.';
COMMENT ON COLUMN sales_invoices.amount_paid IS 'Denormalized from customer_payment_allocations + POS payments.';
COMMENT ON COLUMN sales_invoices.balance IS 'Remaining balance (total_inclusive - settled).';

CREATE TABLE IF NOT EXISTS customer_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    payment_date DATE NOT NULL,
    method VARCHAR(50) NOT NULL,
    reference VARCHAR(255),
    amount NUMERIC(20, 4) NOT NULL,
    is_allocated BOOLEAN DEFAULT FALSE,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_payments_company ON customer_payments(company_id);
CREATE INDEX IF NOT EXISTS idx_customer_payments_branch ON customer_payments(branch_id);
CREATE INDEX IF NOT EXISTS idx_customer_payments_customer ON customer_payments(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_payments_date ON customer_payments(payment_date);

CREATE TABLE IF NOT EXISTS customer_payment_allocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_payment_id UUID NOT NULL REFERENCES customer_payments(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    allocated_amount NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT customer_payment_alloc_amount_positive CHECK (allocated_amount > 0)
);
CREATE INDEX IF NOT EXISTS idx_customer_payment_alloc_payment ON customer_payment_allocations(customer_payment_id);
CREATE INDEX IF NOT EXISTS idx_customer_payment_alloc_invoice ON customer_payment_allocations(sales_invoice_id);

CREATE TABLE IF NOT EXISTS customer_ledger_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    entry_type VARCHAR(50) NOT NULL,
    reference_id UUID,
    debit NUMERIC(20, 4) NOT NULL DEFAULT 0,
    credit NUMERIC(20, 4) NOT NULL DEFAULT 0,
    running_balance NUMERIC(20, 4),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT customer_ledger_entry_type_check CHECK (
        entry_type IN ('invoice', 'payment', 'credit_note', 'adjustment', 'opening_balance')
    ),
    CONSTRAINT customer_ledger_debit_credit_check CHECK (debit >= 0 AND credit >= 0)
);
CREATE INDEX IF NOT EXISTS idx_customer_ledger_company ON customer_ledger_entries(company_id);
CREATE INDEX IF NOT EXISTS idx_customer_ledger_branch ON customer_ledger_entries(branch_id);
CREATE INDEX IF NOT EXISTS idx_customer_ledger_customer ON customer_ledger_entries(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_ledger_date ON customer_ledger_entries(date);
