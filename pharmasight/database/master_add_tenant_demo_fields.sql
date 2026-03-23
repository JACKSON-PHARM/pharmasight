-- Migration: Add demo/plan fields to tenants (master DB)
-- Safe to run on existing master database; defaults preserve current behaviour.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) NOT NULL DEFAULT 'paid',
    ADD COLUMN IF NOT EXISTS demo_expires_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS product_limit INT NULL,
    ADD COLUMN IF NOT EXISTS branch_limit INT NULL,
    ADD COLUMN IF NOT EXISTS user_limit INT NULL;

