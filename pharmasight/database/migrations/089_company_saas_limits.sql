-- Migration 089: SaaS demo/product limits on companies (Option B — no Tenant entitlement reads)

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS product_limit INTEGER NULL,
    ADD COLUMN IF NOT EXISTS branch_limit INTEGER NULL,
    ADD COLUMN IF NOT EXISTS user_limit INTEGER NULL;

COMMENT ON COLUMN companies.product_limit IS 'Optional cap on products/items for demo or tiered plans; enforced in app from companies only.';
COMMENT ON COLUMN companies.branch_limit IS 'Optional cap on branches for demo or tiered plans.';
COMMENT ON COLUMN companies.user_limit IS 'Optional cap on distinct users assigned to this company branches; enforced in app from companies only.';
