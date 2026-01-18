# VAT Classification Implementation - Complete ✅

## Overview

Implemented item-level VAT classification for Kenya pharmacy context where VAT classification is an **intrinsic property of items**, not something decided at transaction time.

**Key Principle:** Most medicines are zero-rated (0%), some items/services are standard-rated (16%). This rarely changes per transaction.

## Changes Made

### 1. Database Schema ✅
- **File:** `pharmasight/database/schema.sql`
- Added to `items` table:
  - `is_vatable BOOLEAN DEFAULT TRUE`
  - `vat_rate NUMERIC(5,2) DEFAULT 0` (0 for zero-rated, 16 for standard-rated)
  - `vat_code VARCHAR(50)` (ZERO_RATED | STANDARD | EXEMPT)
  - `price_includes_vat BOOLEAN DEFAULT FALSE`

### 2. SQLAlchemy Models ✅
- **File:** `pharmasight/backend/app/models/item.py`
- Added VAT fields to `Item` model

### 3. Pydantic Schemas ✅
- **File:** `pharmasight/backend/app/schemas/item.py`
- Added VAT fields to:
  - `ItemBase` (inherited by ItemCreate, ItemResponse)
  - `ItemUpdate`

### 4. Bulk Import ✅
- **File:** `pharmasight/frontend/js/pages/items.js`
- Maps Excel columns to VAT fields:
  - `Price_List_Tax_Percentage` → `vat_rate`
  - `Price_List_Tax_Code` → `vat_code`
  - `Price_List_Price_Inclusive` → `price_includes_vat`
- Automatically infers `vat_code` from `vat_rate` if not provided:
  - 0% → ZERO_RATED
  - 16% → STANDARD
  - Otherwise → null

### 5. Sales Invoice Creation ✅
- **File:** `pharmasight/backend/app/api/sales.py`
- **Before:** Hardcoded `vat_rate = Decimal("16.00")`
- **After:** Copies VAT from item: `item.vat_rate`
- Invoice header VAT rate is calculated as weighted average (informational)
- Line items use item's VAT rate (preserves historical accuracy)

### 6. Purchase Invoice Creation ✅
- **File:** `pharmasight/backend/app/api/purchases.py`
- Schema already supports per-item VAT rates
- Uses VAT from request (which should come from items in frontend)

### 7. Migration SQL ✅
- **File:** `pharmasight/database/add_vat_fields_to_items.sql`
- Adds VAT columns to existing `items` table
- Sets default VAT for existing items (zero-rated)

## Database Migration Required

**For existing databases, run:**

```sql
-- Run this SQL file:
pharmasight/database/add_vat_fields_to_items.sql
```

Or manually:

```sql
ALTER TABLE items
ADD COLUMN IF NOT EXISTS is_vatable BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS vat_code VARCHAR(50),
ADD COLUMN IF NOT EXISTS price_includes_vat BOOLEAN DEFAULT FALSE;

-- Set default VAT for existing items (most medicines are zero-rated in Kenya)
UPDATE items 
SET 
    vat_rate = 0, 
    vat_code = 'ZERO_RATED',
    is_vatable = TRUE,
    price_includes_vat = FALSE
WHERE vat_rate IS NULL OR vat_code IS NULL;
```

## Default Values

- `is_vatable`: `TRUE` (EXEMPT items are not vatable)
- `vat_rate`: `0` (zero-rated medicines)
- `vat_code`: `ZERO_RATED` (for zero-rated items)
- `price_includes_vat`: `FALSE`

## Excel Template Mapping

The bulk import now maps these Excel columns:

| Excel Column | Item Field | Notes |
|-------------|------------|-------|
| `Price_List_Tax_Percentage` | `vat_rate` | 0 or 16 typically |
| `Price_List_Tax_Code` | `vat_code` | ZERO_RATED, STANDARD, EXEMPT |
| `Price_List_Price_Inclusive` | `price_includes_vat` | Boolean |

## Transaction Behavior

### Sales Invoices
1. System reads `item.vat_rate` for each line item
2. Copies VAT data to invoice line item
3. Calculates `vat_amount` using item's VAT rate
4. Invoice header shows weighted average VAT rate (informational)
5. Historical accuracy: If item VAT changes later, old invoices retain original VAT

### Purchase Invoices
1. Frontend should populate VAT from items
2. System uses VAT from request (per line item)
3. Preserves supplier's VAT classification

## Compliance Notes

✅ **Items can exist without transactions**  
✅ **Items retain VAT classification independently**  
✅ **Bulk import reflects CSV VAT settings exactly**  
✅ **Transactions compute VAT using copied item values**  
✅ **No hardcoded 16% default - uses item's VAT rate**  
✅ **Zero-rated medicines default to 0%, not 16%**

## Testing Checklist

- [ ] Run migration SQL on database
- [ ] Test bulk import with Excel file containing VAT fields
- [ ] Verify items are created with correct VAT classification
- [ ] Test sales invoice creation - verify VAT copied from items
- [ ] Test purchase invoice creation - verify VAT from items
- [ ] Verify zero-rated items show 0% VAT, not 16%

## Next Steps

1. **Run database migration** on existing database
2. **Restart backend** to load new code
3. **Test bulk import** with Excel file
4. **Verify VAT** in created items and invoices

---

**Implementation Date:** 2026-01-12  
**Context:** Kenya Pharmacy ERP - VAT Classification as Item Property
