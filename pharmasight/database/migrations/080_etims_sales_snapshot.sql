-- Migration 080: eTIMS sales snapshot + branch credentials (no KRA HTTP; DB + batch preparation only).

-- sales_invoices: KRA response + submission tracking
ALTER TABLE sales_invoices
    ADD COLUMN IF NOT EXISTS kra_receipt_number VARCHAR(100),
    ADD COLUMN IF NOT EXISTS kra_signature TEXT,
    ADD COLUMN IF NOT EXISTS kra_qr_code TEXT,
    ADD COLUMN IF NOT EXISTS submission_status VARCHAR(30),
    ADD COLUMN IF NOT EXISTS kra_submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS kra_last_error TEXT;

COMMENT ON COLUMN sales_invoices.kra_receipt_number IS 'KRA eTIMS receipt/reference after successful submit';
COMMENT ON COLUMN sales_invoices.kra_signature IS 'KRA cryptographic signature / receipt signature payload';
COMMENT ON COLUMN sales_invoices.kra_qr_code IS 'QR payload or data string for compliant receipt printing';
COMMENT ON COLUMN sales_invoices.submission_status IS 'eTIMS: pending | succeeded | failed | skipped (NULL = legacy / not queued)';
COMMENT ON COLUMN sales_invoices.kra_submitted_at IS 'When invoice was successfully submitted to KRA';
COMMENT ON COLUMN sales_invoices.kra_last_error IS 'Last submission error message for operator review';

-- sales_invoice_items: frozen line snapshot for eTIMS at batch time
ALTER TABLE sales_invoice_items
    ADD COLUMN IF NOT EXISTS vat_cat_cd VARCHAR(20),
    ADD COLUMN IF NOT EXISTS tax_ty_cd VARCHAR(20),
    ADD COLUMN IF NOT EXISTS item_cls_cd VARCHAR(50),
    ADD COLUMN IF NOT EXISTS pkg_unit_cd VARCHAR(20),
    ADD COLUMN IF NOT EXISTS qty_unit_cd VARCHAR(20);

COMMENT ON COLUMN sales_invoice_items.vat_cat_cd IS 'eTIMS VAT category code (snapshot at batch)';
COMMENT ON COLUMN sales_invoice_items.tax_ty_cd IS 'eTIMS tax type code (snapshot at batch)';
COMMENT ON COLUMN sales_invoice_items.item_cls_cd IS 'eTIMS item classification (from item master when set)';
COMMENT ON COLUMN sales_invoice_items.pkg_unit_cd IS 'eTIMS package unit code (from item master when set)';
COMMENT ON COLUMN sales_invoice_items.qty_unit_cd IS 'eTIMS quantity unit code (from item master when set)';

-- items: optional KRA master data (sync later via saveItem)
ALTER TABLE items
    ADD COLUMN IF NOT EXISTS kra_item_cls_cd VARCHAR(50),
    ADD COLUMN IF NOT EXISTS kra_pkg_unit_cd VARCHAR(20),
    ADD COLUMN IF NOT EXISTS kra_qty_unit_cd VARCHAR(20),
    ADD COLUMN IF NOT EXISTS kra_tax_ty_cd VARCHAR(20);

COMMENT ON COLUMN items.kra_item_cls_cd IS 'KRA item classification code when synchronized';
COMMENT ON COLUMN items.kra_pkg_unit_cd IS 'KRA package unit code when synchronized';
COMMENT ON COLUMN items.kra_qty_unit_cd IS 'KRA quantity unit code when synchronized';
COMMENT ON COLUMN items.kra_tax_ty_cd IS 'KRA tax type override when synchronized';

-- branch_etims_credentials: OSCU device / branch binding (secrets at rest)
CREATE TABLE IF NOT EXISTS branch_etims_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kra_bhf_id VARCHAR(50),
    device_serial VARCHAR(100),
    cmc_key_encrypted TEXT,
    environment VARCHAR(20) NOT NULL DEFAULT 'sandbox',
    enabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_branch_etims_credentials_branch_id'
    ) THEN
        ALTER TABLE branch_etims_credentials
            ADD CONSTRAINT uq_branch_etims_credentials_branch_id UNIQUE (branch_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_branch_etims_credentials_company_id ON branch_etims_credentials(company_id);

COMMENT ON TABLE branch_etims_credentials IS 'Per-branch eTIMS OSCU credentials; company_id denormalized for tenant-scoped queries';
