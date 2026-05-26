ALTER TABLE purchase_invoice_items
    ADD COLUMN IF NOT EXISTS discount_percent NUMERIC(5, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS bonus_quantity NUMERIC(20, 4) NOT NULL DEFAULT 0;

COMMENT ON COLUMN purchase_invoice_items.discount_percent IS
    'Supplier line discount percent. Unit cost remains gross/original; payable totals are net after discount.';

COMMENT ON COLUMN purchase_invoice_items.bonus_quantity IS
    'Free/bonus quantity in the same purchase unit. Excluded from supplier payable totals, included in received stock when batched.';

UPDATE purchase_invoice_items
SET discount_percent = LEAST(
        100,
        GREATEST(
            0,
            ((unit_cost_exclusive * quantity) - line_total_exclusive) * 100 / NULLIF(unit_cost_exclusive * quantity, 0)
        )
    )
WHERE COALESCE(discount_percent, 0) = 0
  AND COALESCE(unit_cost_exclusive, 0) > 0
  AND COALESCE(quantity, 0) > 0
  AND line_total_exclusive < (unit_cost_exclusive * quantity);
