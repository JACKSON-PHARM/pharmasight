-- Migration 003: Quotations, purchase orders, stock take, order book, import jobs, invoice payments

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
    total_exclusive NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    discount_amount NUMERIC(20,4) DEFAULT 0,
    total_inclusive NUMERIC(20,4) DEFAULT 0,
    converted_to_invoice_id UUID REFERENCES sales_invoices(id),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    valid_until DATE,
    UNIQUE(quotation_no)
);

CREATE TABLE IF NOT EXISTS quotation_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    quotation_id UUID NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    unit_price_exclusive NUMERIC(20,4) NOT NULL,
    discount_percent NUMERIC(5,2) DEFAULT 0,
    discount_amount NUMERIC(20,4) DEFAULT 0,
    vat_rate NUMERIC(5,2) DEFAULT 16.00,
    vat_amount NUMERIC(20,4) DEFAULT 0,
    line_total_exclusive NUMERIC(20,4) NOT NULL,
    line_total_inclusive NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    order_number VARCHAR(100) NOT NULL,
    order_date DATE NOT NULL,
    reference VARCHAR(255),
    notes TEXT,
    total_amount NUMERIC(20,4) DEFAULT 0,
    status VARCHAR(50) DEFAULT 'PENDING',
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, order_number)
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_order_id UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    unit_price NUMERIC(20,4) NOT NULL,
    total_price NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_hash VARCHAR(64) NOT NULL,
    file_name VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_rows INTEGER NOT NULL DEFAULT 0,
    processed_rows INTEGER NOT NULL DEFAULT 0,
    last_batch INTEGER NOT NULL DEFAULT 0,
    stats JSONB,
    error_message VARCHAR(1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stock_take_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    session_code VARCHAR(10) UNIQUE NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    created_by UUID NOT NULL REFERENCES users(id),
    allowed_counters UUID[] DEFAULT ARRAY[]::UUID[],
    assigned_shelves JSONB DEFAULT '{}'::JSONB,
    is_multi_user BOOLEAN DEFAULT true,
    notes TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_st_status CHECK (status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'COMPLETED', 'CANCELLED'))
);

CREATE TABLE IF NOT EXISTS stock_take_counts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES stock_take_sessions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    counted_by UUID NOT NULL REFERENCES users(id),
    shelf_location VARCHAR(100),
    counted_quantity INTEGER NOT NULL,
    system_quantity INTEGER NOT NULL,
    variance INTEGER NOT NULL,
    notes TEXT,
    counted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, item_id, counted_by)
);

CREATE TABLE IF NOT EXISTS stock_take_counter_locks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES stock_take_sessions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    counter_id UUID NOT NULL REFERENCES users(id),
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '5 minutes',
    UNIQUE(session_id, item_id)
);

CREATE TABLE IF NOT EXISTS stock_take_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES stock_take_sessions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    adjustment_quantity INTEGER NOT NULL,
    reason TEXT,
    approved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, item_id)
);

CREATE TABLE IF NOT EXISTS daily_order_book (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    supplier_id UUID REFERENCES suppliers(id),
    quantity_needed NUMERIC(20,4) NOT NULL,
    unit_name VARCHAR(50) NOT NULL,
    reason VARCHAR(100) NOT NULL,
    source_reference_type VARCHAR(50),
    source_reference_id UUID,
    notes TEXT,
    priority INTEGER DEFAULT 5,
    status VARCHAR(50) DEFAULT 'PENDING',
    purchase_order_id UUID REFERENCES purchase_orders(id),
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(branch_id, item_id, status)
);

CREATE TABLE IF NOT EXISTS order_book_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    supplier_id UUID REFERENCES suppliers(id),
    quantity_needed NUMERIC(20,4) NOT NULL,
    unit_name VARCHAR(50) NOT NULL,
    reason VARCHAR(100) NOT NULL,
    source_reference_type VARCHAR(50),
    source_reference_id UUID,
    notes TEXT,
    priority INTEGER DEFAULT 5,
    status VARCHAR(50) NOT NULL,
    purchase_order_id UUID REFERENCES purchase_orders(id),
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invoice_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    payment_mode VARCHAR(20) NOT NULL,
    amount NUMERIC(15,4) NOT NULL DEFAULT 0,
    payment_reference VARCHAR(100),
    paid_by UUID REFERENCES users(id),
    paid_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(invoice_id, payment_mode, payment_reference)
);

ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'DRAFT';
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS batched BOOLEAN DEFAULT false;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS batched_by UUID REFERENCES users(id);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS batched_at TIMESTAMPTZ;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS cashier_approved BOOLEAN DEFAULT false;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id);
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);
ALTER TABLE sales_invoice_items ADD COLUMN IF NOT EXISTS item_name VARCHAR(255);
ALTER TABLE sales_invoice_items ADD COLUMN IF NOT EXISTS item_code VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_quotations_branch_id ON quotations(branch_id);
CREATE INDEX IF NOT EXISTS idx_quotations_company_id ON quotations(company_id);
CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_company ON purchase_orders(company_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_branch ON purchase_orders(branch_id);
CREATE INDEX IF NOT EXISTS idx_import_jobs_company_id ON import_jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status);
CREATE INDEX IF NOT EXISTS idx_stock_take_sessions_branch ON stock_take_sessions(branch_id);
CREATE INDEX IF NOT EXISTS idx_stock_take_sessions_status ON stock_take_sessions(status);
CREATE INDEX IF NOT EXISTS idx_daily_order_book_branch ON daily_order_book(branch_id);
CREATE INDEX IF NOT EXISTS idx_daily_order_book_item ON daily_order_book(item_id);
CREATE INDEX IF NOT EXISTS idx_daily_order_book_status ON daily_order_book(status);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_invoice_id ON invoice_payments(invoice_id);
