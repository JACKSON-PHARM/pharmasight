-- Migration 132: Third branch fiscal doctrine — wholesale distribution depot

ALTER TABLE branches DROP CONSTRAINT IF EXISTS branches_invoice_workflow_type_check;
ALTER TABLE branches ADD CONSTRAINT branches_invoice_workflow_type_check
    CHECK (invoice_workflow_type IN (
        'RETAIL_COUNTER',
        'ENCOUNTER_CONSOLIDATED',
        'WHOLESALE_DISTRIBUTION'
    ));

COMMENT ON COLUMN branches.invoice_workflow_type IS
    'Fiscal doctrine for this branch only. RETAIL_COUNTER: walk-in pharmacy. '
    'ENCOUNTER_CONSOLIDATED: clinic/hospital billing spine. '
    'WHOLESALE_DISTRIBUTION: B2B depot (batch/expiry, wholesale units, customer AR).';
