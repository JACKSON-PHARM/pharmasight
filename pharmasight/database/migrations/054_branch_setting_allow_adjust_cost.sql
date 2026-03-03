-- Migration 054: Branch setting to allow cost adjustment (inventory.adjust_cost) per branch.
-- When false, cost adjustment is disabled for the branch even if user has the role permission.

ALTER TABLE branch_settings
ADD COLUMN IF NOT EXISTS allow_adjust_cost BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN branch_settings.allow_adjust_cost IS 'If true, users with inventory.adjust_cost permission can adjust batch cost at this branch.';
