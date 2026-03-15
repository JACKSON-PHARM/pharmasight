-- Migration 072: Normalize inventory_ledger.unit_cost where mixed scales exist (packet vs retail).
--
-- Background:
-- - Ledger contains mixed units: some rows have cost per retail, some per packet (pack_size).
-- - CanonicalPricingService.get_cost_per_retail_for_valuation_batch() divides by pack_size
--   for items without last PURCHASE, which is wrong when the ledger already stores retail cost.
--
-- This migration (run once):
-- 1) Detects items that have BOTH scales: max_cost >= min_cost * pack_size * 0.9
-- 2) Converts only the high-scale (packet) rows to retail: unit_cost = unit_cost / pack_size
-- 3) Recomputes total_cost (and batch_cost when present)
-- 4) Does NOT touch items with only one cost scale
--
-- After this migration, remove the pack_size division in the pricing service (code change).
-- Items that have only packet-cost rows (no retail row) are NOT converted here (later review).

DO $$
DECLARE
    v_rows_updated INTEGER;
BEGIN
    WITH item_stats AS (
        SELECT
            l.item_id,
            GREATEST(1, COALESCE(i.pack_size, 1)) AS pack_size,
            MIN(l.unit_cost) AS min_cost,
            MAX(l.unit_cost) AS max_cost
        FROM inventory_ledger l
        JOIN items i ON i.id = l.item_id
        GROUP BY l.item_id, i.pack_size
        HAVING MIN(l.unit_cost) > 0
           AND MAX(l.unit_cost) >= (MIN(l.unit_cost) * GREATEST(1, COALESCE(i.pack_size, 1)) * 0.9)
    ),
    rows_to_update AS (
        SELECT
            l.id AS ledger_id,
            l.quantity_delta,
            l.unit_cost AS old_unit_cost,
            s.pack_size,
            l.batch_cost AS old_batch_cost
        FROM inventory_ledger l
        JOIN item_stats s ON s.item_id = l.item_id
        WHERE l.unit_cost >= (s.min_cost * s.pack_size * 0.9)
    )
    UPDATE inventory_ledger l
    SET
        unit_cost   = (r.old_unit_cost / r.pack_size),
        total_cost  = (r.old_unit_cost / r.pack_size) * r.quantity_delta,
        batch_cost  = CASE WHEN l.batch_cost IS NOT NULL
                          THEN (r.old_unit_cost / r.pack_size)
                          ELSE l.batch_cost END
    FROM rows_to_update r
    WHERE l.id = r.ledger_id;

    GET DIAGNOSTICS v_rows_updated = ROW_COUNT;
    RAISE NOTICE '072_inventory_ledger_normalize_mixed_unit_cost: updated % rows (packet-cost -> retail)', v_rows_updated;
END $$;
