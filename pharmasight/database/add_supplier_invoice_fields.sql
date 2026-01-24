-- Migration: Add payment tracking and status fields to supplier invoices
-- Also add batch_data field to invoice items

-- Add new fields to purchase_invoices table
ALTER TABLE purchase_invoices 
ADD COLUMN IF NOT EXISTS reference VARCHAR(255),
ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'DRAFT',
ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'UNPAID',
ADD COLUMN IF NOT EXISTS amount_paid NUMERIC(20,4) DEFAULT 0,
ADD COLUMN IF NOT EXISTS balance NUMERIC(20,4),
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

-- Update balance for existing invoices (set to total_inclusive - amount_paid)
UPDATE purchase_invoices 
SET balance = total_inclusive - COALESCE(amount_paid, 0)
WHERE balance IS NULL;

-- Add batch_data field to purchase_invoice_items
ALTER TABLE purchase_invoice_items
ADD COLUMN IF NOT EXISTS batch_data TEXT;

-- Create index on status for faster filtering
CREATE INDEX IF NOT EXISTS idx_purchase_invoices_status ON purchase_invoices(status);
CREATE INDEX IF NOT EXISTS idx_purchase_invoices_payment_status ON purchase_invoices(payment_status);

-- Add comments
COMMENT ON COLUMN purchase_invoices.status IS 'DRAFT (saved but not batched), BATCHED (stock added)';
COMMENT ON COLUMN purchase_invoices.payment_status IS 'UNPAID, PARTIAL, PAID';
COMMENT ON COLUMN purchase_invoices.amount_paid IS 'Amount paid to supplier';
COMMENT ON COLUMN purchase_invoices.balance IS 'Remaining balance (total_inclusive - amount_paid)';
COMMENT ON COLUMN purchase_invoice_items.batch_data IS 'JSON string storing batch distribution for this item';
