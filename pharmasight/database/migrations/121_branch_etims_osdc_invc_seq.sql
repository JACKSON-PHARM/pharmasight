-- KRA saveTrnsSalesOsdc expects monotonic ``invcNo`` per OSCU branch (not PharmaSight ``invoice_no`` digits).

ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS kra_osdc_next_invc_no INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN branch_etims_credentials.kra_osdc_next_invc_no IS
    'Next OSDC saveTrnsSalesOsdc invcNo to send for this branch (KRA sequence). After resultCd 000, advance to last_used + 1. '
    'If another client filed OSDC sales for the same device, set this to match KRA before submitting from PharmaSight.';
