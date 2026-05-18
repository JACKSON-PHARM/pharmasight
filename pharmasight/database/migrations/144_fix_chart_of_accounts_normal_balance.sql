-- Migration 144: Fix chart_of_accounts.normal_balance width / check (CREDIT was rejected when column was too narrow).

ALTER TABLE chart_of_accounts
    ALTER COLUMN normal_balance TYPE VARCHAR(10);

ALTER TABLE chart_of_accounts
    DROP CONSTRAINT IF EXISTS chart_of_accounts_normal_balance_check;

ALTER TABLE chart_of_accounts
    ADD CONSTRAINT chart_of_accounts_normal_balance_check
    CHECK (normal_balance IN ('DEBIT', 'CREIT'));
