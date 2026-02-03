-- Ensure item_pricing exists (e.g. if DB was created without full 001_initial or table was dropped).
-- Idempotent: safe to run even when table already exists.

CREATE TABLE IF NOT EXISTS item_pricing (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    markup_percent NUMERIC(10,2),
    min_margin_percent NUMERIC(10,2),
    rounding_rule VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id)
);

COMMENT ON TABLE item_pricing IS 'Item-specific pricing is GLOBAL per company. No branch-level pricing.';
