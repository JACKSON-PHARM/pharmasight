-- Migration 041: Inventory Corrections Module — item_movements audit table and permissions
-- Structured correction flows: COST_ADJUSTMENT, BATCH_QUANTITY_CORRECTION, BATCH_METADATA_CORRECTION
-- Does NOT modify sales, FEFO, pricing, or document generation.

-- Item movements: audit log for all correction types (traceable, timestamped)
CREATE TABLE IF NOT EXISTS item_movements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    movement_type VARCHAR(50) NOT NULL,
    ledger_id UUID REFERENCES inventory_ledger(id) ON DELETE SET NULL,
    quantity NUMERIC(20, 4) NOT NULL DEFAULT 0,
    previous_unit_cost NUMERIC(20, 4),
    new_unit_cost NUMERIC(20, 4),
    metadata_before JSONB,
    metadata_after JSONB,
    reason TEXT NOT NULL,
    performed_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_item_movements_item_branch ON item_movements(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_item_movements_created_at ON item_movements(created_at);
CREATE INDEX IF NOT EXISTS idx_item_movements_movement_type ON item_movements(movement_type);
CREATE INDEX IF NOT EXISTS idx_item_movements_ledger_id ON item_movements(ledger_id);

COMMENT ON TABLE item_movements IS 'Audit trail for inventory corrections (cost, quantity, metadata). Do not mutate historical transactions.';

-- Permissions for correction actions
INSERT INTO permissions (name, module, action, description) VALUES
('inventory.adjust_cost', 'inventory', 'adjust_cost', 'Adjust batch cost (valuation only)'),
('inventory.adjust_batch_quantity', 'inventory', 'adjust_batch_quantity', 'Correct batch quantity (stock count correction)'),
('inventory.adjust_batch_metadata', 'inventory', 'adjust_batch_metadata', 'Correct batch expiry or batch number')
ON CONFLICT (name) DO NOTHING;
