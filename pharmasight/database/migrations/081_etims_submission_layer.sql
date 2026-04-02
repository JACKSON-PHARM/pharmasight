-- Migration 081: eTIMS OAuth fields per branch + audit log for OSCU submissions.

ALTER TABLE branch_etims_credentials
    ADD COLUMN IF NOT EXISTS kra_oauth_username VARCHAR(255),
    ADD COLUMN IF NOT EXISTS kra_oauth_password TEXT;

COMMENT ON COLUMN branch_etims_credentials.kra_oauth_username IS 'KRA eTIMS OAuth client id / username for /oauth2/v1/generate (optional if using app-level env)';
COMMENT ON COLUMN branch_etims_credentials.kra_oauth_password IS 'KRA eTIMS OAuth client secret / password (store securely; encryption at rest is operator responsibility)';

CREATE TABLE IF NOT EXISTS etims_submission_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sales_invoice_id UUID REFERENCES sales_invoices(id) ON DELETE SET NULL,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    request_payload_hash VARCHAR(64),
    response_status VARCHAR(40),
    http_status INT,
    error_message TEXT,
    response_body TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_etims_submission_log_invoice ON etims_submission_log(sales_invoice_id);
CREATE INDEX IF NOT EXISTS idx_etims_submission_log_company_created ON etims_submission_log(company_id, created_at DESC);

COMMENT ON TABLE etims_submission_log IS 'Audit trail for KRA eTIMS OSCU invoice submissions (payload hash + response)';
