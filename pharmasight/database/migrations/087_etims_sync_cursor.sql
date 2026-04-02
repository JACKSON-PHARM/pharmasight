-- eTIMS OSCU incremental sync cursor (lastReqDt) per branch + data category
--
-- OSCU spec v2.0 requires TIS to persist the last successful retrieval date-time (CHAR(14))
-- for each type of "Get" data, and send it as lastReqDt on the next request.
--
-- This table is tenant-scoped via company_id and branch_id (single DB, multi-company).

CREATE TABLE IF NOT EXISTS etims_sync_cursor (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    category VARCHAR(60) NOT NULL,
    last_req_dt CHAR(14) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One cursor per (branch, category)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_etims_sync_cursor_branch_category'
    ) THEN
        ALTER TABLE etims_sync_cursor
            ADD CONSTRAINT uq_etims_sync_cursor_branch_category UNIQUE (branch_id, category);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_etims_sync_cursor_company ON etims_sync_cursor(company_id);
CREATE INDEX IF NOT EXISTS idx_etims_sync_cursor_branch ON etims_sync_cursor(branch_id);

COMMENT ON TABLE etims_sync_cursor IS 'Per-branch OSCU lastReqDt cursor for incremental data retrieval (codes/items/imports/purchases/stock/etc.)';
COMMENT ON COLUMN etims_sync_cursor.category IS 'Logical OSCU data category (e.g. selectCodeList, itemInfo, getPurchaseTransactionInfo)';
COMMENT ON COLUMN etims_sync_cursor.last_req_dt IS 'Last successful request date-time (YYYYMMDDHHMMSS) used as next lastReqDt';

