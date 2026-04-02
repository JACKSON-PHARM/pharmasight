-- Migration 085: Module classification metadata (core | business | clinical)
-- This is future-proofing for multi-layer module gating.

CREATE TABLE IF NOT EXISTS modules (
    name VARCHAR(100) PRIMARY KEY,
    category VARCHAR(20) NOT NULL CHECK (category IN ('core', 'business', 'clinical')),
    is_core BOOLEAN NOT NULL DEFAULT FALSE,
    is_clinical BOOLEAN NOT NULL DEFAULT FALSE,
    is_billable BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed core modules (implicit platform capabilities)
INSERT INTO modules (name, category, is_core, is_clinical, is_billable) VALUES
    ('management', 'core', TRUE, FALSE, FALSE),
    ('settings', 'core', TRUE, FALSE, FALSE),
    ('users', 'core', TRUE, FALSE, FALSE),
    ('roles', 'core', TRUE, FALSE, FALSE),
    ('reports', 'core', TRUE, FALSE, FALSE),
    ('dashboard', 'core', TRUE, FALSE, FALSE),
    ('notifications', 'core', TRUE, FALSE, FALSE),
    ('audit_logs', 'core', TRUE, FALSE, FALSE)
ON CONFLICT (name) DO NOTHING;

-- Seed business modules (licensed)
INSERT INTO modules (name, category, is_core, is_clinical, is_billable) VALUES
    ('pharmacy', 'business', FALSE, FALSE, TRUE),
    ('inventory', 'business', FALSE, FALSE, FALSE),
    ('finance', 'business', FALSE, FALSE, TRUE),
    ('procurement', 'business', FALSE, FALSE, TRUE),
    ('pos', 'business', FALSE, FALSE, TRUE),
    ('billing', 'business', FALSE, FALSE, TRUE)
ON CONFLICT (name) DO NOTHING;

-- Seed clinical modules (licensed, optional hospital extensions)
INSERT INTO modules (name, category, is_core, is_clinical, is_billable) VALUES
    ('clinic', 'clinical', FALSE, TRUE, TRUE),
    ('patients', 'clinical', FALSE, TRUE, TRUE),
    ('opd', 'clinical', FALSE, TRUE, TRUE),
    ('prescriptions', 'clinical', FALSE, TRUE, TRUE),
    ('lab', 'clinical', FALSE, TRUE, TRUE),
    ('radiology', 'clinical', FALSE, TRUE, TRUE),
    ('ipd', 'clinical', FALSE, TRUE, TRUE),
    ('emr', 'clinical', FALSE, TRUE, TRUE)
ON CONFLICT (name) DO NOTHING;

