-- Migration 035: Branch settings for branch inventory (allow manual transfer/receipt)
-- Does NOT modify purchase, sales, or ledger.

CREATE TABLE IF NOT EXISTS branch_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    allow_manual_transfer BOOLEAN NOT NULL DEFAULT true,
    allow_manual_receipt BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(branch_id)
);

CREATE INDEX idx_branch_settings_branch ON branch_settings(branch_id);
COMMENT ON TABLE branch_settings IS 'Per-branch flags for branch inventory: allow creating transfer/receipt without pending order/transfer.';
