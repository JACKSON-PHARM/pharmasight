# Price Deprecation Enforcement — Progress Tracker

## Completed ✅

### Phase 1: Foundation
- ✅ **REFACTOR_ITEM_UNITS_DEPRECATION.md** — Documented item_units deprecation
- ✅ **PRICE_DEPRECATION_ENFORCEMENT.md** — Comprehensive enforcement audit
- ✅ **canonical_pricing.py** — Created centralized pricing service (NEW FILE)
- ✅ **excel_import_service.py** — Removed all item_units writes; prices from row → ledger only
- ✅ **clear_for_reimport_service.py** — Stopped writing to item_units

### Phase 2: Backend Core Services
- ✅ **pricing_service.py** — Removed `item.default_cost` fallback from `get_last_cost()` and `get_item_cost()`
- ✅ **pricing_service.py** — Deprecated `get_3tier_pricing()` (returns None)
- ✅ **pricing_service.py** — Deprecated `get_price_for_tier()` (returns None)

### Phase 3: Backend API & Services
- ✅ **items.py** — Removed price columns from search SELECT; pricing from CanonicalPricingService; get_item/get_items_by_company overwrite price fields; update_item strips price fields
- ✅ **items_service.py** — Removed default_cost assignment; strip deprecated price keys from create dump
- ✅ **stock_take.py** — Unit cost from CanonicalPricingService.get_best_available_cost
- ✅ **purchases.py** — Order item default_cost from CanonicalPricingService.get_best_available_cost

### Phase 4: Frontend
- ✅ **items.js** — Removed price input section from create form; removed price fields from create/update payloads; removed default_cost from edit modal and update payload; transaction callback uses purchase_price 0 (ledger when used)
- ✅ **inventory.js** — Cost display uses API (search/overview now return ledger cost)
- ✅ **purchases.js** — Cost display uses API (order item default_cost now from ledger)
- ✅ **TransactionItemsTable.js** — Comment: purchase_price must come from API (ledger)

### Phase 5: Schema Lockdown
- ✅ **migrations/008_deprecate_items_price_columns.sql** — COMMENT ON COLUMN + ALTER COLUMN DROP DEFAULT for all four price columns

---

## Confirmation Statement

**No backend or frontend code reads or writes price from items or item_pricing.  
All pricing flows from inventory_ledger or canonical queries (CanonicalPricingService).**

---

### Schema Lockdown (FINAL STEP) — DONE

#### schema.sql
**File:** `pharmasight/database/schema.sql`
```sql
-- Add DEPRECATED comments
COMMENT ON COLUMN items.default_cost IS 'DEPRECATED — DO NOT READ OR WRITE. Use inventory_ledger.';
COMMENT ON COLUMN items.purchase_price_per_supplier_unit IS 'DEPRECATED — DO NOT READ OR WRITE. Use inventory_ledger.';
COMMENT ON COLUMN items.wholesale_price_per_wholesale_unit IS 'DEPRECATED — DO NOT READ OR WRITE. Price from external config.';
COMMENT ON COLUMN items.retail_price_per_retail_unit IS 'DEPRECATED — DO NOT READ OR WRITE. Price from external config.';

-- Drop defaults to prevent accidental writes
ALTER TABLE items ALTER COLUMN default_cost DROP DEFAULT;
ALTER TABLE items ALTER COLUMN purchase_price_per_supplier_unit DROP DEFAULT;
ALTER TABLE items ALTER COLUMN wholesale_price_per_wholesale_unit DROP DEFAULT;
ALTER TABLE items ALTER COLUMN retail_price_per_retail_unit DROP DEFAULT;

-- Make nullable (optional, for extra safety)
ALTER TABLE items ALTER COLUMN default_cost DROP NOT NULL;
ALTER TABLE items ALTER COLUMN purchase_price_per_supplier_unit DROP NOT NULL;
ALTER TABLE items ALTER COLUMN wholesale_price_per_wholesale_unit DROP NOT NULL;
ALTER TABLE items ALTER COLUMN retail_price_per_retail_unit DROP NOT NULL;
```

---

## Enforcement Checklist

### Backend
- [x] CanonicalPricingService created
- [x] pricing_service.py: Removed item table fallbacks (get_last_cost, get_item_cost, get_3tier_pricing, get_price_for_tier)
- [x] items.py: Removed price columns from search SELECT; pricing from CanonicalPricingService; get_item/get_items_by_company overwrite; update_item strips price fields
- [x] items_service.py: Remove default_cost assignment; strip deprecated keys from create dump
- [x] stock_take.py: Unit cost from CanonicalPricingService.get_best_available_cost
- [x] purchases.py: Order item default_cost from CanonicalPricingService.get_best_available_cost

### Frontend
- [x] items.js: Removed price input section; removed price fields from POST/PUT; removed default_cost from edit
- [x] inventory.js: Cost from API (ledger)
- [x] purchases.js: Cost from API (ledger)
- [x] TransactionItemsTable.js: purchase_price from API (ledger) — comment added

### Schema
- [x] Migration 008: COMMENT ON COLUMN + ALTER COLUMN DROP DEFAULT for all four price columns

---

## Confirmation Statement

**CURRENT STATUS:** ✅ COMPLETE

**Statement:**
> No backend or frontend code reads or writes price from items or item_pricing.  
> All pricing flows from inventory_ledger or canonical queries (CanonicalPricingService).  
> Schema columns are marked DEPRECATED via migration 008 (COMMENT + DROP DEFAULT).
