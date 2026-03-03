-- Migration 056: Branch-level pricing overrides
-- - Adds optional per-branch cost outlier threshold and minimum margin override.

ALTER TABLE branch_settings
ADD COLUMN IF NOT EXISTS cost_outlier_threshold_pct NUMERIC(10, 2) NULL,
ADD COLUMN IF NOT EXISTS min_margin_retail_pct_override NUMERIC(10, 2) NULL;

COMMENT ON COLUMN branch_settings.cost_outlier_threshold_pct IS
    'Max allowed deviation (%) from branch weighted average cost before override is required for this branch.';

COMMENT ON COLUMN branch_settings.min_margin_retail_pct_override IS
    'Branch-level minimum retail margin (%) when no stricter item/tier/company rule applies.';

