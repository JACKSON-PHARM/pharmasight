-- Department supply: same-branch pharmacy -> department mini-store workflow
-- Mirrors branch_orders / branch_transfers / branch_receipts without encounter coupling.

CREATE TABLE department_supply_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    department_store_id UUID NOT NULL REFERENCES department_stores(id) ON DELETE CASCADE,
    order_number VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    notes TEXT,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_department_supply_orders_order_number
    ON department_supply_orders (company_id, branch_id, order_number)
    WHERE order_number IS NOT NULL;

CREATE INDEX idx_department_supply_orders_branch ON department_supply_orders (branch_id);
CREATE INDEX idx_department_supply_orders_store ON department_supply_orders (department_store_id);
CREATE INDEX idx_department_supply_orders_status ON department_supply_orders (status);

COMMENT ON TABLE department_supply_orders IS 'Department requests stock from pharmacy at same branch; OPEN = pending fulfillment.';

CREATE TABLE department_supply_order_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    department_supply_order_id UUID NOT NULL REFERENCES department_supply_orders(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20, 4) NOT NULL,
    fulfilled_qty NUMERIC(20, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_department_supply_order_lines_order ON department_supply_order_lines (department_supply_order_id);
CREATE INDEX idx_department_supply_order_lines_item ON department_supply_order_lines (item_id);

CREATE TABLE department_supply_transfers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    department_store_id UUID NOT NULL REFERENCES department_stores(id) ON DELETE CASCADE,
    department_supply_order_id UUID REFERENCES department_supply_orders(id) ON DELETE SET NULL,
    transfer_number VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    request_audit JSONB,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_department_supply_transfers_branch ON department_supply_transfers (branch_id);
CREATE INDEX idx_department_supply_transfers_store ON department_supply_transfers (department_store_id);
CREATE INDEX idx_department_supply_transfers_order ON department_supply_transfers (department_supply_order_id);

CREATE TABLE department_supply_transfer_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    department_supply_transfer_id UUID NOT NULL REFERENCES department_supply_transfers(id) ON DELETE CASCADE,
    department_supply_order_line_id UUID REFERENCES department_supply_order_lines(id) ON DELETE SET NULL,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20, 4) NOT NULL,
    unit_cost NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_department_supply_transfer_lines_transfer ON department_supply_transfer_lines (department_supply_transfer_id);
CREATE INDEX idx_department_supply_transfer_lines_order_line ON department_supply_transfer_lines (department_supply_order_line_id);

CREATE TABLE department_supply_receipts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    department_store_id UUID NOT NULL REFERENCES department_stores(id) ON DELETE CASCADE,
    department_supply_transfer_id UUID NOT NULL REFERENCES department_supply_transfers(id) ON DELETE CASCADE,
    receipt_number VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    received_at TIMESTAMPTZ,
    received_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uq_department_supply_receipt_per_transfer ON department_supply_receipts (department_supply_transfer_id);

CREATE INDEX idx_department_supply_receipts_store ON department_supply_receipts (department_store_id);
CREATE INDEX idx_department_supply_receipts_status ON department_supply_receipts (status);

CREATE TABLE department_supply_receipt_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    department_supply_receipt_id UUID NOT NULL REFERENCES department_supply_receipts(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    quantity NUMERIC(20, 4) NOT NULL,
    unit_cost NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_department_supply_receipt_lines_receipt ON department_supply_receipt_lines (department_supply_receipt_id);
