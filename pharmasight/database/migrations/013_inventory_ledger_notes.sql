-- Optional notes/comments on inventory ledger entries (e.g. for manual adjustments: source, reason)
ALTER TABLE inventory_ledger ADD COLUMN IF NOT EXISTS notes TEXT;
COMMENT ON COLUMN inventory_ledger.notes IS 'Optional comment or details (e.g. source, reason for adjustment)';
