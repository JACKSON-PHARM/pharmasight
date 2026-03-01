-- =====================================================
-- Run this ONCE per company. Replace YOUR_COMPANY_ID with the actual UUID.
-- Get IDs:  SELECT id, name FROM companies;
-- Run each block in Supabase SQL Editor (one company per run, avoids timeout).
-- =====================================================

-- INSTRUCTIONS: Replace YOUR_COMPANY_ID with actual UUID (appears twice below).
-- Get IDs: SELECT id, name FROM companies;
-- Example: '9c71915e-3e59-45d5-9719-56d2322ff673'
-- Run this script once per company (5 companies = 5 runs).

INSERT INTO item_branch_snapshot (
  company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
  current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
  next_expiry_date, search_text, updated_at
)
WITH cid AS (SELECT 'YOUR_COMPANY_ID'::UUID AS id),
lp AS (
  SELECT DISTINCT ON (il.item_id, il.branch_id) il.item_id, il.branch_id, il.unit_cost AS cost
  FROM inventory_ledger il, cid
  WHERE il.company_id = cid.id AND il.transaction_type = 'PURCHASE' AND il.quantity_delta > 0
  ORDER BY il.item_id, il.branch_id, il.created_at DESC
),
ob AS (
  SELECT DISTINCT ON (il.item_id, il.branch_id) il.item_id, il.branch_id, il.unit_cost AS cost
  FROM inventory_ledger il, cid
  WHERE il.company_id = cid.id AND il.transaction_type = 'OPENING_BALANCE' AND il.reference_type = 'OPENING_BALANCE'
    AND NOT EXISTS (SELECT 1 FROM lp WHERE lp.item_id = il.item_id AND lp.branch_id = il.branch_id)
  ORDER BY il.item_id, il.branch_id, il.created_at DESC
),
wa AS (
  SELECT il.item_id, il.branch_id, (SUM(il.quantity_delta * il.unit_cost) / NULLIF(SUM(il.quantity_delta), 0))::NUMERIC(20,4) AS cost
  FROM inventory_ledger il, cid
  WHERE il.company_id = cid.id AND il.quantity_delta > 0
    AND NOT EXISTS (SELECT 1 FROM lp WHERE lp.item_id = il.item_id AND lp.branch_id = il.branch_id)
    AND NOT EXISTS (SELECT 1 FROM ob WHERE ob.item_id = il.item_id AND ob.branch_id = il.branch_id)
  GROUP BY il.item_id, il.branch_id
),
cs AS (
  SELECT i.id AS item_id, b.id AS branch_id, COALESCE(lp.cost, ob.cost, wa.cost, i.default_cost_per_base, 0)::NUMERIC(20,4) AS avg_cost
  FROM items i, branches b, cid
  LEFT JOIN lp ON lp.item_id = i.id AND lp.branch_id = b.id
  LEFT JOIN ob ON ob.item_id = i.id AND ob.branch_id = b.id
  LEFT JOIN wa ON wa.item_id = i.id AND wa.branch_id = b.id
  WHERE i.company_id = cid.id AND b.company_id = cid.id AND i.is_active AND b.is_active
),
ne AS (
  SELECT item_id, branch_id, MIN(expiry_date) AS next_exp FROM (
    SELECT item_id, branch_id, expiry_date FROM inventory_ledger, cid
    WHERE company_id = cid.id AND expiry_date IS NOT NULL
    GROUP BY item_id, branch_id, batch_number, expiry_date HAVING SUM(quantity_delta) > 0
  ) x GROUP BY item_id, branch_id
),
et AS (
  SELECT id, COALESCE(NULLIF(TRIM(UPPER(pricing_tier)),''),
    CASE UPPER(COALESCE(product_category,'')) WHEN 'COSMETICS' THEN 'BEAUTY_COSMETICS'
      WHEN 'EQUIPMENT' THEN 'EQUIPMENT' WHEN 'SERVICE' THEN 'SERVICE' ELSE 'STANDARD' END) AS tier
  FROM items, cid WHERE company_id = cid.id
)
SELECT cid.id, b.id, i.id, COALESCE(TRIM(i.name),''), GREATEST(1,COALESCE(i.pack_size,1)::INT),
  COALESCE(NULLIF(TRIM(i.base_unit),''),'piece'), NULLIF(TRIM(i.sku),''), i.vat_rate,
  COALESCE(NULLIF(TRIM(i.vat_category),''),'ZERO_RATED'), COALESCE(ib.current_stock,0)::NUMERIC(20,4),
  cs.avg_cost, ps.last_purchase_price,
  CASE WHEN cs.avg_cost IS NOT NULL AND cs.avg_cost > 0
    THEN (cs.avg_cost*(1+COALESCE(ip.markup_percent,cmt.default_margin_percent,cpd.default_markup_percent,30)/100))::NUMERIC(20,4)
    ELSE NULL END,
  COALESCE(ip.markup_percent,cmt.default_margin_percent,cpd.default_markup_percent,30)::NUMERIC(10,2),
  ne.next_exp,
  (LOWER(TRIM(COALESCE(i.name,'')))||' '||LOWER(TRIM(COALESCE(i.sku,'')))||' '||LOWER(TRIM(COALESCE(i.barcode,''))))::TEXT,
  NOW()
FROM items i
CROSS JOIN branches b
CROSS JOIN cid
JOIN cs ON cs.item_id = i.id AND cs.branch_id = b.id
LEFT JOIN inventory_balances ib ON ib.item_id = i.id AND ib.branch_id = b.id AND ib.company_id = cid.id
LEFT JOIN item_branch_purchase_snapshot ps ON ps.item_id = i.id AND ps.branch_id = b.id AND ps.company_id = cid.id
LEFT JOIN ne ON ne.item_id = i.id AND ne.branch_id = b.id
LEFT JOIN et ON et.id = i.id
LEFT JOIN item_pricing ip ON ip.item_id = i.id
LEFT JOIN company_margin_tiers cmt ON cmt.company_id = cid.id AND cmt.tier_name = et.tier
LEFT JOIN company_pricing_defaults cpd ON cpd.company_id = cid.id
WHERE i.company_id = cid.id AND b.company_id = cid.id AND i.is_active AND b.is_active
ON CONFLICT (item_id, branch_id) DO UPDATE SET
  name=EXCLUDED.name, pack_size=EXCLUDED.pack_size, base_unit=EXCLUDED.base_unit, sku=EXCLUDED.sku,
  vat_rate=EXCLUDED.vat_rate, vat_category=EXCLUDED.vat_category, current_stock=EXCLUDED.current_stock,
  average_cost=EXCLUDED.average_cost, last_purchase_price=EXCLUDED.last_purchase_price,
  selling_price=EXCLUDED.selling_price, margin_percent=EXCLUDED.margin_percent,
  next_expiry_date=EXCLUDED.next_expiry_date, search_text=EXCLUDED.search_text, updated_at=NOW();
