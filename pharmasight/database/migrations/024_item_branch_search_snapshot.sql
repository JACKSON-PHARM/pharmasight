-- =====================================================
-- 024: item_branch_search_snapshot — last order, sale, order_book
-- Consolidates "last X" data for fast item search regardless of role.
-- Updated in same transaction as PO, Sales, OrderBook writes.
-- Rollback: DROP TABLE item_branch_search_snapshot;
-- =====================================================

-- 1. Create item_branch_search_snapshot
CREATE TABLE IF NOT EXISTS item_branch_search_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    last_order_date DATE,
    last_sale_date DATE,
    last_order_book_date TIMESTAMPTZ,
    last_quotation_date DATE,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_item_branch_search_item_branch ON item_branch_search_snapshot(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_item_branch_search_company ON item_branch_search_snapshot(company_id);
CREATE INDEX IF NOT EXISTS idx_item_branch_search_branch ON item_branch_search_snapshot(branch_id);

COMMENT ON TABLE item_branch_search_snapshot IS 'Precomputed last order/sale/order_book dates per (item_id, branch_id). Enables fast search with full pricing/order context regardless of role.';

-- 2. Backfill last_order_date from PurchaseOrder
WITH last_po AS (
    SELECT DISTINCT ON (poi.item_id, po.branch_id)
        po.company_id, po.branch_id, poi.item_id, po.order_date AS last_order_date
    FROM purchase_order_items poi
    JOIN purchase_orders po ON poi.purchase_order_id = po.id
    ORDER BY poi.item_id, po.branch_id, po.order_date DESC
)
INSERT INTO item_branch_search_snapshot (company_id, branch_id, item_id, last_order_date, updated_at)
SELECT company_id, branch_id, item_id, last_order_date, NOW()
FROM last_po
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    last_order_date = CASE
        WHEN EXCLUDED.last_order_date IS NOT NULL AND (item_branch_search_snapshot.last_order_date IS NULL OR EXCLUDED.last_order_date > item_branch_search_snapshot.last_order_date)
        THEN EXCLUDED.last_order_date
        ELSE item_branch_search_snapshot.last_order_date
    END,
    updated_at = NOW();

-- 3. Backfill last_sale_date from SalesInvoice
WITH last_sale AS (
    SELECT DISTINCT ON (si_item.item_id, si.branch_id)
        si.company_id, si.branch_id, si_item.item_id, si.invoice_date AS last_sale_date
    FROM sales_invoice_items si_item
    JOIN sales_invoices si ON si_item.sales_invoice_id = si.id
    WHERE si.status = 'BATCHED' OR si.batched = true
    ORDER BY si_item.item_id, si.branch_id, si.invoice_date DESC
)
INSERT INTO item_branch_search_snapshot (company_id, branch_id, item_id, last_sale_date, updated_at)
SELECT company_id, branch_id, item_id, last_sale_date, NOW()
FROM last_sale
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    last_sale_date = CASE
        WHEN EXCLUDED.last_sale_date IS NOT NULL AND (item_branch_search_snapshot.last_sale_date IS NULL OR EXCLUDED.last_sale_date > item_branch_search_snapshot.last_sale_date)
        THEN EXCLUDED.last_sale_date
        ELSE item_branch_search_snapshot.last_sale_date
    END,
    updated_at = NOW();

-- 4. Backfill last_order_book_date from daily_order_book
WITH last_ob AS (
    SELECT DISTINCT ON (item_id, branch_id)
        company_id, branch_id, item_id, created_at AS last_order_book_date
    FROM daily_order_book
    ORDER BY item_id, branch_id, created_at DESC
)
INSERT INTO item_branch_search_snapshot (company_id, branch_id, item_id, last_order_book_date, updated_at)
SELECT company_id, branch_id, item_id, last_order_book_date, NOW()
FROM last_ob
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    last_order_book_date = CASE
        WHEN EXCLUDED.last_order_book_date IS NOT NULL AND (item_branch_search_snapshot.last_order_book_date IS NULL OR EXCLUDED.last_order_book_date > item_branch_search_snapshot.last_order_book_date)
        THEN EXCLUDED.last_order_book_date
        ELSE item_branch_search_snapshot.last_order_book_date
    END,
    updated_at = NOW();

-- 5. Backfill item_branch_purchase_snapshot from OPENING_BALANCE (so cost lookup avoids slow ledger fallback)
INSERT INTO item_branch_purchase_snapshot (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
SELECT company_id, branch_id, item_id, unit_cost, created_at::date, NULL, NOW()
FROM inventory_ledger
WHERE transaction_type = 'OPENING_BALANCE' AND reference_type = 'OPENING_BALANCE' AND quantity_delta > 0
ON CONFLICT (item_id, branch_id) DO NOTHING;

-- 6. GIN index on items.name for fast ILIKE search (pg_trgm)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_items_name_trgm ON items USING gin(name gin_trgm_ops) WHERE is_active = true;
