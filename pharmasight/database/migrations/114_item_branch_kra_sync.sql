-- Migration 114: company-level KRA item identity + branch-level item sync tracking

ALTER TABLE items
    ADD COLUMN IF NOT EXISTS kra_item_code VARCHAR(64);

CREATE TABLE IF NOT EXISTS item_branch_kra_sync (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    synced_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_item_branch_kra_sync_item_branch UNIQUE (item_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_item_branch_kra_sync_item
    ON item_branch_kra_sync(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_item_branch_kra_sync_branch_status
    ON item_branch_kra_sync(branch_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_item_branch_kra_sync_company_status
    ON item_branch_kra_sync(company_id, status, updated_at DESC);
