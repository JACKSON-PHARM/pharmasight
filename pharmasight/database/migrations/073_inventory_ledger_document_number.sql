-- Migration 073: Add document_number to inventory_ledger (Unified Transaction Engine - Phase 1)
-- The ledger must be self-describing for auditability and reporting performance.
-- reference_type and reference_id are retained; document_number stores the human-readable
-- document number at the time the ledger entry is created.
-- Column is nullable for legacy rows until backfill (074) and for optional adjustment types.

ALTER TABLE inventory_ledger ADD COLUMN IF NOT EXISTS document_number VARCHAR(100);

COMMENT ON COLUMN inventory_ledger.document_number IS 'Human-readable document number at time of write (e.g. INV-01-000245, CN-01-000014). Denormalized for audit and reporting.';
