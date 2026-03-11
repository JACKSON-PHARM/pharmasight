-- Migration 065: Backfill inventory_ledger.unit_cost to be per RETAIL unit.
--
-- Background:
-- - Some historical PURCHASE rows were written with unit_cost equal to the
--   supplier invoice line unit_cost_exclusive (typically per WHOLESALE unit / packet),
--   instead of per retail (tablet).
-- - This migration normalizes those rows so that unit_cost is per retail unit,
--   without changing quantities.
--
-- Scope:
-- - Only PURCHASE rows linked to Supplier Invoices
--   (transaction_type = 'PURCHASE', reference_type = 'purchase_invoice').
-- - Only rows where:
--   * The supplier invoice line's unit_name clearly matches the item's wholesale unit
--     (case-insensitive), and
--   * inventory_ledger.unit_cost ~= purchase_invoice_items.unit_cost_exclusive
--     (i.e. ledger stored per wholesale unit).
-- - Rows created before this migration was introduced (safety cutoff date).
--
-- IMPORTANT:
-- - This does NOT touch rows that already stored unit_cost per retail.
-- - Quantities (quantity_delta) are NOT changed.
-- - total_cost is recomputed as quantity_delta * corrected unit_cost.

DO $$
DECLARE
    v_cutoff TIMESTAMPTZ := '2026-03-12 00:00:00+00'; -- adjust if needed
BEGIN
    -- Backfill for Supplier Invoice PURCHASE rows where unit_name = wholesale_unit
    -- and ledger.unit_cost ~= line.unit_cost_exclusive.
    WITH candidate AS (
        SELECT
            l.id                            AS ledger_id,
            l.quantity_delta                AS qty_delta,
            i.pack_size,
            sii.unit_cost_exclusive,
            -- Normalize names for comparison
            LOWER(COALESCE(NULLIF(i.wholesale_unit, ''), NULLIF(i.base_unit, ''), 'piece')) AS wholesale_name,
            LOWER(sii.unit_name)                                                     AS line_unit_name
        FROM inventory_ledger l
        JOIN purchase_invoices pi
              ON pi.id = l.reference_id
        JOIN purchase_invoice_items sii
              ON sii.purchase_invoice_id = pi.id
             AND sii.item_id = l.item_id
        JOIN items i
              ON i.id = l.item_id
        WHERE l.transaction_type = 'PURCHASE'
          AND l.reference_type   = 'purchase_invoice'
          AND l.created_at      < v_cutoff
          -- Unit name must clearly match wholesale (or historical base) unit
          AND LOWER(sii.unit_name) = LOWER(COALESCE(NULLIF(i.wholesale_unit, ''), NULLIF(i.base_unit, ''), 'piece'))
          -- Only when ledger.unit_cost essentially equals the line's cost per wholesale unit
          AND ABS(l.unit_cost - sii.unit_cost_exclusive) < 0.0001
    )
    UPDATE inventory_ledger l
    SET
        unit_cost = (c.unit_cost_exclusive / GREATEST(1, COALESCE(c.pack_size, 1))), -- per retail unit
        total_cost = (c.unit_cost_exclusive / GREATEST(1, COALESCE(c.pack_size, 1))) * c.qty_delta,
        batch_cost = (c.unit_cost_exclusive / GREATEST(1, COALESCE(c.pack_size, 1)))
    FROM candidate c
    WHERE l.id = c.ledger_id;

    -- NOTE:
    -- - item_branch_purchase_snapshot and item_branch_snapshot will be refreshed
    --   by the existing snapshot refresh pipeline (SnapshotRefreshService) after deploy.
END $$;

