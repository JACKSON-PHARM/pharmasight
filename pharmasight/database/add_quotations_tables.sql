-- =====================================================
-- ADD QUOTATIONS TABLES
-- Migration script to add quotations and quotation_items tables
-- =====================================================

-- Create quotations table
CREATE TABLE IF NOT EXISTS quotations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    quotation_no VARCHAR(100) NOT NULL,
    quotation_date DATE NOT NULL,
    customer_name VARCHAR(255),
    customer_pin VARCHAR(50),
    reference VARCHAR(255),
    notes TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    total_exclusive NUMERIC(20, 4) DEFAULT 0,
    vat_rate NUMERIC(5, 2) DEFAULT 16.00,
    vat_amount NUMERIC(20, 4) DEFAULT 0,
    discount_amount NUMERIC(20, 4) DEFAULT 0,
    total_inclusive NUMERIC(20, 4) DEFAULT 0,
    converted_to_invoice_id UUID REFERENCES sales_invoices(id),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    valid_until DATE,
    UNIQUE(quotation_no)
);

COMMENT ON TABLE quotations IS 'Sales Quotation document. Does not affect stock until converted to invoice.';
COMMENT ON COLUMN quotations.status IS 'draft, sent, accepted, converted, cancelled';
COMMENT ON COLUMN quotations.converted_to_invoice_id IS 'Link to sales invoice if quotation was converted';

-- Create quotation_items table
CREATE TABLE IF NOT EXISTS quotation_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    quotation_id UUID NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20, 4) NOT NULL,
    unit_price_exclusive NUMERIC(20, 4) NOT NULL,
    discount_percent NUMERIC(5, 2) DEFAULT 0,
    discount_amount NUMERIC(20, 4) DEFAULT 0,
    vat_rate NUMERIC(5, 2) DEFAULT 16.00,
    vat_amount NUMERIC(20, 4) DEFAULT 0,
    line_total_exclusive NUMERIC(20, 4) NOT NULL,
    line_total_inclusive NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE quotation_items IS 'Line items for quotations. No stock allocation or ledger entries.';

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_quotations_branch_id ON quotations(branch_id);
CREATE INDEX IF NOT EXISTS idx_quotations_company_id ON quotations(company_id);
CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status);
CREATE INDEX IF NOT EXISTS idx_quotations_quotation_date ON quotations(quotation_date);
CREATE INDEX IF NOT EXISTS idx_quotation_items_quotation_id ON quotation_items(quotation_id);
CREATE INDEX IF NOT EXISTS idx_quotation_items_item_id ON quotation_items(item_id);
