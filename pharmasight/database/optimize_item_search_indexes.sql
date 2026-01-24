-- Optimize Item Search Performance
-- This script adds indexes to improve item search speed for 20,000+ items

-- 1. Index on company_id and is_active (most common filter)
CREATE INDEX IF NOT EXISTS idx_items_company_active 
ON items(company_id, is_active) 
WHERE is_active = true;

-- 2. Index on name (for name searches) - using lower() for case-insensitive
-- PostgreSQL can use this with functional indexes
CREATE INDEX IF NOT EXISTS idx_items_name_lower 
ON items(lower(name)) 
WHERE is_active = true;

-- 3. Index on SKU (for SKU searches)
CREATE INDEX IF NOT EXISTS idx_items_sku_lower 
ON items(lower(sku)) 
WHERE is_active = true AND sku IS NOT NULL;

-- 4. Index on barcode (for barcode searches)
CREATE INDEX IF NOT EXISTS idx_items_barcode_lower 
ON items(lower(barcode)) 
WHERE is_active = true AND barcode IS NOT NULL;

-- 5. Composite index for company + name (most common search pattern)
CREATE INDEX IF NOT EXISTS idx_items_company_name_lower 
ON items(company_id, lower(name)) 
WHERE is_active = true;

-- 6. Index on PurchaseInvoiceItem (SupplierInvoiceItem) for faster last purchase lookups
-- Note: Table name is purchase_invoice_items (backward compatibility)
CREATE INDEX IF NOT EXISTS idx_purchase_invoice_item_item_created 
ON purchase_invoice_items(item_id, created_at DESC);

-- 7. Index on PurchaseOrderItem for faster last order lookups
CREATE INDEX IF NOT EXISTS idx_purchase_order_item_item_created 
ON purchase_order_items(item_id, created_at DESC);

-- 8. Enable pg_trgm extension for fuzzy search (if not already enabled)
-- This allows trigram-based similarity searches
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 9. Create GIN index for trigram search on name (for fuzzy matching)
-- This is very fast for LIKE queries with wildcards
CREATE INDEX IF NOT EXISTS idx_items_name_trgm 
ON items USING gin(name gin_trgm_ops) 
WHERE is_active = true;

-- 10. Create GIN index for trigram search on SKU
CREATE INDEX IF NOT EXISTS idx_items_sku_trgm 
ON items USING gin(sku gin_trgm_ops) 
WHERE is_active = true AND sku IS NOT NULL;

-- Verify indexes were created
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('items', 'purchase_invoice_items', 'purchase_order_items')
AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;
