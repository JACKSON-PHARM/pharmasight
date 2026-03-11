-- Migration 067: Backfill ADJUSTMENT ledger unit_cost from per-wholesale to per-retail.
--
-- Background: Migration 066 fixed OPENING_BALANCE and GRN only. Manual ADJUSTMENT rows
-- (e.g. stock corrections) were often entered with unit_cost per packet. Snapshot cost
-- uses last_purchase_price (which includes ADJUSTMENT) and weighted average, so those
-- rows with per-packet cost produce wrong per-tablet prices in item_branch_snapshot.
--
-- Scope: ADJUSTMENT rows with quantity_delta > 0 and item.pack_size > 1: convert
-- unit_cost to per-retail (unit_cost / pack_size), recompute total_cost and batch_cost.
-- Cutoff: only rows created before 2026-03-12 so we don't touch future data.
--
-- After this, run bulk snapshot refresh for affected branches so snapshot shows correct prices.

DO $$
DECLARE
    v_cutoff TIMESTAMPTZ := '2026-03-12 00:00:00+00';
BEGIN
    UPDATE inventory_ledger l
    SET
        unit_cost   = l.unit_cost / GREATEST(1, COALESCE(i.pack_size, 1)),
        total_cost  = (l.unit_cost / GREATEST(1, COALESCE(i.pack_size, 1))) * l.quantity_delta,
        batch_cost  = CASE WHEN l.batch_cost IS NOT NULL
                          THEN (l.unit_cost / GREATEST(1, COALESCE(i.pack_size, 1)))
                          ELSE l.batch_cost END
    FROM items i
    WHERE i.id = l.item_id
      AND l.transaction_type = 'ADJUSTMENT'
      AND l.quantity_delta   > 0
      AND COALESCE(i.pack_size, 1) > 1
      AND l.created_at       < v_cutoff;

    -- Enqueue or re-queue branch-wide snapshot refresh for branches that had adjusted rows.
    -- Unique on (company_id, branch_id) for item_id IS NULL: use ON CONFLICT to re-queue if already processed.
    INSERT INTO snapshot_refresh_queue (company_id, branch_id, item_id, created_at, reason)
    SELECT DISTINCT l.company_id, l.branch_id, NULL::uuid, NOW(), '067_adjustment_unit_cost_per_retail'
    FROM inventory_ledger l
    JOIN items i ON i.id = l.item_id
    WHERE l.transaction_type = 'ADJUSTMENT'
      AND l.quantity_delta   > 0
      AND COALESCE(i.pack_size, 1) > 1
      AND l.created_at       < v_cutoff
    ON CONFLICT (company_id, branch_id) WHERE (item_id IS NULL) DO UPDATE SET
      processed_at = NULL,
      claimed_at   = NULL,
      reason       = EXCLUDED.reason,
      created_at   = NOW();
END $$;
