-- =====================================================
-- Targeted backfill: item_branch_snapshot for (item_id, branch_id) 
-- pairs that have inventory_balances (stock activity) but missing or 
-- stale snapshot. Fixes items skipped by write paths (adjustment, 
-- transfer, etc.) that did not update the snapshot.
-- Run in Supabase SQL Editor. Idempotent.
-- =====================================================

SET statement_timeout = 0;

INSERT INTO item_branch_snapshot (
  company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
  current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
  next_expiry_date, search_text, updated_at
)
WITH pairs AS (
  -- All (item_id, branch_id) that have inventory_balances (stock activity)
  SELECT ib.company_id, ib.branch_id, ib.item_id
  FROM inventory_balances ib
  WHERE ib.company_id IS NOT NULL
),
lp AS (
  SELECT DISTINCT ON (il.company_id, il.item_id, il.branch_id)
         il.company_id, il.item_id, il.branch_id, il.unit_cost AS cost
  FROM inventory_ledger il
  WHERE il.transaction_type = 'PURCHASE'
    AND il.quantity_delta > 0
    AND (il.company_id, il.item_id, il.branch_id) IN (SELECT company_id, item_id, branch_id FROM pairs)
  ORDER BY il.company_id, il.item_id, il.branch_id, il.created_at DESC
),
ob AS (
  SELECT DISTINCT ON (il.company_id, il.item_id, il.branch_id)
         il.company_id, il.item_id, il.branch_id, il.unit_cost AS cost
  FROM inventory_ledger il
  WHERE il.transaction_type = 'OPENING_BALANCE'
    AND il.reference_type = 'OPENING_BALANCE'
    AND (il.company_id, il.item_id, il.branch_id) IN (SELECT company_id, item_id, branch_id FROM pairs)
    AND NOT EXISTS (SELECT 1 FROM lp WHERE lp.company_id = il.company_id AND lp.item_id = il.item_id AND lp.branch_id = il.branch_id)
  ORDER BY il.company_id, il.item_id, il.branch_id, il.created_at DESC
),
wa AS (
  SELECT il.company_id, il.item_id, il.branch_id,
         (SUM(il.quantity_delta * il.unit_cost) / NULLIF(SUM(il.quantity_delta), 0))::numeric(20,4) AS cost
  FROM inventory_ledger il
  WHERE il.quantity_delta > 0
    AND (il.company_id, il.item_id, il.branch_id) IN (SELECT company_id, item_id, branch_id FROM pairs)
    AND NOT EXISTS (SELECT 1 FROM lp WHERE lp.company_id = il.company_id AND lp.item_id = il.item_id AND lp.branch_id = il.branch_id)
    AND NOT EXISTS (SELECT 1 FROM ob WHERE ob.company_id = il.company_id AND ob.item_id = il.item_id AND ob.branch_id = il.branch_id)
  GROUP BY il.company_id, il.item_id, il.branch_id
),
ne AS (
  SELECT company_id, item_id, branch_id, MIN(expiry_date) AS next_exp
  FROM (
    SELECT company_id, item_id, branch_id, batch_number, expiry_date,
           SUM(quantity_delta) AS rem
    FROM inventory_ledger
    WHERE expiry_date IS NOT NULL
      AND (company_id, item_id, branch_id) IN (SELECT company_id, item_id, branch_id FROM pairs)
    GROUP BY company_id, item_id, branch_id, batch_number, expiry_date
    HAVING SUM(quantity_delta) > 0
  ) x
  GROUP BY company_id, item_id, branch_id
),
et AS (
  SELECT p.company_id, p.item_id,
         COALESCE(NULLIF(TRIM(UPPER(i.pricing_tier)), ''),
           CASE UPPER(COALESCE(i.product_category, ''))
             WHEN 'COSMETICS' THEN 'BEAUTY_COSMETICS'
             WHEN 'EQUIPMENT' THEN 'EQUIPMENT'
             WHEN 'SERVICE'   THEN 'SERVICE'
             ELSE 'STANDARD'
           END) AS tier
  FROM pairs p
  JOIN items i ON i.id = p.item_id AND i.company_id = p.company_id
)
SELECT
  p.company_id,
  p.branch_id,
  p.item_id,
  COALESCE(TRIM(i.name), ''),
  GREATEST(1, COALESCE(i.pack_size, 1)::int),
  COALESCE(NULLIF(TRIM(i.base_unit), ''), 'piece'),
  NULLIF(TRIM(i.sku), ''),
  i.vat_rate,
  COALESCE(NULLIF(TRIM(i.vat_category), ''), 'ZERO_RATED'),
  COALESCE(ib.current_stock, 0)::numeric(20,4),
  COALESCE(lp.cost, ob.cost, wa.cost, i.default_cost_per_base, 0)::numeric(20,4),
  ps.last_purchase_price,
  CASE
    WHEN COALESCE(lp.cost, ob.cost, wa.cost, i.default_cost_per_base, 0) > 0
    THEN (
      COALESCE(lp.cost, ob.cost, wa.cost, i.default_cost_per_base, 0)
      * (1 + COALESCE(ip.markup_percent, cmt.default_margin_percent, cpd.default_markup_percent, 30) / 100)
    )::numeric(20,4)
    ELSE NULL
  END,
  COALESCE(ip.markup_percent, cmt.default_margin_percent, cpd.default_markup_percent, 30)::numeric(10,2),
  ne.next_exp,
  (LOWER(TRIM(COALESCE(i.name,''))) || ' ' || LOWER(TRIM(COALESCE(i.sku,''))) || ' ' || LOWER(TRIM(COALESCE(i.barcode,''))))::text,
  NOW()
FROM pairs p
JOIN items i ON i.id = p.item_id AND i.company_id = p.company_id AND i.is_active
LEFT JOIN inventory_balances ib ON ib.company_id = p.company_id AND ib.item_id = p.item_id AND ib.branch_id = p.branch_id
LEFT JOIN item_branch_purchase_snapshot ps ON ps.company_id = p.company_id AND ps.item_id = p.item_id AND ps.branch_id = p.branch_id
LEFT JOIN lp ON lp.company_id = p.company_id AND lp.item_id = p.item_id AND lp.branch_id = p.branch_id
LEFT JOIN ob ON ob.company_id = p.company_id AND ob.item_id = p.item_id AND ob.branch_id = p.branch_id
LEFT JOIN wa ON wa.company_id = p.company_id AND wa.item_id = p.item_id AND wa.branch_id = p.branch_id
LEFT JOIN ne ON ne.company_id = p.company_id AND ne.item_id = p.item_id AND ne.branch_id = p.branch_id
LEFT JOIN et ON et.company_id = p.company_id AND et.item_id = p.item_id
LEFT JOIN item_pricing ip ON ip.item_id = p.item_id
LEFT JOIN company_margin_tiers cmt ON cmt.company_id = p.company_id AND cmt.tier_name = et.tier
LEFT JOIN company_pricing_defaults cpd ON cpd.company_id = p.company_id
ON CONFLICT (item_id, branch_id) DO UPDATE SET
  name = EXCLUDED.name,
  pack_size = EXCLUDED.pack_size,
  base_unit = EXCLUDED.base_unit,
  sku = EXCLUDED.sku,
  vat_rate = EXCLUDED.vat_rate,
  vat_category = EXCLUDED.vat_category,
  current_stock = EXCLUDED.current_stock,
  average_cost = EXCLUDED.average_cost,
  last_purchase_price = EXCLUDED.last_purchase_price,
  selling_price = EXCLUDED.selling_price,
  margin_percent = EXCLUDED.margin_percent,
  next_expiry_date = EXCLUDED.next_expiry_date,
  search_text = EXCLUDED.search_text,
  updated_at = NOW();
