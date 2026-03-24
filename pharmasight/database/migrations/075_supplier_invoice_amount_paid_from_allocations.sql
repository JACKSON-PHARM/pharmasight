-- Single source of truth: supplier_payment_allocations.
-- Recompute denormalized amount_paid / balance / payment_status on purchase_invoices.

UPDATE purchase_invoices pi
SET amount_paid = COALESCE((
    SELECT SUM(spa.allocated_amount)
    FROM supplier_payment_allocations spa
    WHERE spa.supplier_invoice_id = pi.id
), 0);

UPDATE purchase_invoices pi
SET balance = GREATEST(
    0::numeric,
    COALESCE(pi.total_inclusive, 0) - COALESCE(pi.amount_paid, 0)
);

UPDATE purchase_invoices pi
SET payment_status = CASE
    WHEN COALESCE(pi.total_inclusive, 0) <= 0 THEN
        CASE WHEN COALESCE(pi.amount_paid, 0) > 0 THEN 'PAID' ELSE 'UNPAID' END
    WHEN COALESCE(pi.amount_paid, 0) <= 0 THEN 'UNPAID'
    WHEN COALESCE(pi.amount_paid, 0) >= COALESCE(pi.total_inclusive, 0) THEN 'PAID'
    ELSE 'PARTIAL'
END;

COMMENT ON COLUMN purchase_invoices.amount_paid IS 'Denormalized SUM(supplier_payment_allocations.allocated_amount); synced by application';
