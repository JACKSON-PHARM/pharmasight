-- Branch-scoped fiscal doctrine: retail counter vs encounter-consolidated governance.
-- Default preserves existing pharmacy-first behavior for all current branches.

ALTER TABLE branches
    ADD COLUMN IF NOT EXISTS invoice_workflow_type VARCHAR(40) NOT NULL DEFAULT 'RETAIL_COUNTER';

ALTER TABLE branches DROP CONSTRAINT IF EXISTS branches_invoice_workflow_type_check;
ALTER TABLE branches ADD CONSTRAINT branches_invoice_workflow_type_check
    CHECK (invoice_workflow_type IN ('RETAIL_COUNTER', 'ENCOUNTER_CONSOLIDATED'));

COMMENT ON COLUMN branches.invoice_workflow_type IS
    'Fiscal authority doctrine for this branch only. RETAIL_COUNTER: pharmacy owns invoice/KRA lifecycle. ENCOUNTER_CONSOLIDATED: centralized billing governance (enforcement phased in).';
