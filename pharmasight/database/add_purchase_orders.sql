-- Add Purchase Orders table
-- Purchase Orders are created before receiving goods (pre-order documents)

CREATE TABLE IF NOT EXISTS purchase_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplier_id UUID NOT NULL REFERENCES suppliers(id),
    order_number VARCHAR(100) NOT NULL, -- PO{BRANCH_CODE}-000001
    order_date DATE NOT NULL,
    reference VARCHAR(255), -- User reference/notes
    notes TEXT,
    total_amount NUMERIC(20,4) DEFAULT 0,
    status VARCHAR(50) DEFAULT 'PENDING', -- PENDING, APPROVED, RECEIVED, CANCELLED
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, order_number)
);

COMMENT ON TABLE purchase_orders IS 'Purchase Orders are created before receiving goods. Can be converted to GRN when goods are received.';

-- Purchase Order Line Items
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_order_id UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id),
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20,4) NOT NULL,
    unit_price NUMERIC(20,4) NOT NULL, -- Expected price
    total_price NUMERIC(20,4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_purchase_orders_company ON purchase_orders(company_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_branch ON purchase_orders(branch_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON purchase_orders(supplier_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_date ON purchase_orders(order_date);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_purchase_order_items_order ON purchase_order_items(purchase_order_id);
