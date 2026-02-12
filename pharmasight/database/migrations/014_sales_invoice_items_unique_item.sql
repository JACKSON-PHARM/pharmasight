-- Migration 014: Enforce unique (sales_invoice_id, item_id) on sales_invoice_items
-- Prevents duplicate line items for the same product in one invoice.
-- Applied automatically to tenant DBs on backend startup.

-- Drop constraint if it already exists (idempotent)
ALTER TABLE sales_invoice_items
DROP CONSTRAINT IF EXISTS uq_sales_invoice_items_invoice_item;

-- Merge existing duplicates: keep one row per (sales_invoice_id, item_id) with summed quantity/totals.
-- Pick the row to keep by earliest created_at, then id (PostgreSQL has no MIN(uuid)).
WITH dup_groups AS (
    SELECT sales_invoice_id, item_id
    FROM sales_invoice_items
    GROUP BY sales_invoice_id, item_id
    HAVING COUNT(*) > 1
),
keep_row AS (
    SELECT DISTINCT ON (i.sales_invoice_id, i.item_id) i.sales_invoice_id, i.item_id, i.id AS keep_id
    FROM sales_invoice_items i
    INNER JOIN dup_groups d ON i.sales_invoice_id = d.sales_invoice_id AND i.item_id = d.item_id
    ORDER BY i.sales_invoice_id, i.item_id, i.created_at ASC NULLS LAST, i.id ASC
),
sums AS (
    SELECT s.sales_invoice_id, s.item_id,
           SUM(s.quantity) AS qty,
           SUM(s.line_total_exclusive) AS line_excl,
           SUM(s.line_total_inclusive) AS line_incl,
           SUM(s.vat_amount) AS vat,
           SUM(COALESCE(s.discount_amount, 0)) AS disc
    FROM sales_invoice_items s
    INNER JOIN keep_row k ON s.sales_invoice_id = k.sales_invoice_id AND s.item_id = k.item_id
    GROUP BY s.sales_invoice_id, s.item_id
)
UPDATE sales_invoice_items i
SET quantity = s.qty,
    line_total_exclusive = s.line_excl,
    line_total_inclusive = s.line_incl,
    vat_amount = s.vat,
    discount_amount = s.disc
FROM sums s, keep_row k
WHERE i.sales_invoice_id = s.sales_invoice_id AND i.item_id = s.item_id
  AND i.id = k.keep_id;

-- Delete duplicate rows (keep only the one we updated)
DELETE FROM sales_invoice_items i
USING (
    SELECT sales_invoice_id, item_id, keep_id
    FROM (
        SELECT i.sales_invoice_id, i.item_id, i.id AS keep_id,
               ROW_NUMBER() OVER (PARTITION BY i.sales_invoice_id, i.item_id ORDER BY i.created_at ASC NULLS LAST, i.id ASC) AS rn
        FROM sales_invoice_items i
        INNER JOIN (
            SELECT sales_invoice_id, item_id
            FROM sales_invoice_items
            GROUP BY sales_invoice_id, item_id
            HAVING COUNT(*) > 1
        ) d ON i.sales_invoice_id = d.sales_invoice_id AND i.item_id = d.item_id
    ) sub
    WHERE rn = 1
) d
WHERE i.sales_invoice_id = d.sales_invoice_id AND i.item_id = d.item_id AND i.id != d.keep_id;

-- Add unique constraint
ALTER TABLE sales_invoice_items
ADD CONSTRAINT uq_sales_invoice_items_invoice_item UNIQUE (sales_invoice_id, item_id);

COMMENT ON CONSTRAINT uq_sales_invoice_items_invoice_item ON sales_invoice_items IS 'One line per item per invoice; prevents duplicate items.';
