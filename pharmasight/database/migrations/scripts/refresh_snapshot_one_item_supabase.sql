-- Refresh item_branch_snapshot for ONE item (all branches where it has a snapshot row).
-- Paste into Supabase SQL Editor and run. No parameters.
-- Use after fixing ledger unit_cost (e.g. migration 067) so snapshot shows per-retail prices.
--
-- Item: PRESARTAN H 50 TABS 28'S (id below). To use for another item, replace the UUID in the script.

SET statement_timeout = '60s';

WITH
branches AS (
  SELECT branch_id, company_id
  FROM item_branch_snapshot
  WHERE item_id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c'
),
item AS (
  SELECT id, company_id, name, pack_size, base_unit, retail_unit, wholesale_unit, supplier_unit,
    COALESCE(wholesale_units_per_supplier, 1) AS wholesale_units_per_supplier,
    default_cost_per_base, floor_price_retail, promo_price_retail, promo_start_date, promo_end_date,
    COALESCE(NULLIF(TRIM(pricing_tier), ''), 'STANDARD') AS tier
  FROM items
  WHERE id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c'
),
lpp AS (
  SELECT DISTINCT ON (branch_id) branch_id, company_id, item_id, unit_cost AS last_purchase_price
  FROM inventory_ledger
  WHERE item_id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c'
    AND transaction_type IN ('PURCHASE', 'ADJUSTMENT') AND quantity_delta > 0 AND unit_cost > 0
  ORDER BY branch_id, created_at DESC
),
ob AS (
  SELECT DISTINCT ON (branch_id) branch_id, company_id, item_id, unit_cost AS ob_cost
  FROM inventory_ledger
  WHERE item_id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c'
    AND transaction_type = 'OPENING_BALANCE' AND reference_type = 'OPENING_BALANCE'
  ORDER BY branch_id, created_at DESC
),
wavg AS (
  SELECT branch_id, company_id, item_id,
    (SUM(quantity_delta * unit_cost) / NULLIF(SUM(quantity_delta), 0))::numeric(20,4) AS avg_cost
  FROM inventory_ledger
  WHERE item_id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c' AND quantity_delta > 0
  GROUP BY branch_id, company_id, item_id
),
costs AS (
  SELECT b.branch_id, b.company_id, i.id AS item_id,
    COALESCE(lpp.last_purchase_price, ob.ob_cost, wavg.avg_cost, i.default_cost_per_base, 0) AS best_cost,
    lpp.last_purchase_price
  FROM branches b
  CROSS JOIN item i
  LEFT JOIN lpp ON lpp.branch_id = b.branch_id
  LEFT JOIN ob ON ob.branch_id = b.branch_id
  LEFT JOIN wavg ON wavg.branch_id = b.branch_id
),
cpd AS (
  SELECT b.company_id, COALESCE(c.default_markup_percent, 30) AS default_markup_percent
  FROM branches b
  LEFT JOIN company_pricing_defaults c ON c.company_id = b.company_id
),
cmt AS (
  SELECT i.company_id, i.id AS item_id, cm.default_margin_percent
  FROM item i
  LEFT JOIN company_margin_tiers cm ON cm.company_id = i.company_id AND cm.tier_name = i.tier
),
ip AS (
  SELECT item_id, markup_percent FROM item_pricing WHERE item_id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c'
),
margin AS (
  SELECT c.branch_id, c.company_id, c.item_id,
    COALESCE(ip.markup_percent, cmt.default_margin_percent, (SELECT default_markup_percent FROM cpd WHERE cpd.company_id = c.company_id LIMIT 1), 30) AS margin_percent
  FROM costs c
  LEFT JOIN ip ON ip.item_id = c.item_id
  LEFT JOIN cmt ON cmt.item_id = c.item_id AND cmt.company_id = c.company_id
),
selling AS (
  SELECT c.branch_id, c.item_id, c.best_cost AS average_cost, c.last_purchase_price,
    m.margin_percent,
    (CASE WHEN i.floor_price_retail IS NOT NULL
      THEN GREATEST(COALESCE(c.best_cost * (1 + m.margin_percent / 100.0), i.floor_price_retail), i.floor_price_retail)
      ELSE c.best_cost * (1 + m.margin_percent / 100.0) END)::numeric(20,4) AS selling_price,
    i.floor_price_retail,
    i.promo_price_retail,
    (i.promo_price_retail IS NOT NULL AND i.promo_price_retail > 0 AND i.promo_start_date IS NOT NULL AND i.promo_end_date IS NOT NULL
     AND CURRENT_DATE >= i.promo_start_date AND CURRENT_DATE <= i.promo_end_date) AS promotion_active
  FROM costs c
  JOIN item i ON i.id = c.item_id
  JOIN margin m ON m.branch_id = c.branch_id AND m.item_id = c.item_id
),
effective AS (
  SELECT branch_id, item_id, average_cost, last_purchase_price, selling_price,
    (CASE WHEN promotion_active AND promo_price_retail IS NOT NULL THEN promo_price_retail
          WHEN floor_price_retail IS NOT NULL AND selling_price IS NOT NULL AND selling_price <= floor_price_retail THEN floor_price_retail
          ELSE selling_price END)::numeric(20,4) AS effective_selling_price
  FROM selling
)
UPDATE item_branch_snapshot s
SET
  average_cost            = e.average_cost,
  last_purchase_price     = e.last_purchase_price,
  selling_price           = e.selling_price,
  effective_selling_price = e.effective_selling_price,
  updated_at              = NOW()
FROM effective e
WHERE s.item_id = e.item_id AND s.branch_id = e.branch_id;

-- Optional: show updated rows
SELECT branch_id, average_cost, last_purchase_price, selling_price, effective_selling_price, updated_at
FROM item_branch_snapshot
WHERE item_id = '9d6e6bc9-dca9-4fac-97c1-deac8570474c';
