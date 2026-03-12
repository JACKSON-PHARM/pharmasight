-- =============================================================================
-- Order Book: Pack size audit
-- 1) Items with pack_size = 1 or NULL (likely need correction for 3-tier units)
-- 2) Whether they appear in order book trigger (join to validation metrics)
-- Replace company_id and branch_id in params.
-- =============================================================================

WITH params AS (
  SELECT
    '00000000-0000-0000-0000-000000000000'::uuid AS company_id,
    '00000000-0000-0000-0000-000000000000'::uuid AS branch_id
),

current_stock_from_balance AS (
  SELECT
    ib.item_id,
    SUM(ib.current_stock)::numeric AS current_stock_retail_units
  FROM public.inventory_balances ib
  CROSS JOIN params p
  WHERE ib.company_id = p.company_id AND ib.branch_id = p.branch_id
  GROUP BY ib.item_id
),

monthly_sales AS (
  SELECT
    il.item_id,
    SUM(ABS(il.quantity_delta))::numeric AS monthly_sales_retail_units
  FROM public.inventory_ledger il
  CROSS JOIN params p
  WHERE il.company_id = p.company_id AND il.branch_id = p.branch_id
    AND il.transaction_type = 'SALE'
    AND il.created_at >= (CURRENT_DATE - INTERVAL '30 days')
  GROUP BY il.item_id
),

-- Only items with pack_size 1 or NULL
bad_pack_items AS (
  SELECT i.id, i.sku, i.name, i.base_unit, i.retail_unit, i.wholesale_unit, i.pack_size
  FROM public.items i
  CROSS JOIN params p
  WHERE i.company_id = p.company_id
    AND (i.pack_size IS NULL OR i.pack_size = 1)
),

metrics AS (
  SELECT
    b.id AS item_id,
    b.sku,
    b.name,
    b.pack_size,
    GREATEST(COALESCE(NULLIF(b.pack_size, 0), 1), 1)::numeric AS pack_size_used,
    COALESCE(cs.current_stock_retail_units, 0)   AS current_stock_retail_units,
    COALESCE(ms.monthly_sales_retail_units, 0)   AS monthly_sales_retail_units
  FROM bad_pack_items b
  LEFT JOIN current_stock_from_balance cs ON cs.item_id = b.id
  LEFT JOIN monthly_sales ms ON ms.item_id = b.id
)
SELECT
  item_id,
  sku,
  name,
  pack_size AS pack_size_raw,
  pack_size_used,
  current_stock_retail_units,
  monthly_sales_retail_units,
  (current_stock_retail_units < pack_size_used) AS below_one_wholesale,
  (monthly_sales_retail_units > 0
   AND current_stock_retail_units < (monthly_sales_retail_units / 2.0)
  ) AS below_half_monthly,
  (current_stock_retail_units <= 0) AS stock_fell_to_zero,
  (
    (current_stock_retail_units < pack_size_used)
    OR (monthly_sales_retail_units > 0
        AND current_stock_retail_units < (monthly_sales_retail_units / 2.0))
    OR (current_stock_retail_units <= 0)
  ) AS would_trigger_order_book
FROM metrics
ORDER BY name;
