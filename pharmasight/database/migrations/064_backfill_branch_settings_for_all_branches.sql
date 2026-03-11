-- Migration 064: Backfill branch_settings for every branch that has no row.
-- Ensures all branches (including those created before we auto-create settings) have explicit defaults.
-- Safe to run multiple times (only inserts where no row exists).

INSERT INTO branch_settings (
    id,
    branch_id,
    allow_manual_transfer,
    allow_manual_receipt,
    allow_adjust_cost,
    cost_outlier_threshold_pct,
    min_margin_retail_pct_override,
    created_at,
    updated_at
)
SELECT
    uuid_generate_v4(),
    b.id,
    true,
    true,
    true,
    NULL,
    NULL,
    NOW(),
    NOW()
FROM branches b
LEFT JOIN branch_settings bs ON bs.branch_id = b.id
WHERE bs.id IS NULL;
