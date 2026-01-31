-- Migration 005: Add missing columns to sales_invoices table
-- Fixes UndefinedColumn for tenants created from older schema (e.g. total_inclusive, sales_type).
-- Applied automatically to all tenant DBs on backend startup and to new tenants on provision.

-- total_inclusive: required by SalesInvoice model (KRA totals)
ALTER TABLE sales_invoices
ADD COLUMN IF NOT EXISTS total_inclusive NUMERIC(20,4) DEFAULT 0;

COMMENT ON COLUMN sales_invoices.total_inclusive IS 'Total amount including VAT (total_exclusive + vat_amount - discount_amount)';

-- sales_type: RETAIL vs WHOLESALE (pricing tier)
ALTER TABLE sales_invoices
ADD COLUMN IF NOT EXISTS sales_type VARCHAR(20) DEFAULT 'RETAIL';

COMMENT ON COLUMN sales_invoices.sales_type IS 'RETAIL (customers) or WHOLESALE (pharmacies). Determines pricing tier.';

-- Backfill total_inclusive for existing rows where it is 0 but total_exclusive/vat_amount exist
UPDATE sales_invoices
SET total_inclusive = COALESCE(total_exclusive, 0) + COALESCE(vat_amount, 0) - COALESCE(discount_amount, 0)
WHERE (total_inclusive IS NULL OR total_inclusive = 0)
  AND (total_exclusive IS NOT NULL OR vat_amount IS NOT NULL);
