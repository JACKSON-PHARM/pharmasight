# Fixing 422 Errors in Bulk Import

## Issues Identified

1. **422 Validation Errors**: The bulk import is failing with 422 (Unprocessable Content)
2. **Item Pricing Empty**: Items are not creating `item_pricing` records
3. **Tax/VAT Location**: User asked where tax columns are stored

## Solutions

### 1. 422 Errors - Validation Issue

The 422 errors occur because FastAPI validates the request body against the Pydantic schema BEFORE the function runs. This means the data structure from the frontend must match exactly.

**Common causes:**
- Missing required fields (`base_unit` is required)
- Wrong data types (UUIDs as strings instead of UUID objects - but FastAPI handles this)
- Extra fields that aren't in the schema

**Fix**: The frontend is sending data correctly, but we need to handle validation errors better.

### 2. Item Pricing Not Created

The `item_pricing` table is empty because:
- Items are created via bulk import
- The bulk import doesn't create `item_pricing` records
- Only the single item creation endpoint creates pricing records

**Solution**: Add item_pricing creation to bulk import (optional - can use company defaults)

### 3. Tax/VAT Storage Location

**Tax/VAT is stored in INVOICE LINE ITEMS, not in the items table:**

- `sales_invoice_items.vat_rate` (default 16%)
- `sales_invoice_items.vat_amount`
- `purchase_invoice_items.vat_rate` (default 16%)
- `purchase_invoice_items.vat_amount`
- `credit_note_items.vat_rate`
- `credit_note_items.vat_amount`

**Why?** Because:
- VAT rate can vary by transaction
- Different customers/suppliers might have different VAT rates
- Items themselves don't have VAT - transactions do

## Next Steps

1. Check backend logs for specific 422 validation errors
2. Add better error logging to see which fields fail validation
3. Optionally create item_pricing records during bulk import
4. Document that VAT is stored in invoice line items
