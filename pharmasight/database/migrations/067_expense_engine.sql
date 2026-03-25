-- Migration 067: Expense engine workflow fields
-- Adds: expense_categories.is_active, expenses.status/approved_by/approved_at/updated_at, payment_mode NOT NULL
-- Safe additive changes; preserves existing data.

ALTER TABLE expense_categories
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE expense_categories
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'approved';

ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id);

ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

-- payment_mode was nullable in initial schema; enforce required for new rows
ALTER TABLE expenses
    ALTER COLUMN payment_mode SET NOT NULL;

-- Basic status constraint (optional; keep loose if legacy data exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'expenses_status_check'
    ) THEN
        ALTER TABLE expenses
            ADD CONSTRAINT expenses_status_check CHECK (status IN ('pending', 'approved'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_expenses_company_branch_date ON expenses(company_id, branch_id, expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_company_status ON expenses(company_id, status);
CREATE INDEX IF NOT EXISTS idx_expense_categories_company_active ON expense_categories(company_id, is_active);

