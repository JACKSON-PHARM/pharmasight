-- Migration 052: Supplier Management extension
-- Extends suppliers and purchase_invoices; adds supplier_payments, allocations,
-- supplier_returns, supplier_return_lines, supplier_ledger_entries.
-- Rollback: drop new tables; alter suppliers/purchase_invoices to drop new columns.

-- 1. Extend suppliers
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS default_payment_terms_days INTEGER;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(20,4);
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS allow_over_credit BOOLEAN DEFAULT FALSE;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS opening_balance NUMERIC(20,4) DEFAULT 0;
COMMENT ON COLUMN suppliers.default_payment_terms_days IS 'Default days until payment due (e.g. 30).';
COMMENT ON COLUMN suppliers.credit_limit IS 'Maximum credit allowed (NULL = no limit).';
COMMENT ON COLUMN suppliers.allow_over_credit IS 'If true, allow exceeding credit_limit.';
COMMENT ON COLUMN suppliers.opening_balance IS 'Opening balance (positive = we owe supplier).';

-- 2. Extend purchase_invoices (supplier invoices)
ALTER TABLE purchase_invoices ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE purchase_invoices ADD COLUMN IF NOT EXISTS internal_reference VARCHAR(255);
COMMENT ON COLUMN purchase_invoices.due_date IS 'Payment due date for aging.';
COMMENT ON COLUMN purchase_invoices.internal_reference IS 'Internal reference/code for the invoice.';

-- 3. supplier_payments
CREATE TABLE IF NOT EXISTS supplier_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    payment_date DATE NOT NULL,
    method VARCHAR(50) NOT NULL,
    reference VARCHAR(255),
    amount NUMERIC(20,4) NOT NULL,
    is_allocated BOOLEAN DEFAULT FALSE,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_company ON supplier_payments(company_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_branch ON supplier_payments(branch_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_supplier ON supplier_payments(supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payments_date ON supplier_payments(payment_date);
COMMENT ON TABLE supplier_payments IS 'Payments made to suppliers. Allocations link to invoices.';

-- 4. supplier_payment_allocations
CREATE TABLE IF NOT EXISTS supplier_payment_allocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    supplier_payment_id UUID NOT NULL REFERENCES supplier_payments(id) ON DELETE CASCADE,
    supplier_invoice_id UUID NOT NULL REFERENCES purchase_invoices(id) ON DELETE CASCADE,
    allocated_amount NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT supplier_payment_alloc_amount_positive CHECK (allocated_amount > 0)
);
CREATE INDEX IF NOT EXISTS idx_supplier_payment_alloc_payment ON supplier_payment_allocations(supplier_payment_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payment_alloc_invoice ON supplier_payment_allocations(supplier_invoice_id);
COMMENT ON TABLE supplier_payment_allocations IS 'Allocation of a supplier payment to specific invoices.';

-- 5. supplier_returns
CREATE TABLE IF NOT EXISTS supplier_returns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    linked_invoice_id UUID REFERENCES purchase_invoices(id) ON DELETE SET NULL,
    return_date DATE NOT NULL,
    reason TEXT,
    total_value NUMERIC(20,4) NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT supplier_returns_status_check CHECK (status IN ('pending', 'approved', 'rejected', 'credited'))
);
CREATE INDEX IF NOT EXISTS idx_supplier_returns_company ON supplier_returns(company_id);
CREATE INDEX IF NOT EXISTS idx_supplier_returns_branch ON supplier_returns(branch_id);
CREATE INDEX IF NOT EXISTS idx_supplier_returns_supplier ON supplier_returns(supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_returns_date ON supplier_returns(return_date);
COMMENT ON TABLE supplier_returns IS 'Goods returned to supplier; when approved reduces stock and creates ledger credit.';

-- 6. supplier_return_lines
CREATE TABLE IF NOT EXISTS supplier_return_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    supplier_return_id UUID NOT NULL REFERENCES supplier_returns(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    quantity NUMERIC(20,4) NOT NULL,
    unit_cost NUMERIC(20,4) NOT NULL,
    line_total NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT supplier_return_lines_qty_positive CHECK (quantity > 0)
);
CREATE INDEX IF NOT EXISTS idx_supplier_return_lines_return ON supplier_return_lines(supplier_return_id);
CREATE INDEX IF NOT EXISTS idx_supplier_return_lines_item ON supplier_return_lines(item_id);
COMMENT ON TABLE supplier_return_lines IS 'Line items for supplier returns; links to item/batch for stock reduction.';

-- 7. supplier_ledger_entries (single source of truth for supplier financial tracking)
CREATE TABLE IF NOT EXISTS supplier_ledger_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    entry_type VARCHAR(50) NOT NULL,
    reference_id UUID,
    debit NUMERIC(20,4) NOT NULL DEFAULT 0,
    credit NUMERIC(20,4) NOT NULL DEFAULT 0,
    running_balance NUMERIC(20,4),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT supplier_ledger_entry_type_check CHECK (entry_type IN ('invoice', 'payment', 'return', 'adjustment', 'opening_balance')),
    CONSTRAINT supplier_ledger_debit_credit_check CHECK (debit >= 0 AND credit >= 0)
);
CREATE INDEX IF NOT EXISTS idx_supplier_ledger_company ON supplier_ledger_entries(company_id);
CREATE INDEX IF NOT EXISTS idx_supplier_ledger_branch ON supplier_ledger_entries(branch_id);
CREATE INDEX IF NOT EXISTS idx_supplier_ledger_supplier ON supplier_ledger_entries(supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_ledger_date ON supplier_ledger_entries(date);
CREATE INDEX IF NOT EXISTS idx_supplier_ledger_reference ON supplier_ledger_entries(entry_type, reference_id);
COMMENT ON TABLE supplier_ledger_entries IS 'Single source of truth for supplier balances: debit=we owe, credit=we paid/credited.';
