-- Migration 077: Cashbook engine (money movement tracking)
-- Adds table cashbook_entries:
-- - tracking layer for inflow/outflow sourced from expenses + supplier payments
-- - deduped by (company_id, source_type, source_id)

CREATE TABLE IF NOT EXISTS cashbook_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,

    date DATE NOT NULL,
    type VARCHAR(20) NOT NULL, -- inflow | outflow
    amount NUMERIC(20, 4) NOT NULL,
    payment_mode VARCHAR(20) NOT NULL, -- cash | mpesa | bank

    source_type VARCHAR(50) NOT NULL, -- expense | supplier_payment | sale
    source_id UUID NOT NULL,
    reference_number VARCHAR(100),
    description TEXT,

    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Deduplication: one cashbook entry per source record.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_cashbook_company_source'
    ) THEN
        ALTER TABLE cashbook_entries
            ADD CONSTRAINT uq_cashbook_company_source UNIQUE (company_id, source_type, source_id);
    END IF;
END $$;

-- Common filters / ordering
CREATE INDEX IF NOT EXISTS idx_cashbook_entries_date ON cashbook_entries(date);
CREATE INDEX IF NOT EXISTS idx_cashbook_entries_branch_id ON cashbook_entries(branch_id);
CREATE INDEX IF NOT EXISTS idx_cashbook_entries_source_type_id ON cashbook_entries(source_type, source_id);

-- Optional value checks (keep strict to preserve UI expectations)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cashbook_type_check'
    ) THEN
        ALTER TABLE cashbook_entries
            ADD CONSTRAINT cashbook_type_check CHECK (type IN ('inflow', 'outflow'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cashbook_payment_mode_check'
    ) THEN
        ALTER TABLE cashbook_entries
            ADD CONSTRAINT cashbook_payment_mode_check CHECK (payment_mode IN ('cash', 'mpesa', 'bank'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cashbook_source_type_check'
    ) THEN
        ALTER TABLE cashbook_entries
            ADD CONSTRAINT cashbook_source_type_check CHECK (source_type IN ('expense', 'supplier_payment', 'sale'));
    END IF;
END $$;

