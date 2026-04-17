-- Migration 091: Backfill companies from legacy tenant_subscriptions (read-only on legacy tables; no writes to tenants or tenant_subscriptions).
--
-- PREREQ: public.tenant_subscriptions, public.tenants, public.subscription_plans, and public.companies
-- must live in the SAME database (typical when MASTER_DATABASE_URL equals DATABASE_URL).
-- If master and app DBs are split, run an equivalent ETL externally — do not run this blindly.

-- 1) Primary path: resolve company via tenants.admin_user_id → user_branch_roles → branches.company_id
WITH sub_pick AS (
    SELECT DISTINCT ON (b.company_id)
        b.company_id,
        ts.stripe_customer_id AS scid,
        ts.stripe_subscription_id AS ssid,
        ts.status AS tss,
        sp.name AS plan_name
    FROM tenant_subscriptions ts
    JOIN tenants t ON t.id = ts.tenant_id
    JOIN subscription_plans sp ON sp.id = ts.plan_id
    JOIN users u ON u.id = t.admin_user_id AND u.deleted_at IS NULL
    JOIN user_branch_roles ubr ON ubr.user_id = u.id
    JOIN branches b ON b.id = ubr.branch_id
    WHERE b.company_id IS NOT NULL
      AND (NULLIF(TRIM(ts.stripe_customer_id), '') IS NOT NULL OR NULLIF(TRIM(ts.stripe_subscription_id), '') IS NOT NULL)
    ORDER BY b.company_id, ts.updated_at DESC NULLS LAST, ts.created_at DESC NULLS LAST
)
UPDATE companies c
SET
    stripe_customer_id = COALESCE(NULLIF(TRIM(c.stripe_customer_id), ''), NULLIF(TRIM(s.scid), '')),
    stripe_subscription_id = COALESCE(NULLIF(TRIM(c.stripe_subscription_id), ''), NULLIF(TRIM(s.ssid), '')),
    subscription_plan = COALESCE(
        c.subscription_plan,
        NULLIF(lower(replace(trim(s.plan_name), ' ', '_')), '')
    ),
    subscription_status = COALESCE(
        c.subscription_status,
        CASE lower(COALESCE(s.tss, ''))
            WHEN 'active' THEN 'active'
            WHEN 'trial' THEN 'trial'
            WHEN 'past_due' THEN 'past_due'
            WHEN 'cancelled' THEN 'canceled'
            WHEN 'suspended' THEN 'suspended'
            ELSE NULL
        END
    )
FROM sub_pick s
WHERE c.id = s.company_id
  AND (
      (NULLIF(TRIM(c.stripe_customer_id), '') IS NULL AND NULLIF(TRIM(s.scid), '') IS NOT NULL)
      OR (NULLIF(TRIM(c.stripe_subscription_id), '') IS NULL AND NULLIF(TRIM(s.ssid), '') IS NOT NULL)
      OR c.subscription_status IS NULL
      OR c.subscription_plan IS NULL
  );

-- 2) Fallback: match tenant name to company name when admin_user_id path did not populate stripe ids
WITH sub_name AS (
    SELECT DISTINCT ON (lower(trim(t.name)))
        lower(trim(t.name)) AS tkey,
        ts.stripe_customer_id AS scid,
        ts.stripe_subscription_id AS ssid,
        ts.status AS tss,
        sp.name AS plan_name
    FROM tenant_subscriptions ts
    JOIN tenants t ON t.id = ts.tenant_id
    JOIN subscription_plans sp ON sp.id = ts.plan_id
    WHERE (NULLIF(TRIM(ts.stripe_customer_id), '') IS NOT NULL OR NULLIF(TRIM(ts.stripe_subscription_id), '') IS NOT NULL)
    ORDER BY lower(trim(t.name)), ts.updated_at DESC NULLS LAST, ts.created_at DESC NULLS LAST
)
UPDATE companies c
SET
    stripe_customer_id = COALESCE(NULLIF(TRIM(c.stripe_customer_id), ''), NULLIF(TRIM(n.scid), '')),
    stripe_subscription_id = COALESCE(NULLIF(TRIM(c.stripe_subscription_id), ''), NULLIF(TRIM(n.ssid), '')),
    subscription_plan = COALESCE(
        c.subscription_plan,
        NULLIF(lower(replace(trim(n.plan_name), ' ', '_')), '')
    ),
    subscription_status = COALESCE(
        c.subscription_status,
        CASE lower(COALESCE(n.tss, ''))
            WHEN 'active' THEN 'active'
            WHEN 'trial' THEN 'trial'
            WHEN 'past_due' THEN 'past_due'
            WHEN 'cancelled' THEN 'canceled'
            WHEN 'suspended' THEN 'suspended'
            ELSE NULL
        END
    )
FROM sub_name n
WHERE lower(trim(c.name)) = n.tkey
  AND (NULLIF(TRIM(c.stripe_customer_id), '') IS NULL OR NULLIF(TRIM(c.stripe_subscription_id), '') IS NULL);
