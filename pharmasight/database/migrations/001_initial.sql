-- Migration 001: Initial tenant schema
-- Authority: locked architecture. One DB per tenant; branches in tenant DB.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

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

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255),
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE branches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    address TEXT,
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, code)
);

CREATE TABLE user_branch_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES user_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, branch_id, role_id)
);

CREATE TABLE items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    generic_name VARCHAR(255),
    sku VARCHAR(100),
    barcode VARCHAR(100),
    category VARCHAR(100),
    base_unit VARCHAR(50) NOT NULL,
    default_cost NUMERIC(20,4) DEFAULT 0,
    is_vatable BOOLEAN DEFAULT TRUE,
    vat_rate NUMERIC(5,2) DEFAULT 0,
    vat_code VARCHAR(50),
    price_includes_vat BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE item_units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_name VARCHAR(50) NOT NULL,
    multiplier_to_base NUMERIC(20,4) NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, unit_name)
);

CREATE TABLE company_pricing_defaults (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    default_markup_percent NUMERIC(10,2) DEFAULT 30.00,
    rounding_rule VARCHAR(50) DEFAULT 'nearest_1',
    min_margin_percent NUMERIC(10,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id)
);

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

CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    pin VARCHAR(50),
    contact_person VARCHAR(255),
    phone VARCHAR(50),
    email VARCHAR(255),
    address TEXT,
    credit_terms INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inventory_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    transaction_type VARCHAR(50) NOT NULL,
    reference_type VARCHAR(50),
    reference_id UUID,
    quantity_delta INTEGER NOT NULL,
    unit_cost NUMERIC(20,4) NOT NULL,
    total_cost NUMERIC(20,4) NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT quantity_delta_not_zero CHECK (quantity_delta != 0)
);

CREATE INDEX idx_inventory_ledger_item ON inventory_ledger(item_id);
CREATE INDEX idx_inventory_ledger_branch ON inventory_ledger(branch_id);
CREATE INDEX idx_inventory_ledger_expiry ON inventory_ledger(expiry_date);
CREATE INDEX idx_inventory_ledger_company ON inventory_ledger(company_id);
CREATE INDEX idx_inventory_ledger_reference ON inventory_ledger(reference_type, reference_id);
CREATE INDEX idx_inventory_ledger_batch ON inventory_ledger(item_id, batch_number, expiry_date);

CREATE TABLE grns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    grn_no VARCHAR(100) NOT NULL,
    date_received DATE NOT NULL,
    total_cost NUMERIC(20,4) DEFAULT 0,
    notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, grn_no)
);

CREATE TABLE grn_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    grn_id UUID NOT NULL REFERENCES grns(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    unit_cost NUMERIC(20,4) NOT NULL,
    batch_number VARCHAR(200),
    expiry_date DATE,
    total_cost NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE purchase_invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    invoice_number VARCHAR(100) NOT NULL,
    pin_number VARCHAR(100),
    invoice_date DATE NOT NULL,
    linked_grn_id UUID REFERENCES grns(id),
    total_exclusive NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    total_inclusive NUMERIC(20,4) DEFAULT 0,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, invoice_number)
);

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

CREATE TABLE sales_invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    invoice_no VARCHAR(100) NOT NULL,
    invoice_date DATE NOT NULL,
    customer_name VARCHAR(255),
    customer_pin VARCHAR(50),
    payment_mode VARCHAR(50) NOT NULL,
    payment_status VARCHAR(50) DEFAULT 'PAID',
    total_exclusive NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    discount_amount NUMERIC(20,4) DEFAULT 0,
    total_inclusive NUMERIC(20,4) DEFAULT 0,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, invoice_no)
);

CREATE TABLE sales_invoice_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    batch_id UUID REFERENCES inventory_ledger(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    unit_price_exclusive NUMERIC(20,4) NOT NULL,
    discount_percent NUMERIC(5,2) DEFAULT 0,
    discount_amount NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    line_total_exclusive NUMERIC(20,4) NOT NULL,
    line_total_inclusive NUMERIC(20,4) NOT NULL,
    unit_cost_used NUMERIC(20,4),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    payment_no VARCHAR(100) NOT NULL,
    payment_date DATE NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    payment_mode VARCHAR(50) NOT NULL,
    reference_number VARCHAR(100),
    notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, payment_no)
);

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
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, credit_note_no)
);

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

CREATE TABLE expense_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, name)
);

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
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE company_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    setting_key VARCHAR(100) NOT NULL,
    setting_value TEXT,
    setting_type VARCHAR(50) DEFAULT 'string',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, setting_key)
);

CREATE TABLE document_sequences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    document_type VARCHAR(50) NOT NULL,
    prefix VARCHAR(20),
    current_number INTEGER DEFAULT 0,
    year INTEGER,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, document_type, year)
);

INSERT INTO user_roles (role_name, description) VALUES
    ('Super Admin', 'Full system access with all permissions - can manage users and roles'),
    ('admin', 'Full system access'),
    ('pharmacist', 'Can sell, purchase, view reports'),
    ('cashier', 'Can sell only'),
    ('procurement', 'Can purchase and view inventory'),
    ('viewer', 'Read-only access')
ON CONFLICT (role_name) DO NOTHING;

CREATE OR REPLACE FUNCTION get_next_document_number(
    p_company_id UUID,
    p_branch_id UUID,
    p_document_type VARCHAR,
    p_prefix VARCHAR DEFAULT NULL
) RETURNS VARCHAR AS $$
DECLARE
    v_year INTEGER;
    v_next_number INTEGER;
    v_document_no VARCHAR;
    v_branch_code VARCHAR;
BEGIN
    v_year := EXTRACT(YEAR FROM CURRENT_DATE);
    SELECT code INTO v_branch_code FROM branches WHERE id = p_branch_id;
    IF v_branch_code IS NULL OR v_branch_code = '' THEN
        RAISE EXCEPTION 'Branch code is required. Branch ID: %', p_branch_id;
    END IF;
    IF p_prefix IS NULL THEN
        CASE p_document_type
            WHEN 'SALES_INVOICE' THEN p_prefix := 'CS';
            WHEN 'GRN' THEN p_prefix := 'GRN';
            WHEN 'CREDIT_NOTE' THEN p_prefix := 'CN';
            WHEN 'PAYMENT' THEN p_prefix := 'PAY';
            WHEN 'SUPPLIER_INVOICE' THEN p_prefix := 'SUP-INV';
            ELSE p_prefix := p_document_type;
        END CASE;
    END IF;
    INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
    VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year)
    ON CONFLICT (company_id, branch_id, document_type, year)
    DO UPDATE SET current_number = document_sequences.current_number + 1
    RETURNING current_number INTO v_next_number;
    v_document_no := p_prefix || LPAD(v_next_number::TEXT, 3, '0');
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_current_stock(p_item_id UUID, p_branch_id UUID) RETURNS INTEGER AS $$
DECLARE v_balance INTEGER;
BEGIN
    SELECT COALESCE(SUM(quantity_delta), 0)::INTEGER INTO v_balance
    FROM inventory_ledger WHERE item_id = p_item_id AND branch_id = p_branch_id;
    RETURN v_balance;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_company_id() RETURNS UUID AS $$
DECLARE v_company_id UUID;
BEGIN
    SELECT id INTO v_company_id FROM companies LIMIT 1;
    RETURN v_company_id;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION enforce_single_company() RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM companies) > 1 THEN
        RAISE EXCEPTION 'Only one company is allowed per database.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER check_single_company
    BEFORE INSERT ON companies
    FOR EACH ROW
    EXECUTE FUNCTION enforce_single_company();
