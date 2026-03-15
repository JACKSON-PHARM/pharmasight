-- Migration 074: Backfill inventory_ledger.document_number from document tables + index (Phase 1)
-- Runs after 073. Idempotent: only updates rows where document_number IS NULL.
-- Adds index for audit/reporting performance.

-- 1. sales_invoice -> sales_invoices.invoice_no
UPDATE inventory_ledger l
SET document_number = s.invoice_no
FROM sales_invoices s
WHERE l.reference_type = 'sales_invoice'
  AND l.reference_id = s.id
  AND l.document_number IS NULL;

-- 2. grn -> grns.grn_no
UPDATE inventory_ledger l
SET document_number = g.grn_no
FROM grns g
WHERE l.reference_type = 'grn'
  AND l.reference_id = g.id
  AND l.document_number IS NULL;

-- 3. purchase_invoice -> purchase_invoices.invoice_number (supplier invoice)
UPDATE inventory_ledger l
SET document_number = p.invoice_number
FROM purchase_invoices p
WHERE l.reference_type = 'purchase_invoice'
  AND l.reference_id = p.id
  AND l.document_number IS NULL;

-- 4. supplier_return -> convention (no doc number column on supplier_returns yet)
UPDATE inventory_ledger l
SET document_number = 'PR-' || UPPER(SUBSTRING(sr.id::TEXT, 1, 8))
FROM supplier_returns sr
WHERE l.reference_type = 'supplier_return'
  AND l.reference_id = sr.id
  AND l.document_number IS NULL;

-- 5. branch_transfer -> branch_transfers.transfer_number
UPDATE inventory_ledger l
SET document_number = COALESCE(bt.transfer_number, 'TRF-' || UPPER(SUBSTRING(bt.id::TEXT, 1, 8)))
FROM branch_transfers bt
WHERE l.reference_type = 'branch_transfer'
  AND l.reference_id = bt.id
  AND l.document_number IS NULL;

-- 6. branch_receipt -> branch_receipts.receipt_number
UPDATE inventory_ledger l
SET document_number = COALESCE(br.receipt_number, 'RCP-' || UPPER(SUBSTRING(br.id::TEXT, 1, 8)))
FROM branch_receipts br
WHERE l.reference_type = 'branch_receipt'
  AND l.reference_id = br.id
  AND l.document_number IS NULL;

-- 7. STOCK_TAKE -> stock_take_sessions.session_code
UPDATE inventory_ledger l
SET document_number = st.session_code
FROM stock_take_sessions st
WHERE l.reference_type = 'STOCK_TAKE'
  AND l.reference_id = st.id
  AND l.document_number IS NULL;

-- 8. MANUAL_ADJUSTMENT, BATCH_QUANTITY_CORRECTION, BATCH_METADATA_CORRECTION -> ADJ
UPDATE inventory_ledger
SET document_number = 'ADJ'
WHERE reference_type IN ('MANUAL_ADJUSTMENT', 'BATCH_QUANTITY_CORRECTION', 'BATCH_METADATA_CORRECTION')
  AND document_number IS NULL;

-- 9. OPENING_BALANCE -> OPEN
UPDATE inventory_ledger
SET document_number = 'OPEN'
WHERE reference_type = 'OPENING_BALANCE'
  AND document_number IS NULL;

-- 10. credit_note -> credit_notes.credit_note_no
UPDATE inventory_ledger l
SET document_number = c.credit_note_no
FROM credit_notes c
WHERE l.reference_type = 'credit_note'
  AND l.reference_id = c.id
  AND l.document_number IS NULL;

-- 11. Index for audit and reporting (branch_id, document_number)
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_doc_branch
ON inventory_ledger(branch_id, document_number);

COMMENT ON INDEX idx_inventory_ledger_doc_branch IS 'Audit and reporting: lookup by branch and document number.';

