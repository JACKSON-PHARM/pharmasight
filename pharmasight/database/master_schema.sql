-- =====================================================
-- PHARMASIGHT MASTER DATABASE SCHEMA
-- Multi-Tenant SaaS Management Database
-- =====================================================
-- This database stores tenant metadata and manages
-- all client databases. Each tenant gets their own
-- isolated Supabase database.
-- =====================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- TENANTS (CLIENTS)
-- =====================================================

CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    subdomain VARCHAR(100) UNIQUE NOT NULL,
    custom_domain VARCHAR(255),
    
    -- Database connection info (encrypted)
    database_name VARCHAR(255),  -- Supabase project name
    database_url TEXT,            -- Encrypted connection string
    supabase_project_id VARCHAR(255),  -- Supabase project ID
    supabase_project_ref VARCHAR(255), -- Supabase project reference
    
    -- Status
    status VARCHAR(20) DEFAULT 'trial',  -- 'trial', 'active', 'suspended', 'cancelled'
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    trial_ends_at TIMESTAMPTZ,  -- When trial period ends
    
    -- Admin user info (first user created)
    admin_email VARCHAR(255) NOT NULL,
    admin_user_id UUID,  -- User ID in tenant's database
    
    CONSTRAINT valid_status CHECK (status IN ('trial', 'active', 'suspended', 'cancelled', 'past_due'))
);

CREATE INDEX idx_tenants_subdomain ON tenants(subdomain);
CREATE INDEX idx_tenants_status ON tenants(status);
CREATE INDEX idx_tenants_admin_email ON tenants(admin_email);

COMMENT ON TABLE tenants IS 'Master tenant registry. Each tenant has their own isolated database.';
COMMENT ON COLUMN tenants.database_url IS 'Encrypted Supabase connection string. Should be encrypted at application level.';
COMMENT ON COLUMN tenants.status IS 'trial: 14-day free trial, active: paid subscription, suspended: access blocked, cancelled: subscription ended';

-- =====================================================
-- TENANT INVITES (SETUP TOKENS)
-- =====================================================

CREATE TABLE tenant_invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID,  -- Admin user ID in tenant's database
    
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT token_not_expired CHECK (expires_at > created_at)
);

CREATE INDEX idx_tenant_invites_token ON tenant_invites(token);
CREATE INDEX idx_tenant_invites_tenant_id ON tenant_invites(tenant_id);
CREATE INDEX idx_tenant_invites_expires_at ON tenant_invites(expires_at);

COMMENT ON TABLE tenant_invites IS 'One-time invite tokens for tenant setup. Expires after 7 days.';

-- =====================================================
-- SUBSCRIPTION PLANS
-- =====================================================

CREATE TABLE subscription_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,  -- 'Starter', 'Professional', 'Enterprise'
    description TEXT,
    
    -- Pricing
    price_monthly DECIMAL(10, 2),
    price_yearly DECIMAL(10, 2),
    
    -- Limits
    max_users INTEGER,
    max_branches INTEGER,
    max_items INTEGER,
    
    -- Features (JSON array of module names)
    included_modules TEXT[],
    
    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE subscription_plans IS 'Available subscription plans with features and limits.';

-- =====================================================
-- TENANT SUBSCRIPTIONS
-- =====================================================

CREATE TABLE tenant_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES subscription_plans(id),
    
    status VARCHAR(20) DEFAULT 'trial',  -- 'trial', 'active', 'cancelled', 'past_due'
    
    -- Billing period
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    
    -- Cancellation
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    cancelled_at TIMESTAMPTZ,
    
    -- Stripe integration
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_subscription_status CHECK (status IN ('trial', 'active', 'cancelled', 'past_due', 'suspended'))
);

CREATE INDEX idx_tenant_subscriptions_tenant_id ON tenant_subscriptions(tenant_id);
CREATE INDEX idx_tenant_subscriptions_status ON tenant_subscriptions(status);
CREATE INDEX idx_tenant_subscriptions_stripe_subscription_id ON tenant_subscriptions(stripe_subscription_id);

COMMENT ON TABLE tenant_subscriptions IS 'Active subscriptions for each tenant. Links to Stripe for billing.';

-- =====================================================
-- TENANT MODULES (FEATURE FLAGS)
-- =====================================================

CREATE TABLE tenant_modules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    module_name VARCHAR(100) NOT NULL,  -- 'inventory', 'sales', 'purchases', 'reports', etc.
    
    is_enabled BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMPTZ,  -- NULL = perpetual (from subscription plan)
    
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(tenant_id, module_name)
);

CREATE INDEX idx_tenant_modules_tenant_id ON tenant_modules(tenant_id);
CREATE INDEX idx_tenant_modules_module_name ON tenant_modules(module_name);

COMMENT ON TABLE tenant_modules IS 'Feature flags per tenant. Controls which modules are enabled.';

-- =====================================================
-- SEED DATA: SUBSCRIPTION PLANS
-- =====================================================

INSERT INTO subscription_plans (name, description, price_monthly, price_yearly, max_users, max_branches, max_items, included_modules) VALUES
('Starter', 'Perfect for small pharmacies', 99.00, 990.00, 5, 1, 10000, ARRAY['inventory', 'sales', 'purchases']),
('Professional', 'For growing pharmacies', 299.00, 2990.00, 20, 5, 50000, ARRAY['inventory', 'sales', 'purchases', 'reports', 'stock_take', 'multi_branch']),
('Enterprise', 'Custom solutions for large operations', NULL, NULL, NULL, NULL, NULL, ARRAY['inventory', 'sales', 'purchases', 'reports', 'stock_take', 'multi_branch', 'api_access', 'advanced_reports', 'custom_branding']);

-- =====================================================
-- TRIGGERS
-- =====================================================

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_tenants_updated_at BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_subscription_plans_updated_at BEFORE UPDATE ON subscription_plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tenant_subscriptions_updated_at BEFORE UPDATE ON tenant_subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tenant_modules_updated_at BEFORE UPDATE ON tenant_modules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
