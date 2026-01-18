# VAT Classification Migration Guide

## Database Migration Required

After updating the schema, you need to add the new VAT columns to the existing `items` table:

```sql
-- Add VAT classification columns to items table
ALTER TABLE items
ADD COLUMN IF NOT EXISTS is_vatable BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS vat_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS price_includes_vat BOOLEAN DEFAULT FALSE;

-- Set default VAT for existing items (most medicines are zero-rated in Kenya)
-- Update this based on your actual data classification
UPDATE items SET vat_rate = 0, vat_code = 'ZERO_RATED' WHERE vat_rate IS NULL OR vat_rate = 0;
```

## Notes

- Default `vat_rate` is 0 (zero-rated) for Kenya pharmacy context
- Default `is_vatable` is TRUE (can be zero-rated but still vatable)
- `vat_code` should be: ZERO_RATED | STANDARD | EXEMPT
- `price_includes_vat` defaults to FALSE
