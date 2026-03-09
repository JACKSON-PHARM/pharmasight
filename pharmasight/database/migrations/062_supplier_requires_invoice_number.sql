-- 062_supplier_requires_invoice_number.sql
-- Adds per-supplier toggle to require external supplier invoice number on invoices.

ALTER TABLE suppliers
    ADD COLUMN IF NOT EXISTS requires_supplier_invoice_number BOOLEAN NOT NULL DEFAULT FALSE;

