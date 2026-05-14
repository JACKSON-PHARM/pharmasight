-- OSCU stock ledger: SAR sequence per branch device + mirrored KRA rsdQty per item/branch (for retries/resume).

ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS kra_last_stock_io_sar_no INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN branch_etims_credentials.kra_last_stock_io_sar_no IS
    'Last insertStockIO sarNo that returned resultCd 000 for this branch OSCU (monotonic KRA sequence).';

ALTER TABLE item_branch_kra_sync
    ADD COLUMN IF NOT EXISTS kra_stock_rsd_qty NUMERIC(20, 4) NULL;

ALTER TABLE item_branch_kra_sync
    ADD COLUMN IF NOT EXISTS kra_stock_mirror_updated_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN item_branch_kra_sync.kra_stock_rsd_qty IS
    'Last rsdQty successfully posted to KRA via saveStockMaster for this item at this branch (mirror).';

COMMENT ON COLUMN item_branch_kra_sync.kra_stock_mirror_updated_at IS
    'When kra_stock_rsd_qty was last confirmed from KRA stock master.';
