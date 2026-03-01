-- =====================================================
-- Backfill item_branch_snapshot for ALL companies, ALL active items.
-- Runs in sequence: each company, then 5,000-item batches until done.
-- No company ID to copy — run once in Supabase SQL Editor.
-- May still hit upstream timeout if total runtime is long; then run
-- backfill_item_branch_snapshot_batched_supabase.sql per company manually.
-- =====================================================

DO $$
DECLARE
  cid UUID;
  last_item_id UUID;
  batch_size INT := 5000;
  rows_affected INT;
  company_name TEXT;
BEGIN
  FOR cid IN SELECT id FROM companies LOOP
    SELECT name INTO company_name FROM companies WHERE id = cid;
    last_item_id := NULL;
    rows_affected := 1;

    WHILE rows_affected > 0 LOOP
      INSERT INTO item_branch_snapshot (
        company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category,
        current_stock, average_cost, last_purchase_price, selling_price, margin_percent,
        next_expiry_date, search_text, updated_at
      )
      WITH item_batch AS (
        SELECT i.id
        FROM items i
        WHERE i.company_id = cid AND i.is_active
          AND (last_item_id IS NULL OR i.id > last_item_id)
        ORDER BY i.id
        LIMIT batch_size
      ),
      -- Full coverage: every item in batch × every active branch (so search shows all items, even zero stock)
      pairs AS (
        SELECT i.id AS item_id, b.id AS branch_id
        FROM item_batch i
        CROSS JOIN branches b
        WHERE b.company_id = cid AND b.is_active
      ),
      lp AS (
        SELECT DISTINCT ON (il.item_id, il.branch_id)
               il.item_id, il.branch_id, il.unit_cost AS cost
        FROM inventory_ledger il
        WHERE il.company_id = cid
          AND il.transaction_type = 'PURCHASE'
          AND il.quantity_delta > 0
          AND il.item_id IN (SELECT id FROM item_batch)
          AND (il.item_id, il.branch_id) IN (SELECT item_id, branch_id FROM pairs)
        ORDER BY il.item_id, il.branch_id, il.created_at DESC
      ),
      ob AS (
        SELECT DISTINCT ON (il.item_id, il.branch_id)
               il.item_id, il.branch_id, il.unit_cost AS cost
        FROM inventory_ledger il
        WHERE il.company_id = cid
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
        FROM inventory_ledger il
        WHERE il.company_id = cid
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
          FROM inventory_ledger
          WHERE company_id = cid
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
        FROM items
        WHERE company_id = cid
          AND id IN (SELECT id FROM item_batch)
      )
      SELECT
        cid,
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
      JOIN items i ON i.id = p.item_id AND i.company_id = cid AND i.is_active
      JOIN branches b ON b.id = p.branch_id AND b.company_id = cid AND b.is_active
      LEFT JOIN inventory_balances ib ON ib.company_id = cid AND ib.item_id = p.item_id AND ib.branch_id = p.branch_id
      LEFT JOIN item_branch_purchase_snapshot ps ON ps.company_id = cid AND ps.item_id = p.item_id AND ps.branch_id = p.branch_id
      LEFT JOIN lp ON lp.item_id = p.item_id AND lp.branch_id = p.branch_id
      LEFT JOIN ob ON ob.item_id = p.item_id AND ob.branch_id = p.branch_id
      LEFT JOIN wa ON wa.item_id = p.item_id AND wa.branch_id = p.branch_id
      LEFT JOIN ne ON ne.item_id = p.item_id AND ne.branch_id = p.branch_id
      LEFT JOIN et ON et.id = p.item_id
      LEFT JOIN item_pricing ip ON ip.item_id = p.item_id
      LEFT JOIN company_margin_tiers cmt ON cmt.company_id = cid AND cmt.tier_name = et.tier
      LEFT JOIN company_pricing_defaults cpd ON cpd.company_id = cid
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

      GET DIAGNOSTICS rows_affected = ROW_COUNT;
      IF rows_affected > 0 THEN
        SELECT id INTO last_item_id
        FROM (
          SELECT i.id
          FROM items i
          WHERE i.company_id = cid
            AND i.is_active
            AND (last_item_id IS NULL OR i.id > last_item_id)
          ORDER BY i.id DESC
          LIMIT 1
        ) sub;
      END IF;
      EXIT WHEN rows_affected = 0;
    END LOOP;

    RAISE NOTICE 'Company % (%): batches complete', company_name, cid;
  END LOOP;
  RAISE NOTICE 'Backfill complete for all companies.';
END $$;
