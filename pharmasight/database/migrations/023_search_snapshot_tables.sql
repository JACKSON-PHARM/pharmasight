-- =====================================================
-- 023: Search snapshot tables for <300ms search latency
-- =====================================================
-- inventory_balances: precomputed current_stock per (item_id, branch_id)
-- item_branch_purchase_snapshot: precomputed last purchase per (item_id, branch_id)
-- Updated in same transaction as every ledger write.
-- Rollback: DROP TABLE item_branch_purchase_snapshot; DROP TABLE inventory_balances;
-- =====================================================

-- 1. inventory_balances
CREATE TABLE IF NOT EXISTS inventory_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    current_stock NUMERIC(20, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_balances_branch ON inventory_balances(branch_id);
CREATE INDEX IF NOT EXISTS idx_inventory_balances_item_branch ON inventory_balances(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_inventory_balances_company ON inventory_balances(company_id);

COMMENT ON TABLE inventory_balances IS 'Precomputed current stock per (item_id, branch_id). Updated in same transaction as ledger writes.';

-- 2. item_branch_purchase_snapshot
CREATE TABLE IF NOT EXISTS item_branch_purchase_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    last_purchase_price NUMERIC(20, 4),
    last_purchase_date TIMESTAMPTZ,
    last_supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_item_branch_purchase_item_branch ON item_branch_purchase_snapshot(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_item_branch_purchase_company ON item_branch_purchase_snapshot(company_id);

COMMENT ON TABLE item_branch_purchase_snapshot IS 'Precomputed last purchase per (item_id, branch_id). Updated when PURCHASE ledger entries are written.';

-- 2b. Ensure purchase_invoices has status column (some tenants may have older schema)
ALTER TABLE purchase_invoices ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'DRAFT';
UPDATE purchase_invoices SET status = 'BATCHED' WHERE status IS NULL;
UPDATE purchase_invoices SET status = 'BATCHED' WHERE id IN (
    SELECT DISTINCT reference_id FROM inventory_ledger 
    WHERE reference_type IN ('purchase_invoice', 'supplier_invoice') AND reference_id IS NOT NULL
);

-- 3. Backfill inventory_balances from ledger
INSERT INTO inventory_balances (company_id, branch_id, item_id, current_stock, updated_at)
SELECT 
    company_id,
    branch_id,
    item_id,
    COALESCE(SUM(quantity_delta), 0),
    NOW()
FROM inventory_ledger
GROUP BY company_id, branch_id, item_id
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    current_stock = EXCLUDED.current_stock,
    updated_at = NOW();

-- 4. Backfill item_branch_purchase_snapshot from purchase_invoice_items (batched invoices only)
-- Uses unit_cost_exclusive as last_purchase_price (matches current search behavior)
-- Note: GRN backfill omitted; GRN-only tenants may need a separate Python backfill for correct unit conversion
WITH last_purchases AS (
    SELECT DISTINCT ON (pi_item.item_id, pi.branch_id)
        pi.company_id,
        pi.branch_id,
        pi_item.item_id,
        pi_item.unit_cost_exclusive AS last_purchase_price,
        pi.created_at AS last_purchase_date,
        pi.supplier_id AS last_supplier_id
    FROM purchase_invoice_items pi_item
    JOIN purchase_invoices pi ON pi_item.purchase_invoice_id = pi.id
    WHERE pi.status = 'BATCHED'
    ORDER BY pi_item.item_id, pi.branch_id, pi.created_at DESC
)
INSERT INTO item_branch_purchase_snapshot (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
SELECT company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, NOW()
FROM last_purchases
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    last_purchase_price = EXCLUDED.last_purchase_price,
    last_purchase_date = EXCLUDED.last_purchase_date,
    last_supplier_id = EXCLUDED.last_supplier_id,
    updated_at = NOW();
