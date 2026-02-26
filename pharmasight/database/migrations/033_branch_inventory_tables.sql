-- Migration 033: Branch Inventory Module (FEFO + Batch Controlled)
-- Creates ONLY new tables. Does NOT modify items, inventory_batches, cost tables, or existing transaction tables.
-- Reuses: inventory_ledger (TRANSFER), inventory_balances, existing document/branch patterns.

-- branch_orders: ordering branch requests stock from supplying branch
CREATE TABLE branch_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    ordering_branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    supplying_branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    order_number VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',  -- DRAFT, BATCHED (locked)
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_branch_orders_order_number ON branch_orders(company_id, ordering_branch_id, order_number) WHERE order_number IS NOT NULL;

CREATE INDEX idx_branch_orders_ordering ON branch_orders(ordering_branch_id);
CREATE INDEX idx_branch_orders_supplying ON branch_orders(supplying_branch_id);
CREATE INDEX idx_branch_orders_status ON branch_orders(status);

COMMENT ON TABLE branch_orders IS 'Order from one branch to another; locked after batching.';

-- branch_order_lines: line items (item, qty); fulfilled_qty updated by branch_transfer_lines
CREATE TABLE branch_order_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    branch_order_id UUID NOT NULL REFERENCES branch_orders(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20, 4) NOT NULL,
    fulfilled_qty NUMERIC(20, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_branch_order_lines_order ON branch_order_lines(branch_order_id);
CREATE INDEX idx_branch_order_lines_item ON branch_order_lines(item_id);

-- branch_transfers: supplying branch sends stock to receiving branch (FEFO deduction at batch level)
CREATE TABLE branch_transfers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    supplying_branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    receiving_branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    branch_order_id UUID REFERENCES branch_orders(id) ON DELETE SET NULL,
    transfer_number VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',  -- DRAFT, COMPLETED
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_branch_transfers_supplying ON branch_transfers(supplying_branch_id);
CREATE INDEX idx_branch_transfers_receiving ON branch_transfers(receiving_branch_id);
CREATE INDEX idx_branch_transfers_order ON branch_transfers(branch_order_id);

COMMENT ON TABLE branch_transfers IS 'Transfer of stock between branches; FEFO deduction from supplying branch.';

-- branch_transfer_lines: batch-aware (one row per item+batch); cost from inventory batch
CREATE TABLE branch_transfer_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    branch_transfer_id UUID NOT NULL REFERENCES branch_transfers(id) ON DELETE CASCADE,
    branch_order_line_id UUID REFERENCES branch_order_lines(id) ON DELETE SET NULL,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    unit_name VARCHAR(50) NOT NULL,
    quantity NUMERIC(20, 4) NOT NULL,
    unit_cost NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_branch_transfer_lines_transfer ON branch_transfer_lines(branch_transfer_id);
CREATE INDEX idx_branch_transfer_lines_order_line ON branch_transfer_lines(branch_order_line_id);

COMMENT ON TABLE branch_transfer_lines IS 'Batch-level transfer line; unit_cost from inventory batch at transfer.';

-- branch_receipts: receiving branch confirms receipt
CREATE TABLE branch_receipts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    receiving_branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    branch_transfer_id UUID NOT NULL REFERENCES branch_transfers(id) ON DELETE CASCADE,
    receipt_number VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',  -- PENDING, RECEIVED
    received_at TIMESTAMPTZ,
    received_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_branch_receipts_receiving ON branch_receipts(receiving_branch_id);
CREATE INDEX idx_branch_receipts_transfer ON branch_receipts(branch_transfer_id);
CREATE UNIQUE INDEX idx_branch_receipts_transfer_unique ON branch_receipts(branch_transfer_id);

COMMENT ON TABLE branch_receipts IS 'Receipt confirmation for a branch transfer; one receipt per transfer.';

-- branch_receipt_lines: batch-level received qty and cost (preserved from transfer)
CREATE TABLE branch_receipt_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    branch_receipt_id UUID NOT NULL REFERENCES branch_receipts(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    batch_number VARCHAR(200),
    expiry_date DATE,
    quantity NUMERIC(20, 4) NOT NULL,
    unit_cost NUMERIC(20, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_branch_receipt_lines_receipt ON branch_receipt_lines(branch_receipt_id);

COMMENT ON TABLE branch_receipt_lines IS 'Batch-level receipt line; batch_number, expiry_date, unit_cost preserved from transfer.';
