-- Insurance billing + receivables engine (single DB, company scoped)

CREATE TABLE insurance_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    contact_person VARCHAR(255),
    phone VARCHAR(50),
    email VARCHAR(255),
    address TEXT,
    terms_days NUMERIC(10, 0) NOT NULL DEFAULT 30,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_insurance_providers_company_name ON insurance_providers (company_id, lower(name));
CREATE UNIQUE INDEX uq_insurance_providers_company_code ON insurance_providers (company_id, lower(code));
CREATE INDEX idx_insurance_providers_company_active ON insurance_providers (company_id, is_active);

CREATE TABLE insurance_claims (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    insurance_provider_id UUID NOT NULL REFERENCES insurance_providers(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    claim_number VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'submitted',
    billed_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    approved_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    settled_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    outstanding_amount NUMERIC(20, 4) NOT NULL DEFAULT 0,
    submitted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    due_date DATE,
    notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_insurance_claims_company_number ON insurance_claims (company_id, claim_number);
CREATE INDEX idx_insurance_claims_company_status ON insurance_claims (company_id, status);
CREATE INDEX idx_insurance_claims_provider ON insurance_claims (insurance_provider_id);
CREATE INDEX idx_insurance_claims_invoice ON insurance_claims (sales_invoice_id);

CREATE TABLE insurance_settlements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    insurance_provider_id UUID NOT NULL REFERENCES insurance_providers(id) ON DELETE CASCADE,
    settlement_number VARCHAR(100) NOT NULL,
    settlement_date DATE NOT NULL,
    method VARCHAR(50) NOT NULL DEFAULT 'bank',
    reference VARCHAR(255),
    amount NUMERIC(20, 4) NOT NULL,
    notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_insurance_settlements_company_number ON insurance_settlements (company_id, settlement_number);
CREATE INDEX idx_insurance_settlements_provider ON insurance_settlements (insurance_provider_id);
CREATE INDEX idx_insurance_settlements_date ON insurance_settlements (settlement_date);

CREATE TABLE insurance_settlement_allocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    insurance_settlement_id UUID NOT NULL REFERENCES insurance_settlements(id) ON DELETE CASCADE,
    insurance_claim_id UUID NOT NULL REFERENCES insurance_claims(id) ON DELETE CASCADE,
    allocated_amount NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_insurance_settlement_alloc_settlement ON insurance_settlement_allocations (insurance_settlement_id);
CREATE INDEX idx_insurance_settlement_alloc_claim ON insurance_settlement_allocations (insurance_claim_id);

CREATE TABLE insurance_ledger_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    insurance_provider_id UUID NOT NULL REFERENCES insurance_providers(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    entry_type VARCHAR(50) NOT NULL,
    reference_id UUID,
    debit NUMERIC(20, 4) NOT NULL DEFAULT 0,
    credit NUMERIC(20, 4) NOT NULL DEFAULT 0,
    running_balance NUMERIC(20, 4),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_insurance_ledger_provider_date ON insurance_ledger_entries (insurance_provider_id, date);

ALTER TABLE invoice_payments
ADD COLUMN IF NOT EXISTS insurance_provider_id UUID REFERENCES insurance_providers(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_invoice_payments_insurance_provider_id ON invoice_payments (insurance_provider_id);
