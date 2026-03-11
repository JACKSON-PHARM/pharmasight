-- Migration 066: Backfill ledger OPENING_BALANCE and GRN unit_cost to per-retail;
--                 normalize items.default_cost_per_base to per-retail; enqueue snapshot refresh.
--
-- Background:
-- - OPENING_BALANCE (Excel import / opening balance) was stored with unit_cost per WHOLESALE unit.
-- - Some historical GRN PURCHASE rows may have been written with unit_cost per wholesale.
-- - items.default_cost_per_base was populated from Excel as cost per wholesale; base = retail now.
-- - Ledger and snapshot must use cost per RETAIL unit consistently.
--
-- Scope:
-- 1) OPENING_BALANCE: for each row, unit_cost = unit_cost / pack_size, total_cost and batch_cost recomputed.
-- 2) PURCHASE + reference_type = 'grn': where ledger.unit_cost ~= grn_items.unit_cost (per wholesale),
--    set unit_cost = line.unit_cost / multiplier (per retail), recompute total_cost and batch_cost.
-- 3) items.default_cost_per_base: set default_cost_per_base = default_cost_per_base / pack_size
--    where not null and pack_size > 1 (assumes current values are per wholesale).
-- 4) Enqueue branch-wide snapshot refresh for every (company_id, branch_id) that has ledger rows,
--    so item_branch_snapshot and item_branch_purchase_snapshot are updated with corrected costs.
--
-- IMPORTANT:
-- - quantity_delta is never changed.
-- - Only rows that were stored per wholesale are corrected (GRN: match on unit + cost equality).

DO $$
DECLARE
    v_cutoff TIMESTAMPTZ := '2026-03-12 00:00:00+00';
BEGIN
    -- -------------------------------------------------------------------------
    -- 1) OPENING_BALANCE: convert unit_cost from per-wholesale to per-retail
    -- -------------------------------------------------------------------------
    UPDATE inventory_ledger l
    SET
        unit_cost   = l.unit_cost / GREATEST(1, COALESCE(i.pack_size, 1)),
        total_cost  = (l.unit_cost / GREATEST(1, COALESCE(i.pack_size, 1))) * l.quantity_delta,
        batch_cost  = CASE WHEN l.batch_cost IS NOT NULL
                          THEN (l.unit_cost / GREATEST(1, COALESCE(i.pack_size, 1)))
                          ELSE l.batch_cost END
    FROM items i
    WHERE i.id = l.item_id
      AND l.transaction_type = 'OPENING_BALANCE'
      AND l.reference_type   = 'OPENING_BALANCE'
      AND l.created_at      < v_cutoff;

    -- -------------------------------------------------------------------------
    -- 2) GRN PURCHASE: where unit_cost was stored per wholesale, convert to per retail
    --    Match ledger to grn_items by reference_id=grn_id, item_id, and batch_number/expiry when present.
    --    Only update when line unit matches item wholesale and ledger.unit_cost ~= line.unit_cost.
    -- -------------------------------------------------------------------------
    WITH grn_candidate AS (
        SELECT
            l.id                    AS ledger_id,
            l.quantity_delta         AS qty_delta,
            i.pack_size,
            gi.unit_cost             AS line_unit_cost,
            LOWER(COALESCE(NULLIF(TRIM(i.wholesale_unit), ''), 'piece')) AS wholesale_name,
            LOWER(COALESCE(NULLIF(TRIM(gi.unit_name), ''), 'piece'))     AS line_unit_name
        FROM inventory_ledger l
        JOIN grns g           ON g.id = l.reference_id
        JOIN grn_items gi     ON gi.grn_id = g.id AND gi.item_id = l.item_id
        JOIN items i          ON i.id = l.item_id
        WHERE l.transaction_type = 'PURCHASE'
          AND l.reference_type   = 'grn'
          AND l.created_at      < v_cutoff
          AND (l.batch_number IS NOT DISTINCT FROM gi.batch_number)
          AND (l.expiry_date   IS NOT DISTINCT FROM gi.expiry_date)
          AND LOWER(COALESCE(NULLIF(TRIM(gi.unit_name), ''), 'piece'))
              = LOWER(COALESCE(NULLIF(TRIM(i.wholesale_unit), ''), 'piece'))
          AND ABS(l.unit_cost - gi.unit_cost) < 0.0001
    )
    UPDATE inventory_ledger l
    SET
        unit_cost  = (c.line_unit_cost / GREATEST(1, COALESCE(c.pack_size, 1))),
        total_cost = (c.line_unit_cost / GREATEST(1, COALESCE(c.pack_size, 1))) * c.qty_delta,
        batch_cost = (c.line_unit_cost / GREATEST(1, COALESCE(c.pack_size, 1)))
    FROM grn_candidate c
    WHERE l.id = c.ledger_id;

    -- -------------------------------------------------------------------------
    -- 3) items.default_cost_per_base: normalize to per-retail (was per-wholesale from Excel)
    -- -------------------------------------------------------------------------
    UPDATE items
    SET default_cost_per_base = default_cost_per_base / GREATEST(1, COALESCE(pack_size, 1))
    WHERE default_cost_per_base IS NOT NULL
      AND COALESCE(pack_size, 1) > 1;

    -- -------------------------------------------------------------------------
    -- 4) Enqueue branch-wide snapshot refresh for every (company_id, branch_id) in ledger
    --    so background processor refreshes item_branch_snapshot with corrected costs.
    -- -------------------------------------------------------------------------
    INSERT INTO snapshot_refresh_queue (company_id, branch_id, item_id, created_at, reason)
    SELECT DISTINCT l.company_id, l.branch_id, NULL::uuid, NOW(), '066_ledger_unit_cost_backfill'
    FROM inventory_ledger l
    WHERE NOT EXISTS (
        SELECT 1 FROM snapshot_refresh_queue q
        WHERE q.company_id = l.company_id
          AND q.branch_id  = l.branch_id
          AND q.item_id   IS NULL
          AND q.processed_at IS NULL
    );

END $$;
