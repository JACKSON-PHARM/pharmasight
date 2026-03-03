-- Migration 055: Cost outlier threshold + override permission
-- - Adds optional company-level setting pricing_settings.cost_outlier_threshold_pct
--   to control how far a new unit cost may deviate from branch weighted average
--   before manager override is required.
-- - Seeds inventory.cost_override permission for RBAC.

ALTER TABLE pricing_settings
ADD COLUMN IF NOT EXISTS cost_outlier_threshold_pct NUMERIC(10, 2) NULL;

COMMENT ON COLUMN pricing_settings.cost_outlier_threshold_pct IS
    'Max allowed deviation (%) from branch weighted average cost before override is required. NULL = use application default.';

INSERT INTO permissions (name, module, action, description) VALUES
('inventory.cost_override', 'inventory', 'cost_override', 'Approve inventory cost outliers above configured deviation threshold')
ON CONFLICT (name) DO NOTHING;

