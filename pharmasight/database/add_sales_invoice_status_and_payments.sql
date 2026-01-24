-- Migration: Add DRAFT/BATCHED/PAID status flow to sales invoices
-- Add split payment support
-- Add item name/code to invoice items for display

-- =====================================================
-- 1. Add status fields to sales_invoices
-- =====================================================

-- Add status column (DRAFT, BATCHED, PAID, CANCELLED)
ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'DRAFT';

-- Add batching tracking fields
ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS batched BOOLEAN DEFAULT false;

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS batched_by UUID REFERENCES users(id);

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS batched_at TIMESTAMP;

-- Add cashier approval tracking (for PAID status)
ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS cashier_approved BOOLEAN DEFAULT false;

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id);

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;

-- Update existing invoices to have BATCHED status if they have items (they were already processed)
-- This maintains backward compatibility
UPDATE sales_invoices 
SET status = 'BATCHED', batched = true 
WHERE status IS NULL OR status = 'DRAFT'
AND EXISTS (
    SELECT 1 FROM sales_invoice_items 
    WHERE sales_invoice_items.sales_invoice_id = sales_invoices.id
);

-- Set existing invoices with payment_status = 'PAID' to status = 'PAID'
UPDATE sales_invoices 
SET status = 'PAID', cashier_approved = true
WHERE payment_status = 'PAID' AND (status IS NULL OR status = 'BATCHED');

-- =====================================================
-- 2. Add item name and code to sales_invoice_items
-- =====================================================

ALTER TABLE sales_invoice_items 
ADD COLUMN IF NOT EXISTS item_name VARCHAR(255);

ALTER TABLE sales_invoice_items 
ADD COLUMN IF NOT EXISTS item_code VARCHAR(100);

-- Populate item_name and item_code from items table for existing records
UPDATE sales_invoice_items sii
SET 
    item_name = i.name,
    item_code = COALESCE(i.sku, '')
FROM items i
WHERE sii.item_id = i.id 
AND (sii.item_name IS NULL OR sii.item_code IS NULL);

-- =====================================================
-- 3. Create invoice_payments table for split payments
-- =====================================================

CREATE TABLE IF NOT EXISTS invoice_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
    payment_mode VARCHAR(20) NOT NULL, -- 'cash', 'mpesa', 'card', 'credit', 'insurance'
    amount NUMERIC(15, 4) NOT NULL DEFAULT 0,
    payment_reference VARCHAR(100), -- M-Pesa code, transaction ID, etc.
    paid_by UUID REFERENCES users(id),
    paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(invoice_id, payment_mode, payment_reference)
);

CREATE INDEX IF NOT EXISTS idx_invoice_payments_invoice_id ON invoice_payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_paid_by ON invoice_payments(paid_by);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_paid_at ON invoice_payments(paid_at);

COMMENT ON TABLE invoice_payments IS 'Split payment tracking for sales invoices. Supports multiple payment modes per invoice.';
COMMENT ON COLUMN invoice_payments.payment_mode IS 'Payment method: cash, mpesa, card, credit, insurance';
COMMENT ON COLUMN invoice_payments.payment_reference IS 'Transaction reference (M-Pesa code, card transaction ID, etc.)';

-- =====================================================
-- 4. Add indexes for performance
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_sales_invoices_status ON sales_invoices(status);
CREATE INDEX IF NOT EXISTS idx_sales_invoices_batched ON sales_invoices(batched);
CREATE INDEX IF NOT EXISTS idx_sales_invoices_batched_by ON sales_invoices(batched_by);
CREATE INDEX IF NOT EXISTS idx_sales_invoices_approved_by ON sales_invoices(approved_by);

-- =====================================================
-- 5. Add customer_phone field for credit payment validation
-- =====================================================

ALTER TABLE sales_invoices 
ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);

COMMENT ON COLUMN sales_invoices.customer_phone IS 'Customer phone number (required for credit payment mode)';

-- =====================================================
-- 6. Comments for documentation
-- =====================================================

COMMENT ON COLUMN sales_invoices.status IS 'Document status: DRAFT (editable), BATCHED (committed, ready for payment), PAID (payment collected), CANCELLED';
COMMENT ON COLUMN sales_invoices.batched IS 'True when invoice has been committed and stock reduced';
COMMENT ON COLUMN sales_invoices.batched_by IS 'User who batched the invoice';
COMMENT ON COLUMN sales_invoices.batched_at IS 'Timestamp when invoice was batched';
COMMENT ON COLUMN sales_invoices.cashier_approved IS 'True when cashier has collected payment';
COMMENT ON COLUMN sales_invoices.approved_by IS 'Cashier who collected payment';
COMMENT ON COLUMN sales_invoices.approved_at IS 'Timestamp when payment was collected';

COMMENT ON COLUMN sales_invoice_items.item_name IS 'Cached item name for display (snapshot at time of sale)';
COMMENT ON COLUMN sales_invoice_items.item_code IS 'Cached item SKU/code for display (snapshot at time of sale)';
