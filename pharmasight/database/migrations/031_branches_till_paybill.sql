-- Migration 031: Add till_number and paybill to branches (for sales invoice PDF footer)
-- Till and paybill are branch characteristics shown on sales invoice and quotation footers.

ALTER TABLE branches ADD COLUMN IF NOT EXISTS till_number VARCHAR(50) NULL;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS paybill VARCHAR(50) NULL;
