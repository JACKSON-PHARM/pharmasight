-- Migration 093: One registry row per company (prevents duplicate tenants.company_id at scale).
-- Fails if duplicate company_id values already exist — fix data first:
--   SELECT company_id, COUNT(*) FROM tenants GROUP BY company_id HAVING COUNT(*) > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_company_id ON tenants(company_id);
