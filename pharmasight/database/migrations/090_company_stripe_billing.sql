-- Migration 090: Stripe customer + subscription IDs on companies (Phase 2 — company-only billing)

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255) NULL,
    ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255) NULL;

CREATE INDEX IF NOT EXISTS idx_companies_stripe_customer_id
    ON companies (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL AND stripe_customer_id <> '';

CREATE INDEX IF NOT EXISTS idx_companies_stripe_subscription_id
    ON companies (stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL AND stripe_subscription_id <> '';

COMMENT ON COLUMN companies.stripe_customer_id IS 'Stripe Customer id (cus_...); authoritative billing identity for this company.';
COMMENT ON COLUMN companies.stripe_subscription_id IS 'Stripe Subscription id (sub_...) for the active SaaS subscription when applicable.';
