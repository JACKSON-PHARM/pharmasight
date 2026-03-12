-- =============================================================================
-- Order Book Trigger Validation
-- Run this to see why items do or do not appear in the order book.
-- Matches the logic in OrderBookService.check_and_add_to_order_book (Python).
--
-- 1. Replace the two UUIDs in "params" with your company_id and branch_id.
-- 2. To run for all branches, set branch_id = company_id in params (or change
--    the filter to "AND (il.branch_id = p.branch_id OR p.branch_id IS NULL)").
-- =============================================================================

WITH params AS (
  SELECT
    '00000000-0000-0000-0000-000000000000'::uuid AS company_id,
    '00000000-0000-0000-0000-000000000000'::uuid AS branch_id  -- use your branch UUID
),

-- Current stock from inventory_balances (cached; per branch then summed per item)
current_stock_from_balance AS (
  SELECT
    ib.item_id,
    SUM(ib.current_stock)::numeric AS current_stock_retail_units
  FROM public.inventory_balances ib
  CROSS JOIN params p
  WHERE ib.company_id = p.company_id
    AND ib.branch_id = p.branch_id
  GROUP BY ib.item_id
),

-- Real 30-day sales from inventory_ledger (base units)
monthly_sales AS (
  SELECT
    il.item_id,
    SUM(ABS(il.quantity_delta))::numeric AS monthly_sales_retail_units
  FROM public.inventory_ledger il
  CROSS JOIN params p
  WHERE il.company_id = p.company_id
    AND il.branch_id = p.branch_id
    AND il.transaction_type = 'SALE'
    AND il.created_at >= (CURRENT_DATE - INTERVAL '30 days')
  GROUP BY il.item_id
),

metrics AS (
  SELECT
    i.id AS item_id,
    i.sku,
    i.name,
    GREATEST(COALESCE(NULLIF(i.pack_size, 0), 1), 1)::numeric AS pack_size,
    COALESCE(cs.current_stock_retail_units, 0)   AS current_stock_retail_units,
    COALESCE(ms.monthly_sales_retail_units, 0)   AS monthly_sales_retail_units
  FROM public.items i
  CROSS JOIN params p
  LEFT JOIN current_stock_from_balance cs ON cs.item_id = i.id
  LEFT JOIN monthly_sales ms ON ms.item_id = i.id
  WHERE i.company_id = p.company_id
)
SELECT
  item_id,
  sku,
  name,
  pack_size,
  current_stock_retail_units,
  monthly_sales_retail_units,
  (current_stock_retail_units < pack_size) AS below_one_wholesale,
  (monthly_sales_retail_units > 0
   AND current_stock_retail_units < (monthly_sales_retail_units / 2.0)
  ) AS below_half_monthly,
  (current_stock_retail_units <= 0) AS stock_fell_to_zero,
  (
    (current_stock_retail_units < pack_size)
    OR (monthly_sales_retail_units > 0
        AND current_stock_retail_units < (monthly_sales_retail_units / 2.0))
    OR (current_stock_retail_units <= 0)
  ) AS would_trigger_order_book
FROM metrics
ORDER BY would_trigger_order_book DESC, current_stock_retail_units ASC NULLS LAST;
