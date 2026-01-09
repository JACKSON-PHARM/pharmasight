-- =====================================================
-- PHARMASIGHT DATABASE SCHEMA
-- Pharmacy Management System - KRA Compliant
-- =====================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =====================================================
-- MULTI-TENANCY & AUTH
-- =====================================================

-- Companies (Multi-tenant support)
CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    registration_number VARCHAR(100),
    pin VARCHAR(50),
    logo_url TEXT,
    phone VARCHAR(50),
    email VARCHAR(255),
    address TEXT,
    currency VARCHAR(10) DEFAULT 'KES',
    timezone VARCHAR(50) DEFAULT 'Africa/Nairobi',
    fiscal_start_date DATE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Branches
CREATE TABLE branches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50),
    address TEXT,
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- User Roles
CREATE TABLE user_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- User Branch Roles (Many-to-many: users can have different roles per branch)
CREATE TABLE user_branch_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL, -- Supabase Auth user_id
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES user_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, branch_id, role_id)
);

-- =====================================================
-- ITEM MASTER DATA
-- =====================================================

-- Items (SKUs)
CREATE TABLE items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    generic_name VARCHAR(255),
    sku VARCHAR(100),
    barcode VARCHAR(100),
    category VARCHAR(100),
    base_unit VARCHAR(50) NOT NULL, -- tablet, ml, gram, etc.
    default_cost NUMERIC(20,4) DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Item Units (Breaking Bulk Configuration)
CREATE TABLE item_units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_name VARCHAR(50) NOT NULL, -- box, carton, tablet, etc.
    multiplier_to_base NUMERIC(20,4) NOT NULL, -- e.g., 1 box = 100 tablets
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, unit_name)
);

-- =====================================================
-- PRICING CONFIGURATION
-- =====================================================

-- Company Pricing Defaults
CREATE TABLE company_pricing_defaults (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    default_markup_percent NUMERIC(10,2) DEFAULT 30.00,
    rounding_rule VARCHAR(50) DEFAULT 'nearest_1', -- nearest_1, nearest_5, nearest_10
    min_margin_percent NUMERIC(10,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id)
);

-- Item-Specific Pricing
CREATE TABLE item_pricing (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    markup_percent NUMERIC(10,2),
    min_margin_percent NUMERIC(10,2),
    rounding_rule VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id)
);

-- =====================================================
-- SUPPLIERS
-- =====================================================

-- Suppliers
CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    pin VARCHAR(50),
    contact_person VARCHAR(255),
    phone VARCHAR(50),
    email VARCHAR(255),
    address TEXT,
    credit_terms INTEGER, -- days
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- INVENTORY LEDGER (CORE - APPEND ONLY)
-- =====================================================

-- Inventory Ledger (Single Source of Truth)
CREATE TABLE inventory_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    transaction_type VARCHAR(50) NOT NULL, -- PURCHASE, SALE, ADJUSTMENT, TRANSFER, OPENING_BALANCE
    reference_type VARCHAR(50), -- purchase_invoice, sales_invoice, adjustment, grn
    reference_id UUID,
    quantity_delta INTEGER NOT NULL, -- Positive = add stock, Negative = remove stock (BASE UNITS)
    unit_cost NUMERIC(20,4) NOT NULL, -- Cost per base unit
    total_cost NUMERIC(20,4) NOT NULL, -- quantity_delta * unit_cost
    created_by UUID NOT NULL, -- User ID
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    -- Indexes will be added below
    CONSTRAINT quantity_delta_not_zero CHECK (quantity_delta != 0)
);

-- Critical Indexes for Inventory Ledger
CREATE INDEX idx_inventory_ledger_item ON inventory_ledger(item_id);
CREATE INDEX idx_inventory_ledger_branch ON inventory_ledger(branch_id);
CREATE INDEX idx_inventory_ledger_expiry ON inventory_ledger(expiry_date);
CREATE INDEX idx_inventory_ledger_company ON inventory_ledger(company_id);
CREATE INDEX idx_inventory_ledger_reference ON inventory_ledger(reference_type, reference_id);
CREATE INDEX idx_inventory_ledger_batch ON inventory_ledger(item_id, batch_number, expiry_date);

-- =====================================================
-- PURCHASES
-- =====================================================

-- Goods Received Notes (GRN)
CREATE TABLE grns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    grn_no VARCHAR(100) NOT NULL,
    date_received DATE NOT NULL,
    total_cost NUMERIC(20,4) DEFAULT 0,
    notes TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, grn_no)
);

-- GRN Line Items
CREATE TABLE grn_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    grn_id UUID NOT NULL REFERENCES grns(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL, -- In purchase unit
    unit_cost NUMERIC(20,4) NOT NULL, -- Cost per purchase unit
    batch_number VARCHAR(200),
    expiry_date DATE,
    total_cost NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Purchase Invoices (VAT Input)
CREATE TABLE purchase_invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    invoice_number VARCHAR(100) NOT NULL, -- Supplier's invoice number
    pin_number VARCHAR(100), -- Supplier's PIN
    invoice_date DATE NOT NULL,
    linked_grn_id UUID REFERENCES grns(id),
    total_exclusive NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    total_inclusive NUMERIC(20,4) DEFAULT 0,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, invoice_number)
);

-- Purchase Invoice Line Items
CREATE TABLE purchase_invoice_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_invoice_id UUID NOT NULL REFERENCES purchase_invoices(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    unit_cost_exclusive NUMERIC(20,4) NOT NULL,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    line_total_exclusive NUMERIC(20,4) NOT NULL,
    line_total_inclusive NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- SALES (KRA COMPLIANT)
-- =====================================================

-- Sales Invoices (KRA Document)
CREATE TABLE sales_invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    invoice_no VARCHAR(100) NOT NULL, -- Sequential, KRA compliant
    invoice_date DATE NOT NULL,
    customer_name VARCHAR(255),
    customer_pin VARCHAR(50),
    payment_mode VARCHAR(50) NOT NULL, -- cash, mpesa, credit, bank
    payment_status VARCHAR(50) DEFAULT 'PAID', -- PAID, PARTIAL, CREDIT
    total_exclusive NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    discount_amount NUMERIC(20,4) DEFAULT 0,
    total_inclusive NUMERIC(20,4) DEFAULT 0,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, invoice_no)
);

-- Sales Invoice Line Items
CREATE TABLE sales_invoice_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    batch_id UUID REFERENCES inventory_ledger(id), -- Reference to ledger entry
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL, -- In sale unit
    unit_price_exclusive NUMERIC(20,4) NOT NULL,
    discount_percent NUMERIC(5,2) DEFAULT 0,
    discount_amount NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    line_total_exclusive NUMERIC(20,4) NOT NULL,
    line_total_inclusive NUMERIC(20,4) NOT NULL,
    unit_cost_used NUMERIC(20,4), -- For margin calculation
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Payments (Settlement of Invoices)
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    payment_no VARCHAR(100) NOT NULL,
    payment_date DATE NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    payment_mode VARCHAR(50) NOT NULL, -- cash, mpesa, bank, cheque
    reference_number VARCHAR(100),
    notes TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, payment_no)
);

-- =====================================================
-- RETURNS & CREDIT NOTES (KRA COMPLIANT)
-- =====================================================

-- Credit Notes (KRA Document for Returns)
CREATE TABLE credit_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    credit_note_no VARCHAR(100) NOT NULL,
    original_invoice_id UUID NOT NULL REFERENCES sales_invoices(id),
    credit_note_date DATE NOT NULL,
    reason TEXT,
    total_exclusive NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    total_inclusive NUMERIC(20,4) DEFAULT 0,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, credit_note_no)
);

-- Credit Note Line Items
CREATE TABLE credit_note_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    credit_note_id UUID NOT NULL REFERENCES credit_notes(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    original_sale_item_id UUID REFERENCES sales_invoice_items(id),
    batch_id UUID REFERENCES inventory_ledger(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity_returned NUMERIC(20,4) NOT NULL,
    unit_price_exclusive NUMERIC(20,4) NOT NULL,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    line_total_exclusive NUMERIC(20,4) NOT NULL,
    line_total_inclusive NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- EXPENSES (NOT INVENTORY)
-- =====================================================

-- Expense Categories
CREATE TABLE expense_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, name)
);

-- Expenses
CREATE TABLE expenses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES expense_categories(id),
    description TEXT NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    expense_date DATE NOT NULL,
    payment_mode VARCHAR(50),
    reference_number VARCHAR(100),
    attachment_url TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- SETTINGS & CONFIGURATION
-- =====================================================

-- Company Settings
CREATE TABLE company_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    setting_key VARCHAR(100) NOT NULL,
    setting_value TEXT,
    setting_type VARCHAR(50) DEFAULT 'string', -- string, number, boolean, json
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, setting_key)
);

-- Document Numbering Sequences
CREATE TABLE document_sequences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    document_type VARCHAR(50) NOT NULL, -- SALES_INVOICE, GRN, CREDIT_NOTE, PAYMENT
    prefix VARCHAR(20),
    current_number INTEGER DEFAULT 0,
    year INTEGER,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, document_type, year)
);

-- =====================================================
-- SEED DATA
-- =====================================================

-- Insert Default Roles
INSERT INTO user_roles (role_name, description) VALUES
    ('admin', 'Full system access'),
    ('pharmacist', 'Can sell, purchase, view reports'),
    ('cashier', 'Can sell only'),
    ('procurement', 'Can purchase and view inventory'),
    ('viewer', 'Read-only access')
ON CONFLICT (role_name) DO NOTHING;

-- Insert Default Expense Categories
-- (Will be seeded per company during setup)

-- =====================================================
-- HELPER FUNCTIONS
-- =====================================================

-- Function to get next document number
CREATE OR REPLACE FUNCTION get_next_document_number(
    p_company_id UUID,
    p_branch_id UUID,
    p_document_type VARCHAR,
    p_prefix VARCHAR DEFAULT NULL
) RETURNS VARCHAR AS $$
DECLARE
    v_year INTEGER;
    v_current_number INTEGER;
    v_next_number INTEGER;
    v_document_no VARCHAR;
BEGIN
    v_year := EXTRACT(YEAR FROM CURRENT_DATE);
    
    -- Get or create sequence record
    INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
    VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year)
    ON CONFLICT (company_id, branch_id, document_type, year)
    DO UPDATE SET current_number = document_sequences.current_number + 1
    RETURNING current_number INTO v_next_number;
    
    -- Format document number
    IF p_prefix IS NOT NULL THEN
        v_document_no := p_prefix || '-' || LPAD(v_next_number::TEXT, 6, '0');
    ELSE
        v_document_no := LPAD(v_next_number::TEXT, 6, '0');
    END IF;
    
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate current stock (base units)
CREATE OR REPLACE FUNCTION get_current_stock(
    p_item_id UUID,
    p_branch_id UUID
) RETURNS INTEGER AS $$
DECLARE
    v_balance INTEGER;
BEGIN
    SELECT COALESCE(SUM(quantity_delta), 0)::INTEGER
    INTO v_balance
    FROM inventory_ledger
    WHERE item_id = p_item_id
      AND branch_id = p_branch_id;
    
    RETURN v_balance;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- COMMENTS (Documentation)
-- =====================================================

COMMENT ON TABLE inventory_ledger IS 'Single source of truth for all stock movements. Append-only. Never update or delete.';
COMMENT ON COLUMN inventory_ledger.quantity_delta IS 'Positive = stock in, Negative = stock out. Always in BASE UNITS.';
COMMENT ON COLUMN inventory_ledger.unit_cost IS 'Cost per base unit at time of transaction';
COMMENT ON TABLE sales_invoices IS 'KRA-compliant sales documents. Immutable after creation.';
COMMENT ON TABLE credit_notes IS 'KRA-compliant return documents. Must reference original invoice.';
COMMENT ON TABLE purchase_invoices IS 'VAT input claims. Separate from GRN for KRA compliance.';

