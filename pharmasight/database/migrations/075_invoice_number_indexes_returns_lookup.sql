-- Migration 075: Indexes for targeted invoice lookup (returns/credit note flow)
-- Ensures invoice number and date-scoped queries stay fast as history grows.
-- Do not load full history; use today default + search by invoice_no / date range.

-- Sales: lookup by branch + invoice_no (and optional date)
CREATE INDEX IF NOT EXISTS idx_sales_invoices_invoice_no
ON sales_invoices(invoice_no);

-- Supplier invoices: lookup by branch + invoice_number (and optional date)
-- Table name is purchase_invoices (SupplierInvoice model)
CREATE INDEX IF NOT EXISTS idx_purchase_invoices_invoice_number
ON purchase_invoices(invoice_number);

COMMENT ON INDEX idx_sales_invoices_invoice_no IS 'Targeted lookup for returns flow; avoid full branch scan.';
COMMENT ON INDEX idx_purchase_invoices_invoice_number IS 'Targeted lookup for supplier credit note flow; avoid full branch scan.';
