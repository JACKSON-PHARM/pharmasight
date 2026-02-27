-- Multi-company readiness: remove one-company-per-DB enforcement.
-- RLS and app-level company_id (from JWT) now provide company isolation.
-- Run after RLS policies are in place if you use RLS; otherwise run when consolidating to single DB.

-- Drop trigger that prevented inserting more than one company
DROP TRIGGER IF EXISTS check_single_company ON companies;

-- Drop legacy helper and trigger function
DROP FUNCTION IF EXISTS enforce_single_company() CASCADE;
DROP FUNCTION IF EXISTS get_company_id() CASCADE;
