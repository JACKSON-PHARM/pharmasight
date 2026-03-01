-- =====================================================
-- Batched backfill for item_branch_snapshot (senior's approach)
-- Processes 5,000 active items per run for one company. Run multiple times
-- with keyset (last_id) to cover all items, or change LIMIT/OFFSET.
-- Replace YOUR_COMPANY_ID with actual UUID. Run in Supabase SQL Editor.
-- =====================================================

WITH cid AS (SELECT 'YOUR_COMPANY_ID'::UUID AS id),

item_batch AS (
  SELECT i.id
  FROM items i, cid
  WHERE i.company_id = cid.id AND i.is_active
  ORDER BY i.id
  LIMIT 5000
  -- Next run (keyset): add  AND i.id > 'LAST_ITEM_UUID_FROM_PREVIOUS_RUN'
),

branches_active AS (
  SELECT b.id
  FROM branches b, cid
  WHERE b.company_id = cid.id AND b.is_active
),

-- Full coverage: every item in batch × every active branch (search shows all items, even zero stock)
pairs AS (
  SELECT i.id AS item_id, b.id AS branch_id
  FROM item_batch i, branches b, cid
  WHERE b.company_id = cid.id AND b.is_active
    AND i.id IN (SELECT id FROM item_batch)
),

lp AS (
  SELECT DISTINCT ON (il.item_id, il.branch_id)
         il.item_id, il.branch_id, il.unit_cost AS cost
  FROM inventory_ledger il, cid
  WHERE il.company_id = cid.id
    AND il.transaction_type = 'PURCHASE'
    AND il.quantity_delta > 0
    AND il.item_id IN (SELECT id FROM item_batch)
    AND (il.item_id, il.branch_id) IN (SELECT item_id, branch_id FROM pairs)
  ORDER BY il.item_id, il.branch_id, il.created_at DESC
),

ob AS (
  SELECT DISTINCT ON (il.item_id, il.branch_id)
         il.item_id, il.branch_id, il.unit_cost AS cost
  FROM inventory_ledger il, cid
  WHERE il.company_id = cid.id
    AND il.transaction_type = 'OPENING_BALANCE'
    AND il.reference_type = 'OPENING_BALANCE'
    AND il.item_id IN (SELECT id FROM item_batch)
    AND (il.item_id, il.branch_id) IN (SELECT item_id, branch_id FROM pairs)
    AND NOT EXISTS (SELECT 1 FROM lp WHERE lp.item_id = il.item_id AND lp.branch_id = il.branch_id)
  ORDER BY il.item_id, il.branch_id, il.created_at DESC
),

wa AS (
  SELECT il.item_id, il.branch_id,
         (SUM(il.quantity_delta * il.unit_cost) / NULLIF(SUM(il.quantity_delta), 0))::numeric(20,4) AS cost
  FROM inventory_ledger il, cid
  WHERE il.company_id = cid.id
    AND il.quantity_delta > 0
    AND il.item_id IN (SELECT id FROM item_batch)
    AND (il.item_id, il.branch_id) IN (SELECT item_id, branch_id FROM pairs)
    AND NOT EXISTS (SELECT 1 FROM lp WHERE lp.item_id = il.item_id AND lp.branch_id = il.branch_id)
    AND NOT EXISTS (SELECT 1 FROM ob WHERE ob.item_id = il.item_id AND ob.branch_id = il.branch_id)
  GROUP BY il.item_id, il.branch_id
),

ne AS (
  SELECT item_id, branch_id, MIN(expiry_date) AS next_exp
  FROM (
    SELECT item_id, branch_id, batch_number, expiry_date,
           SUM(quantity_delta) AS rem
    FROM inventory_ledger, cid
    WHERE company_id = cid.id
      AND expiry_date IS NOT NULL
      AND item_id IN (SELECT id FROM item_batch)
    GROUP BY item_id, branch_id, batch_number, expiry_date
    HAVING SUM(quantity_delta) > 0
  ) x
  GROUP BY item_id, branch_id
),

et AS (
  SELECT id,
         COALESCE(NULLIF(TRIM(UPPER(pricing_tier)), ''),
           CASE UPPER(COALESCE(product_category, ''))
             WHEN 'COSMETICS' THEN 'BEAUTY_COSMETICS'
             WHEN 'EQUIPMENT' THEN 'EQUIPMENT'
             WHEN 'SERVICE'   THEN 'SERVICE'
             ELSE 'STANDARD'
           END) AS tier
  FROM items, cid
  WHERE company_id = cid.id
    AND id IN (SELECT id FROM item_batch)
)

INSERT INTO item_branch_snapshot (
  company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
  current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
  next_expiry_date, search_text, updated_at
)
SELECT
  cid.id,
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
JOIN cid ON true
JOIN items i ON i.id = p.item_id AND i.company_id = cid.id AND i.is_active
JOIN branches b ON b.id = p.branch_id AND b.company_id = cid.id AND b.is_active
LEFT JOIN inventory_balances ib ON ib.company_id = cid.id AND ib.item_id = p.item_id AND ib.branch_id = p.branch_id
LEFT JOIN item_branch_purchase_snapshot ps ON ps.company_id = cid.id AND ps.item_id = p.item_id AND ps.branch_id = p.branch_id
LEFT JOIN lp ON lp.item_id = p.item_id AND lp.branch_id = p.branch_id
LEFT JOIN ob ON ob.item_id = p.item_id AND ob.branch_id = p.branch_id
LEFT JOIN wa ON wa.item_id = p.item_id AND wa.branch_id = p.branch_id
LEFT JOIN ne ON ne.item_id = p.item_id AND ne.branch_id = p.branch_id
LEFT JOIN et ON et.id = p.item_id
LEFT JOIN item_pricing ip ON ip.item_id = p.item_id
LEFT JOIN company_margin_tiers cmt ON cmt.company_id = cid.id AND cmt.tier_name = et.tier
LEFT JOIN company_pricing_defaults cpd ON cpd.company_id = cid.id
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
