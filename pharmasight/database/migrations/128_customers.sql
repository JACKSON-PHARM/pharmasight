-- Migration 128: B2B customers master (wholesale module)

CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    pin VARCHAR(50),
    contact_person VARCHAR(255),
    phone VARCHAR(50),
    email VARCHAR(255),
    address TEXT,
    city VARCHAR(100),
    county VARCHAR(100),
    customer_type VARCHAR(50) NOT NULL DEFAULT 'PHARMACY',
    default_payment_terms_days INTEGER,
    credit_limit NUMERIC(20, 4),
    allow_over_credit BOOLEAN NOT NULL DEFAULT FALSE,
    credit_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    default_sales_type VARCHAR(20) NOT NULL DEFAULT 'WHOLESALE',
    opening_balance NUMERIC(20, 4) NOT NULL DEFAULT 0,
    notes TEXT,
    portal_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT customers_type_check CHECK (
        customer_type IN ('PHARMACY', 'HOSPITAL', 'CLINIC', 'INSTITUTION', 'OTHER')
    ),
    CONSTRAINT customers_default_sales_type_check CHECK (
        default_sales_type IN ('RETAIL', 'WHOLESALE', 'SUPPLIER')
    )
);

CREATE INDEX IF NOT EXISTS idx_customers_company ON customers(company_id);
CREATE INDEX IF NOT EXISTS idx_customers_company_active ON customers(company_id, is_active);
CREATE INDEX IF NOT EXISTS idx_customers_company_name_lower ON customers(company_id, lower(name));

COMMENT ON TABLE customers IS 'B2B wholesale buyers (pharmacies, institutions). Scoped by company_id.';
COMMENT ON COLUMN customers.opening_balance IS 'Positive = customer owes us (AR opening).';
COMMENT ON COLUMN customers.portal_enabled IS 'Future: allow customer portal login (Phase 5).';

ALTER TABLE sales_invoices
    ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;

ALTER TABLE quotations
    ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_sales_invoices_customer ON sales_invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_quotations_customer ON quotations(customer_id);
