-- Phase 1: Reversal document axes (posting vs KRA sync), audit metadata,
-- supplier return SR-{branch}-{seq} numbering (deprecates PR-{uuid8} on ledger),
-- optional supplier return line lineage UUIDs (no FKs — future allocation / GRN linkage).

-- ---------------------------------------------------------------------------
-- credit_notes: two-axis status + audit (no workflow change in app yet)
-- ---------------------------------------------------------------------------
ALTER TABLE credit_notes
    ADD COLUMN IF NOT EXISTS posting_status VARCHAR(32) NOT NULL DEFAULT 'posted',
    ADD COLUMN IF NOT EXISTS kra_sync_status VARCHAR(32) NOT NULL DEFAULT 'not_started',
    ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64),
    ADD COLUMN IF NOT EXISTS user_agent TEXT,
    ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64);

UPDATE credit_notes SET posting_status = 'posted' WHERE posting_status IS NULL OR posting_status = '';
UPDATE credit_notes SET kra_sync_status = 'not_started' WHERE kra_sync_status IS NULL OR kra_sync_status = '';

ALTER TABLE credit_notes DROP CONSTRAINT IF EXISTS credit_notes_posting_status_check;
ALTER TABLE credit_notes ADD CONSTRAINT credit_notes_posting_status_check
    CHECK (posting_status IN ('draft', 'submitted', 'posted', 'cancelled'));

ALTER TABLE credit_notes DROP CONSTRAINT IF EXISTS credit_notes_kra_sync_status_check;
ALTER TABLE credit_notes ADD CONSTRAINT credit_notes_kra_sync_status_check
    CHECK (kra_sync_status IN ('not_required', 'not_started', 'pending', 'retrying', 'synced', 'failed', 'partially_synced'));

COMMENT ON COLUMN credit_notes.posting_status IS 'Business posting lifecycle. posted = inventory ledger rows for this document were successfully committed (system invariant). Independent of kra_sync_status.';
COMMENT ON COLUMN credit_notes.kra_sync_status IS 'KRA fiscal/async sync (actionable states only). Stock I/O is separate; not_started until fiscal reversal pipeline exists.';

-- ---------------------------------------------------------------------------
-- supplier_returns: document number, two-axis status, audit
-- ---------------------------------------------------------------------------
ALTER TABLE supplier_returns
    ADD COLUMN IF NOT EXISTS return_document_no VARCHAR(100),
    ADD COLUMN IF NOT EXISTS posting_status VARCHAR(32) NOT NULL DEFAULT 'not_posted',
    ADD COLUMN IF NOT EXISTS kra_sync_status VARCHAR(32) NOT NULL DEFAULT 'not_required',
    ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS client_ip VARCHAR(64),
    ADD COLUMN IF NOT EXISTS user_agent TEXT,
    ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64);

UPDATE supplier_returns SET posting_status = CASE status
    WHEN 'pending' THEN 'not_posted'
    WHEN 'credited' THEN 'posted'
    WHEN 'approved' THEN 'posted'
    WHEN 'rejected' THEN 'cancelled'
    ELSE 'not_posted'
END;

UPDATE supplier_returns SET kra_sync_status = 'not_required' WHERE kra_sync_status IS NULL OR kra_sync_status = '';

ALTER TABLE supplier_returns DROP CONSTRAINT IF EXISTS supplier_returns_posting_status_check;
ALTER TABLE supplier_returns ADD CONSTRAINT supplier_returns_posting_status_check
    CHECK (posting_status IN ('not_posted', 'posted', 'cancelled'));

ALTER TABLE supplier_returns DROP CONSTRAINT IF EXISTS supplier_returns_kra_sync_status_check;
ALTER TABLE supplier_returns ADD CONSTRAINT supplier_returns_kra_sync_status_check
    CHECK (kra_sync_status IN ('not_required', 'not_started', 'pending', 'retrying', 'synced', 'failed', 'partially_synced'));

COMMENT ON COLUMN supplier_returns.return_document_no IS 'Fiscal-style SR-{branch}-{seq}; assigned when return is posted (approved).';
COMMENT ON COLUMN supplier_returns.posting_status IS 'Stock/financial posting state. posted = PURCHASE_RETURN ledger rows committed for this return (invariant). Legacy status column remains for compatibility.';
COMMENT ON COLUMN supplier_returns.kra_sync_status IS 'KRA fiscal/async sync for supplier returns (actionable states). not_required when no KRA path applies.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_supplier_returns_company_branch_return_doc_no
    ON supplier_returns (company_id, branch_id, return_document_no)
    WHERE return_document_no IS NOT NULL;

-- ---------------------------------------------------------------------------
-- supplier_return_lines: optional lineage (no FKs in Phase 1)
-- ---------------------------------------------------------------------------
ALTER TABLE supplier_return_lines
    ADD COLUMN IF NOT EXISTS source_purchase_invoice_item_id UUID,
    ADD COLUMN IF NOT EXISTS source_grn_item_id UUID,
    ADD COLUMN IF NOT EXISTS source_inventory_ledger_id UUID;

COMMENT ON COLUMN supplier_return_lines.source_purchase_invoice_item_id IS 'Optional lineage to purchase invoice line; FK may be added in a later phase.';
COMMENT ON COLUMN supplier_return_lines.source_grn_item_id IS 'Optional lineage to GRN line; FK may be added in a later phase.';
COMMENT ON COLUMN supplier_return_lines.source_inventory_ledger_id IS 'Optional lineage to originating stock ledger row; FK may be added in a later phase.';

-- ---------------------------------------------------------------------------
-- Backfill SR numbers for already-posted (credited) supplier returns
-- ---------------------------------------------------------------------------
WITH branch_doc_code AS (
    SELECT
        b.id AS branch_id,
        (
            CASE
                WHEN NULLIF(TRIM(b.code), '') IS NULL THEN '01'
                WHEN LENGTH(TRIM(b.code)) >= 2 THEN SUBSTRING(TRIM(b.code) FROM 1 FOR 2)
                WHEN TRIM(b.code) ~ '^[0-9]$' THEN LPAD(TRIM(b.code), 2, '0')
                ELSE RPAD(SUBSTRING(TRIM(b.code) FROM 1 FOR 1), 2, '0')
            END
        ) AS doc_code
    FROM branches b
),
numbered AS (
    SELECT
        sr.id,
        'SR-' || bdc.doc_code || '-' || LPAD(
            ROW_NUMBER() OVER (PARTITION BY sr.branch_id ORDER BY sr.created_at, sr.id)::TEXT,
            6,
            '0'
        ) AS new_doc_no
    FROM supplier_returns sr
    JOIN branch_doc_code bdc ON bdc.branch_id = sr.branch_id
    WHERE sr.status = 'credited'
      AND (sr.return_document_no IS NULL OR TRIM(sr.return_document_no) = '')
)
UPDATE supplier_returns sr
SET return_document_no = n.new_doc_no
FROM numbered n
WHERE sr.id = n.id;

UPDATE inventory_ledger l
SET document_number = sr.return_document_no
FROM supplier_returns sr
WHERE l.reference_type = 'supplier_return'
  AND l.reference_id = sr.id
  AND sr.return_document_no IS NOT NULL
  AND (l.document_number IS DISTINCT FROM sr.return_document_no);

-- Seed document_sequences for SR so the next app-generated SR does not collide.
INSERT INTO document_sequences (id, company_id, branch_id, document_type, prefix, current_number, year)
SELECT
    uuid_generate_v4(),
    mx.company_id,
    mx.branch_id,
    'SR',
    NULL,
    mx.mx_seq,
    NULL
FROM (
    SELECT
        company_id,
        branch_id,
        GREATEST(
            0,
            MAX(
                CAST(
                    NULLIF(TRIM(SPLIT_PART(return_document_no, '-', 3)), '') AS INTEGER
                )
            )
        ) AS mx_seq
    FROM supplier_returns
    WHERE return_document_no IS NOT NULL
      AND return_document_no ~ '^SR-.+-[0-9]{6}$'
    GROUP BY company_id, branch_id
) mx
WHERE NOT EXISTS (
    SELECT 1
    FROM document_sequences ds
    WHERE ds.company_id = mx.company_id
      AND ds.branch_id = mx.branch_id
      AND ds.document_type = 'SR'
      AND ds.year IS NULL
);

UPDATE document_sequences ds
SET
    current_number = GREATEST(COALESCE(ds.current_number, 0), mx.mx_seq),
    updated_at = CURRENT_TIMESTAMP
FROM (
    SELECT
        company_id,
        branch_id,
        GREATEST(
            0,
            MAX(
                CAST(
                    NULLIF(TRIM(SPLIT_PART(return_document_no, '-', 3)), '') AS INTEGER
                )
            )
        ) AS mx_seq
    FROM supplier_returns
    WHERE return_document_no IS NOT NULL
      AND return_document_no ~ '^SR-.+-[0-9]{6}$'
    GROUP BY company_id, branch_id
) mx
WHERE ds.company_id = mx.company_id
  AND ds.branch_id = mx.branch_id
  AND ds.document_type = 'SR'
  AND ds.year IS NULL;
