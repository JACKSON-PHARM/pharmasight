-- =====================================================
-- PHARMASIGHT DATABASE SCHEMA
-- Pharmacy Management System - KRA Compliant
-- ARCHITECTURE: ONE COMPANY = ONE DATABASE
-- =====================================================
-- This is the AUTHORITATIVE schema file.
-- Use this for all new database setups.
-- =====================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =====================================================
-- COMPANY (SINGLE COMPANY PER DATABASE)
-- =====================================================

-- Companies (ONE record per database)
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

-- =====================================================
-- USERS & AUTHENTICATION
-- =====================================================

-- Users (Application users - linked to Supabase Auth)
CREATE TABLE users (
    id UUID PRIMARY KEY,  -- Same as Supabase Auth user_id
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255),
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE users IS 'Application users. All users belong to the single company in this database. No company_id needed.';
COMMENT ON COLUMN users.id IS 'Must match Supabase Auth user_id';

-- User Roles (System roles)
CREATE TABLE user_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Branches
CREATE TABLE branches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,  -- REQUIRED for invoice numbering
    address TEXT,
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, code)
);

COMMENT ON TABLE branches IS 'Branch locations. Company_id is kept for referential integrity, but there is only one company.';
COMMENT ON COLUMN branches.code IS 'REQUIRED: Used in invoice numbering. Format: {BRANCH_CODE}-INV-YYYY-000001';

-- User Branch Roles (Many-to-many: users have roles per branch)
-- THIS IS THE ONLY WAY USERS ACCESS BRANCHES - NO COMPANY-LEVEL ROLES
CREATE TABLE user_branch_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES user_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, branch_id, role_id)
);

COMMENT ON TABLE user_branch_roles IS 'ONLY way users access branches. No company-level roles. Users can only access branches they are assigned to.';

-- =====================================================
-- ITEM MASTER DATA (COMPANY-LEVEL)
-- =====================================================

-- Items (SKUs) - Shared across all branches
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
    -- VAT Classification (Kenya Pharmacy Context)
    -- Most medicines are zero-rated (0%), some items/services are standard-rated (16%)
    is_vatable BOOLEAN DEFAULT TRUE,
    vat_rate NUMERIC(5,2) DEFAULT 0,  -- 0 for zero-rated, 16 for standard-rated
    vat_code VARCHAR(50),  -- ZERO_RATED | STANDARD | EXEMPT
    price_includes_vat BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE items IS 'Items are created at company level and shared across all branches. Pricing is GLOBAL per company.';

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
-- PRICING CONFIGURATION (GLOBAL PER COMPANY)
-- =====================================================

-- Company Pricing Defaults (GLOBAL - no branch overrides)
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

COMMENT ON TABLE company_pricing_defaults IS 'GLOBAL pricing defaults. No branch-level price overrides allowed.';

-- Item-Specific Pricing (GLOBAL)
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

COMMENT ON TABLE item_pricing IS 'Item-specific pricing is GLOBAL per company. No branch-level pricing.';

-- =====================================================
-- SUPPLIERS (COMPANY-LEVEL)
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
-- INVENTORY LEDGER (BRANCH-SPECIFIC)
-- =====================================================

-- Inventory Ledger (Single Source of Truth - BRANCH-SPECIFIC)
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
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT quantity_delta_not_zero CHECK (quantity_delta != 0)
);

COMMENT ON TABLE inventory_ledger IS 'Single source of truth for all stock movements. BRANCH-SPECIFIC. Append-only. Never update or delete.';
COMMENT ON COLUMN inventory_ledger.quantity_delta IS 'Positive = stock in, Negative = stock out. Always in BASE UNITS.';
COMMENT ON COLUMN inventory_ledger.unit_cost IS 'Cost per base unit at time of transaction';

-- Critical Indexes for Inventory Ledger
CREATE INDEX idx_inventory_ledger_item ON inventory_ledger(item_id);
CREATE INDEX idx_inventory_ledger_branch ON inventory_ledger(branch_id);
CREATE INDEX idx_inventory_ledger_expiry ON inventory_ledger(expiry_date);
CREATE INDEX idx_inventory_ledger_company ON inventory_ledger(company_id);
CREATE INDEX idx_inventory_ledger_reference ON inventory_ledger(reference_type, reference_id);
CREATE INDEX idx_inventory_ledger_batch ON inventory_ledger(item_id, batch_number, expiry_date);

-- =====================================================
-- PURCHASES (BRANCH-SPECIFIC)
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
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, grn_no)
);

COMMENT ON TABLE grns IS 'GRNs are BRANCH-SPECIFIC. GRN numbers should include branch code.';

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

-- Purchase Invoices (VAT Input) - BRANCH-SPECIFIC
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
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, invoice_number)
);

COMMENT ON TABLE purchase_invoices IS 'Purchase invoices are BRANCH-SPECIFIC for tracking purposes.';

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
-- SALES (BRANCH-SPECIFIC, KRA COMPLIANT)
-- =====================================================

-- Sales Invoices (KRA Document) - BRANCH-SPECIFIC
CREATE TABLE sales_invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    invoice_no VARCHAR(100) NOT NULL, -- Format: {BRANCH_CODE}-INV-YYYY-000001 (REQUIRES BRANCH CODE)
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
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, invoice_no)
);

COMMENT ON TABLE sales_invoices IS 'KRA-compliant sales documents. BRANCH-SPECIFIC. Invoice numbers MUST include branch code. Immutable after creation.';
COMMENT ON COLUMN sales_invoices.invoice_no IS 'REQUIRED format: {BRANCH_CODE}-INV-YYYY-000001. Branch code is mandatory.';

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

-- Payments (Settlement of Invoices) - BRANCH-SPECIFIC
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    sales_invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    payment_no VARCHAR(100) NOT NULL, -- Format: {BRANCH_CODE}-PAY-YYYY-000001
    payment_date DATE NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    payment_mode VARCHAR(50) NOT NULL, -- cash, mpesa, bank, cheque
    reference_number VARCHAR(100),
    notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, payment_no)
);

-- =====================================================
-- RETURNS & CREDIT NOTES (BRANCH-SPECIFIC, KRA COMPLIANT)
-- =====================================================

-- Credit Notes (KRA Document for Returns) - BRANCH-SPECIFIC
CREATE TABLE credit_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    credit_note_no VARCHAR(100) NOT NULL, -- Format: {BRANCH_CODE}-CN-YYYY-000001
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

COMMENT ON TABLE credit_notes IS 'KRA-compliant return documents. BRANCH-SPECIFIC. Must reference original invoice. Credit note numbers MUST include branch code.';

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
-- EXPENSES (BRANCH-SPECIFIC)
-- =====================================================

-- Expense Categories (COMPANY-LEVEL)
CREATE TABLE expense_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, name)
);

-- Expenses (BRANCH-SPECIFIC)
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

-- Document Numbering Sequences (BRANCH-SPECIFIC)
CREATE TABLE document_sequences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    document_type VARCHAR(50) NOT NULL, -- SALES_INVOICE, GRN, CREDIT_NOTE, PAYMENT
    prefix VARCHAR(20), -- Will include branch code
    current_number INTEGER DEFAULT 0,
    year INTEGER,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, branch_id, document_type, year)
);

COMMENT ON TABLE document_sequences IS 'Document numbering sequences are BRANCH-SPECIFIC. Invoice numbers MUST include branch code.';

-- =====================================================
-- SEED DATA
-- =====================================================

-- Insert Default Roles
INSERT INTO user_roles (role_name, description) VALUES
    ('Super Admin', 'Full system access with all permissions - can manage users and roles'),
    ('admin', 'Full system access'),
    ('pharmacist', 'Can sell, purchase, view reports'),
    ('cashier', 'Can sell only'),
    ('procurement', 'Can purchase and view inventory'),
    ('viewer', 'Read-only access')
ON CONFLICT (role_name) DO NOTHING;

-- =====================================================
-- HELPER FUNCTIONS
-- =====================================================

-- Function to ensure first user gets Super Admin role
-- This should be called after a user is created or when setting up the first admin
CREATE OR REPLACE FUNCTION ensure_first_user_is_super_admin()
RETURNS TRIGGER AS $$
DECLARE
    v_user_count INTEGER;
    v_super_admin_role_id UUID;
    v_first_branch_id UUID;
BEGIN
    -- Count existing users (excluding soft-deleted)
    SELECT COUNT(*) INTO v_user_count
    FROM users
    WHERE deleted_at IS NULL AND id != NEW.id;
    
    -- If this is the first user, assign Super Admin role
    IF v_user_count = 0 THEN
        -- Get Super Admin role ID
        SELECT id INTO v_super_admin_role_id
        FROM user_roles
        WHERE role_name = 'Super Admin'
        LIMIT 1;
        
        -- If Super Admin role exists and we have at least one branch
        IF v_super_admin_role_id IS NOT NULL THEN
            -- Get the first branch (if exists)
            SELECT id INTO v_first_branch_id
            FROM branches
            ORDER BY created_at ASC
            LIMIT 1;
            
            -- If branch exists, assign Super Admin role to first branch
            IF v_first_branch_id IS NOT NULL THEN
                -- Check if assignment already exists
                IF NOT EXISTS (
                    SELECT 1 FROM user_branch_roles
                    WHERE user_id = NEW.id
                    AND branch_id = v_first_branch_id
                    AND role_id = v_super_admin_role_id
                ) THEN
                    INSERT INTO user_branch_roles (user_id, branch_id, role_id)
                    VALUES (NEW.id, v_first_branch_id, v_super_admin_role_id);
                END IF;
            END IF;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to automatically assign Super Admin to first user
DROP TRIGGER IF EXISTS trigger_ensure_first_user_super_admin ON users;
CREATE TRIGGER trigger_ensure_first_user_super_admin
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION ensure_first_user_is_super_admin();

-- Manual function to promote existing first user to Super Admin (run this if needed)
CREATE OR REPLACE FUNCTION promote_first_user_to_super_admin()
RETURNS VOID AS $$
DECLARE
    v_first_user_id UUID;
    v_super_admin_role_id UUID;
    v_first_branch_id UUID;
BEGIN
    -- Get the first user (by creation date, excluding soft-deleted)
    SELECT id INTO v_first_user_id
    FROM users
    WHERE deleted_at IS NULL
    ORDER BY created_at ASC
    LIMIT 1;
    
    IF v_first_user_id IS NULL THEN
        RAISE NOTICE 'No users found';
        RETURN;
    END IF;
    
    -- Get Super Admin role
    SELECT id INTO v_super_admin_role_id
    FROM user_roles
    WHERE role_name = 'Super Admin'
    LIMIT 1;
    
    IF v_super_admin_role_id IS NULL THEN
        RAISE NOTICE 'Super Admin role not found';
        RETURN;
    END IF;
    
    -- Get first branch
    SELECT id INTO v_first_branch_id
    FROM branches
    ORDER BY created_at ASC
    LIMIT 1;
    
    IF v_first_branch_id IS NULL THEN
        RAISE NOTICE 'No branches found - cannot assign role. Please create a branch first.';
        RETURN;
    END IF;
    
    -- Assign Super Admin role if not already assigned
    IF NOT EXISTS (
        SELECT 1 FROM user_branch_roles
        WHERE user_id = v_first_user_id
        AND branch_id = v_first_branch_id
        AND role_id = v_super_admin_role_id
    ) THEN
        INSERT INTO user_branch_roles (user_id, branch_id, role_id)
        VALUES (v_first_user_id, v_first_branch_id, v_super_admin_role_id);
        RAISE NOTICE 'Promoted first user to Super Admin';
    ELSE
        RAISE NOTICE 'First user already has Super Admin role';
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to get next document number (SIMPLIFIED FORMAT)
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
    v_branch_code VARCHAR;
BEGIN
    v_year := EXTRACT(YEAR FROM CURRENT_DATE);
    
    -- Get branch code (for validation only)
    SELECT code INTO v_branch_code
    FROM branches
    WHERE id = p_branch_id;
    
    IF v_branch_code IS NULL OR v_branch_code = '' THEN
        RAISE EXCEPTION 'Branch code is required. Branch ID: %', p_branch_id;
    END IF;
    
    -- Determine prefix if not provided (simplified format)
    IF p_prefix IS NULL THEN
        CASE p_document_type
            WHEN 'SALES_INVOICE' THEN p_prefix := 'CS';  -- Cash Sale
            WHEN 'GRN' THEN p_prefix := 'GRN';
            WHEN 'CREDIT_NOTE' THEN p_prefix := 'CN';    -- Credit Note
            WHEN 'PAYMENT' THEN p_prefix := 'PAY';
            ELSE p_prefix := p_document_type;
        END CASE;
    END IF;
    
    -- Get or create sequence record (branch-specific but simple format)
    INSERT INTO document_sequences (company_id, branch_id, document_type, prefix, current_number, year)
    VALUES (p_company_id, p_branch_id, p_document_type, p_prefix, 0, v_year)
    ON CONFLICT (company_id, branch_id, document_type, year)
    DO UPDATE SET current_number = document_sequences.current_number + 1
    RETURNING current_number INTO v_next_number;
    
    -- Format document number: {PREFIX}{NUMBER} (e.g., CS001, CN001, CS002, etc.)
    v_document_no := p_prefix || LPAD(v_next_number::TEXT, 3, '0');
    
    RETURN v_document_no;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_document_number IS 'Generates simplified document numbers. Format: CS001 (Cash Sale), CN001 (Credit Note), etc. Branch-specific sequences.';

-- Function to calculate current stock (base units) - BRANCH-SPECIFIC
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

-- Function to get company ID (helper for ONE COMPANY architecture)
CREATE OR REPLACE FUNCTION get_company_id() RETURNS UUID AS $$
DECLARE
    v_company_id UUID;
BEGIN
    SELECT id INTO v_company_id FROM companies LIMIT 1;
    RETURN v_company_id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_company_id IS 'Returns the single company ID. This database represents ONE COMPANY.';

-- =====================================================
-- CONSTRAINTS & TRIGGERS (ONE COMPANY ENFORCEMENT)
-- =====================================================

-- Trigger to enforce ONE COMPANY rule
CREATE OR REPLACE FUNCTION enforce_single_company() RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM companies) > 1 THEN
        RAISE EXCEPTION 'Only one company is allowed per database. This database already has a company.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER check_single_company
    BEFORE INSERT ON companies
    FOR EACH ROW
    EXECUTE FUNCTION enforce_single_company();

COMMENT ON FUNCTION enforce_single_company IS 'Enforces ONE COMPANY = ONE DATABASE rule. Prevents inserting multiple companies.';

-- =====================================================
-- COMMENTS (Documentation)
-- =====================================================

COMMENT ON TABLE companies IS 'ONE COMPANY PER DATABASE. This table should have exactly one record.';
COMMENT ON TABLE inventory_ledger IS 'Single source of truth for all stock movements. BRANCH-SPECIFIC. Append-only. Never update or delete.';
COMMENT ON COLUMN inventory_ledger.quantity_delta IS 'Positive = stock in, Negative = stock out. Always in BASE UNITS.';
COMMENT ON COLUMN inventory_ledger.unit_cost IS 'Cost per base unit at time of transaction';
COMMENT ON TABLE sales_invoices IS 'KRA-compliant sales documents. BRANCH-SPECIFIC. Invoice numbers MUST include branch code. Immutable after creation.';
COMMENT ON TABLE credit_notes IS 'KRA-compliant return documents. BRANCH-SPECIFIC. Must reference original invoice. Credit note numbers MUST include branch code.';
COMMENT ON TABLE purchase_invoices IS 'VAT input claims. BRANCH-SPECIFIC. Separate from GRN for KRA compliance.';
