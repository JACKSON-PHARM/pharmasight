-- Migration 150: Platform usage telemetry
-- Privacy-safe SaaS operator metrics. Stores metadata only: signup/login/user-created
-- events and aggregated API request counters. No client business records are stored.

CREATE TABLE IF NOT EXISTS platform_usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(60) NOT NULL,
    actor_email VARCHAR(255),
    actor_name VARCHAR(255),
    company_name VARCHAR(255),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_ip VARCHAR(80),
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_usage_events_created
    ON platform_usage_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_platform_usage_events_company_created
    ON platform_usage_events(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_platform_usage_events_type_created
    ON platform_usage_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS platform_usage_counters (
    hour_start TIMESTAMPTZ NOT NULL,
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    endpoint_group VARCHAR(120) NOT NULL,
    method VARCHAR(12) NOT NULL,
    status_family VARCHAR(8) NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    total_duration_ms INTEGER NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (hour_start, company_id, endpoint_group, method, status_family)
);

CREATE INDEX IF NOT EXISTS idx_platform_usage_counters_company_hour
    ON platform_usage_counters(company_id, hour_start DESC);

CREATE INDEX IF NOT EXISTS idx_platform_usage_counters_hour
    ON platform_usage_counters(hour_start DESC);

-- Backfill enough metadata so the platform dashboard is useful immediately after deploy.
-- Existing company rows become historical client_signup events. Existing refresh token
-- history becomes one latest user_login event per company/user where possible.
INSERT INTO platform_usage_events (
    company_id, event_type, company_name, metadata, created_at
)
SELECT
    c.id,
    'client_signup',
    c.name,
    jsonb_build_object('source', 'company_backfill'),
    COALESCE(c.created_at, NOW())
FROM companies c
WHERE NOT EXISTS (
    SELECT 1
    FROM platform_usage_events e
    WHERE e.company_id = c.id
      AND e.event_type = 'client_signup'
);

INSERT INTO platform_usage_events (
    company_id, user_id, event_type, actor_email, actor_name, company_name, metadata, created_at
)
SELECT
    b.company_id,
    u.id,
    'user_login',
    u.email,
    u.full_name,
    c.name,
    jsonb_build_object('source', 'refresh_token_backfill'),
    MAX(rt.issued_at)
FROM refresh_tokens rt
JOIN users u ON u.id = rt.user_id
JOIN user_branch_roles ubr ON ubr.user_id = u.id
JOIN branches b ON b.id = ubr.branch_id
JOIN companies c ON c.id = b.company_id
WHERE rt.issued_at IS NOT NULL
GROUP BY b.company_id, u.id, u.email, u.full_name, c.name
HAVING NOT EXISTS (
    SELECT 1
    FROM platform_usage_events e
    WHERE e.company_id = b.company_id
      AND e.user_id = u.id
      AND e.event_type = 'user_login'
);
