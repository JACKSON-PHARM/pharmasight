-- Refresh item_branch_snapshot for HARTE PHARMACY LTD so item search works.
-- Run this in Supabase SQL Editor (one shot). Replace company_id/branch_id if needed.
-- company_id: 79c297dc-0091-4f9a-b918-e768aaf80b14
-- branch_id:  d21e22be-fb42-40f2-bcdc-0a4c94bc9889

WITH
items_base AS (
  SELECT id, company_id, name, pack_size,
    COALESCE(NULLIF(TRIM(base_unit), ''), 'piece') AS base_unit,
    COALESCE(NULLIF(TRIM(retail_unit), ''), 'piece') AS retail_unit,
    COALESCE(NULLIF(TRIM(wholesale_unit), ''), 'piece') AS wholesale_unit,
    COALESCE(NULLIF(TRIM(supplier_unit), ''), 'piece') AS supplier_unit,
    COALESCE(wholesale_units_per_supplier, 1) AS wholesale_units_per_supplier,
    sku, vat_rate, COALESCE(NULLIF(TRIM(vat_category), ''), 'ZERO_RATED') AS vat_category,
    default_cost_per_base, floor_price_retail, promo_price_retail, promo_start_date, promo_end_date,
    COALESCE(NULLIF(TRIM(pricing_tier), ''), 'STANDARD') AS tier,
    COALESCE(description, '') AS description, COALESCE(barcode, '') AS barcode
  FROM items
  WHERE company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid AND is_active = true
),
stock AS (
  SELECT item_id, COALESCE(current_stock, 0) AS current_stock
  FROM inventory_balances
  WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
),
lpp AS (
  SELECT DISTINCT ON (item_id) item_id, unit_cost AS last_purchase_price
  FROM inventory_ledger
  WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
    AND transaction_type IN ('PURCHASE', 'ADJUSTMENT') AND quantity_delta > 0 AND unit_cost > 0
  ORDER BY item_id, created_at DESC
),
ob AS (
  SELECT DISTINCT ON (item_id) item_id, unit_cost AS ob_cost
  FROM inventory_ledger
  WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
    AND transaction_type = 'OPENING_BALANCE' AND reference_type = 'OPENING_BALANCE'
  ORDER BY item_id, created_at DESC
),
wavg AS (
  SELECT item_id,
    (SUM(quantity_delta * unit_cost) / NULLIF(SUM(quantity_delta), 0))::numeric(20,4) AS avg_cost
  FROM inventory_ledger
  WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid AND quantity_delta > 0
  GROUP BY item_id
),
costs AS (
  SELECT i.id AS item_id,
    COALESCE(lpp.last_purchase_price, ob.ob_cost, wavg.avg_cost, i.default_cost_per_base, 0) AS best_cost,
    lpp.last_purchase_price
  FROM items_base i
  LEFT JOIN lpp ON lpp.item_id = i.id
  LEFT JOIN ob ON ob.item_id = i.id
  LEFT JOIN wavg ON wavg.item_id = i.id
),
batch_rem AS (
  SELECT item_id, MIN(expiry_date) AS next_expiry_date
  FROM (
    SELECT item_id, expiry_date
    FROM inventory_ledger
    WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
    GROUP BY item_id, batch_number, expiry_date
    HAVING SUM(quantity_delta) > 0
  ) t
  WHERE expiry_date IS NOT NULL
  GROUP BY item_id
),
pch AS (
  SELECT item_id, last_purchase_date, last_supplier_id
  FROM item_branch_purchase_snapshot
  WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
),
sch AS (
  SELECT item_id, last_order_date, last_sale_date, last_order_book_date, last_quotation_date
  FROM item_branch_search_snapshot
  WHERE branch_id = 'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid AND company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
),
ip AS (
  SELECT item_id, markup_percent, min_margin_percent
  FROM item_pricing
  WHERE item_id IN (SELECT id FROM items_base)
),
cpd AS (
  SELECT COALESCE(default_markup_percent, 30) AS default_markup_percent, min_margin_percent
  FROM company_pricing_defaults
  WHERE company_id = '79c297dc-0091-4f9a-b918-e768aaf80b14'::uuid
  LIMIT 1
),
cmt AS (
  SELECT i.id AS item_id, cm.default_margin_percent, cm.min_margin_percent
  FROM items_base i
  LEFT JOIN company_margin_tiers cm ON cm.company_id = i.company_id AND cm.tier_name = i.tier
),
computed AS (
  SELECT
    i.id AS item_id,
    i.company_id,
    i.name,
    GREATEST(1, COALESCE(i.pack_size, 1)) AS pack_size,
    i.base_unit,
    i.sku,
    i.vat_rate,
    i.vat_category,
    COALESCE(s.current_stock, 0) AS current_stock,
    c.best_cost AS average_cost,
    COALESCE(c.last_purchase_price, CASE WHEN c.best_cost > 0 THEN c.best_cost END) AS last_purchase_price,
    COALESCE(ip.markup_percent, cmt.default_margin_percent, (SELECT default_markup_percent FROM cpd LIMIT 1), 30) AS margin_percent,
    COALESCE(ip.min_margin_percent, cmt.min_margin_percent, (SELECT min_margin_percent FROM cpd LIMIT 1)) AS minimum_margin,
    i.floor_price_retail AS floor_price,
    i.promo_price_retail AS promotion_price,
    i.promo_start_date AS promotion_start,
    i.promo_end_date AS promotion_end,
    (i.promo_price_retail IS NOT NULL AND i.promo_price_retail > 0
     AND i.promo_start_date IS NOT NULL AND i.promo_end_date IS NOT NULL
     AND CURRENT_DATE >= i.promo_start_date AND CURRENT_DATE <= i.promo_end_date) AS promotion_active,
    ne.next_expiry_date,
    LOWER(TRIM(COALESCE(i.name,'') || ' ' || COALESCE(i.sku,'') || ' ' || COALESCE(i.barcode,'') || ' ' || COALESCE(i.description,''))) AS search_text,
    pch.last_purchase_date,
    pch.last_supplier_id,
    sch.last_order_date,
    sch.last_sale_date,
    sch.last_order_book_date,
    sch.last_quotation_date,
    ip.markup_percent AS default_item_margin,
    (SELECT default_markup_percent FROM cpd LIMIT 1) AS company_margin,
    i.retail_unit,
    i.supplier_unit,
    i.wholesale_unit,
    i.wholesale_units_per_supplier
  FROM items_base i
  LEFT JOIN stock s ON s.item_id = i.id
  LEFT JOIN costs c ON c.item_id = i.id
  LEFT JOIN batch_rem ne ON ne.item_id = i.id
  LEFT JOIN pch ON pch.item_id = i.id
  LEFT JOIN sch ON sch.item_id = i.id
  LEFT JOIN ip ON ip.item_id = i.id
  LEFT JOIN cmt ON cmt.item_id = i.id
),
selling_step AS (
  SELECT
    c.*,
    (CASE WHEN c.floor_price IS NOT NULL
      THEN GREATEST(COALESCE((CASE WHEN c.average_cost IS NOT NULL AND c.margin_percent IS NOT NULL THEN c.average_cost * (1 + c.margin_percent / 100.0) END), c.floor_price), c.floor_price)
      ELSE (CASE WHEN c.average_cost IS NOT NULL AND c.margin_percent IS NOT NULL THEN c.average_cost * (1 + c.margin_percent / 100.0) END) END)::numeric(20,4) AS selling_price
  FROM computed c
),
effective_step AS (
  SELECT
    s.*,
    (CASE WHEN s.promotion_active AND s.promotion_price IS NOT NULL THEN s.promotion_price
          WHEN s.floor_price IS NOT NULL AND s.selling_price IS NOT NULL AND s.selling_price <= s.floor_price THEN s.floor_price
          ELSE s.selling_price END)::numeric(20,4) AS effective_selling_price,
    (CASE WHEN s.promotion_active AND s.promotion_price IS NOT NULL THEN 'promotion'
          WHEN s.floor_price IS NOT NULL AND s.selling_price IS NOT NULL AND s.selling_price = s.floor_price THEN 'floor'
          WHEN s.selling_price IS NOT NULL THEN 'company_margin'
          ELSE NULL END)::varchar(50) AS price_source
  FROM selling_step s
)
INSERT INTO item_branch_snapshot (
  company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
  current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
  next_expiry_date, search_text,
  last_purchase_date, last_supplier_id,
  last_order_date, last_sale_date, last_order_book_date, last_quotation_date,
  default_item_margin, branch_margin, company_margin, floor_price, minimum_margin,
  promotion_price, promotion_start, promotion_end, promotion_active,
  effective_selling_price, price_source,
  retail_unit, supplier_unit, wholesale_unit, wholesale_units_per_supplier,
  updated_at
)
SELECT
  f.company_id,
  'd21e22be-fb42-40f2-bcdc-0a4c94bc9889'::uuid,
  f.item_id,
  f.name,
  f.pack_size,
  f.base_unit,
  f.sku,
  f.vat_rate,
  f.vat_category,
  f.current_stock,
  f.average_cost,
  f.last_purchase_price,
  f.selling_price,
  f.margin_percent,
  f.next_expiry_date,
  COALESCE(NULLIF(TRIM(f.search_text), ''), ' ') AS search_text,
  f.last_purchase_date,
  f.last_supplier_id,
  f.last_order_date,
  f.last_sale_date,
  f.last_order_book_date,
  f.last_quotation_date,
  f.default_item_margin,
  NULL::numeric AS branch_margin,
  f.company_margin,
  f.floor_price,
  f.minimum_margin,
  f.promotion_price,
  f.promotion_start,
  f.promotion_end,
  f.promotion_active,
  f.effective_selling_price,
  f.price_source,
  f.retail_unit,
  f.supplier_unit,
  f.wholesale_unit,
  GREATEST(0.0001, f.wholesale_units_per_supplier),
  NOW()
FROM effective_step f
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
  last_purchase_date = EXCLUDED.last_purchase_date,
  last_supplier_id = EXCLUDED.last_supplier_id,
  last_order_date = EXCLUDED.last_order_date,
  last_sale_date = EXCLUDED.last_sale_date,
  last_order_book_date = EXCLUDED.last_order_book_date,
  last_quotation_date = EXCLUDED.last_quotation_date,
  default_item_margin = EXCLUDED.default_item_margin,
  branch_margin = EXCLUDED.branch_margin,
  company_margin = EXCLUDED.company_margin,
  floor_price = EXCLUDED.floor_price,
  minimum_margin = EXCLUDED.minimum_margin,
  promotion_price = EXCLUDED.promotion_price,
  promotion_start = EXCLUDED.promotion_start,
  promotion_end = EXCLUDED.promotion_end,
  promotion_active = EXCLUDED.promotion_active,
  effective_selling_price = EXCLUDED.effective_selling_price,
  price_source = EXCLUDED.price_source,
  retail_unit = EXCLUDED.retail_unit,
  supplier_unit = EXCLUDED.supplier_unit,
  wholesale_unit = EXCLUDED.wholesale_unit,
  wholesale_units_per_supplier = EXCLUDED.wholesale_units_per_supplier,
  updated_at = NOW();
