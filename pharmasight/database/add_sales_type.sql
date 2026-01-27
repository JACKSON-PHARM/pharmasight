-- Add sales_type to sales_invoices to distinguish wholesale vs retail
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS sales_type VARCHAR(20) DEFAULT 'RETAIL';
COMMENT ON COLUMN sales_invoices.sales_type IS 'RETAIL (customers) or WHOLESALE (pharmacies). Determines which pricing tier to use.';
