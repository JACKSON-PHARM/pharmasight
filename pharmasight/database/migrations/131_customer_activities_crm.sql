-- Migration 131: CRM-lite customer activities

CREATE TABLE IF NOT EXISTS customer_activities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    notes TEXT,
    due_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    assigned_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    completed_at TIMESTAMPTZ,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT customer_activities_type_check CHECK (
        activity_type IN ('call', 'visit', 'email', 'follow_up', 'other')
    ),
    CONSTRAINT customer_activities_status_check CHECK (
        status IN ('open', 'completed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_customer_activities_company ON customer_activities(company_id);
CREATE INDEX IF NOT EXISTS idx_customer_activities_customer ON customer_activities(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_activities_due ON customer_activities(company_id, due_date)
    WHERE status = 'open';

COMMENT ON TABLE customer_activities IS 'CRM follow-ups for wholesale customers.';

-- Phase 5 foundation: external customer login (not fully implemented)
CREATE TABLE IF NOT EXISTS customer_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    auth_user_id UUID,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    invited_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT customer_users_company_email_unique UNIQUE (company_id, email)
);

CREATE INDEX IF NOT EXISTS idx_customer_users_customer ON customer_users(customer_id);

COMMENT ON TABLE customer_users IS 'Future B2B portal identities (Phase 5). auth_user_id links to Supabase when enabled.';
