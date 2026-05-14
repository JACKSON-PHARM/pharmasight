-- Persist per-branch saveItem response details so operators can confirm KRA acceptance.

ALTER TABLE item_branch_kra_sync
  ADD COLUMN IF NOT EXISTS http_status INTEGER NULL;

ALTER TABLE item_branch_kra_sync
  ADD COLUMN IF NOT EXISTS kra_result_cd TEXT NULL;

ALTER TABLE item_branch_kra_sync
  ADD COLUMN IF NOT EXISTS kra_result_msg TEXT NULL;

ALTER TABLE item_branch_kra_sync
  ADD COLUMN IF NOT EXISTS response_payload_json JSONB NULL;

COMMENT ON COLUMN item_branch_kra_sync.http_status IS 'Last HTTP status returned by KRA saveItem for this branch.';
COMMENT ON COLUMN item_branch_kra_sync.kra_result_cd IS 'Last parsed KRA result code (e.g. 000 accepted).';
COMMENT ON COLUMN item_branch_kra_sync.kra_result_msg IS 'Last parsed KRA result message/description.';
COMMENT ON COLUMN item_branch_kra_sync.response_payload_json IS 'Last raw response payload body from KRA saveItem (when JSON).';
