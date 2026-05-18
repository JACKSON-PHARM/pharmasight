-- Fix chart_of_accounts normal_balance check: CREDIT rows were rejected despite
-- pg_get_constraintdef showing DEBIT/CREDIT (corrupted conbin on some deployments).

ALTER TABLE chart_of_accounts DROP CONSTRAINT IF EXISTS chart_of_accounts_normal_balance_check;

ALTER TABLE chart_of_accounts
    ADD CONSTRAINT chart_of_accounts_normal_balance_check
    CHECK (normal_balance IN ('DEBIT', 'CREDIT'));
