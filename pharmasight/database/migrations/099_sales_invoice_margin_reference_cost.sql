-- Margin UI vs discounted inventory COGS: store list/reference cost per base unit on sale lines.
ALTER TABLE sales_invoice_items
ADD COLUMN IF NOT EXISTS margin_reference_unit_cost_base NUMERIC(20, 4);

COMMENT ON COLUMN sales_invoice_items.margin_reference_unit_cost_base IS
    'Pre-discount list / pricing-reference cost per base unit for margin display and min-margin checks; COGS remains in unit_cost_used after batch.';
