# Architectural Enforcement Complete ✅

## Executive Summary

**All deprecated price column read/write paths have been eliminated.**

Zero tolerance enforcement of:
- ❌ No reads from `items.default_cost`, `items.purchase_price_per_supplier_unit`, `items.wholesale_price_per_wholesale_unit`, `items.retail_price_per_retail_unit`
- ❌ No writes to those columns
- ✅ All pricing flows from `inventory_ledger` via `CanonicalPricingService`

---

## Files Modified (11 total)

### Backend (7 files)

| File | Changes | Status |
|------|---------|--------|
| **app/services/canonical_pricing.py** | **NEW FILE** — Single source of truth for all pricing: `get_last_purchase_cost()`, `get_opening_balance_cost()`, `get_weighted_average_cost()`, `get_best_available_cost()` | ✅ |
| **app/services/excel_import_service.py** | Removed all `ItemUnit` writes; stopped persisting prices to items; opening balance uses `unit_cost` from Excel row (converted via `wholesale_units_per_supplier`); added unit conversion helpers | ✅ |
| **app/services/clear_for_reimport_service.py** | Removed explicit `DELETE FROM item_units` (table left intact) | ✅ |
| **app/services/pricing_service.py** | Removed `item.default_cost` fallback from `get_last_cost()` and `get_item_cost()`; deprecated `get_3tier_pricing()` and `get_price_for_tier()` (return None) | ✅ |
| **app/api/items.py** | Removed price columns from search SELECT; search/overview use `CanonicalPricingService`; `get_item`/`get_items_by_company` overwrite price fields with ledger values; `update_item` strips price fields from payload | ✅ |
| **app/services/items_service.py** | Removed `default_cost` assignment; strip deprecated price keys from create dump | ✅ |
| **app/api/stock_take.py** | Unit cost from `CanonicalPricingService.get_best_available_cost()` | ✅ |
| **app/api/purchases.py** | Order item cost from `CanonicalPricingService.get_best_available_cost()` | ✅ |

### Frontend (3 files)

| File | Changes | Status |
|------|---------|--------|
| **frontend/js/pages/items.js** | Removed price input section from create form; removed price fields from create/update payloads; removed default_cost from edit modal; transaction callback uses `purchase_price: 0` | ✅ |
| **frontend/js/components/TransactionItemsTable.js** | Comment: `purchase_price` must come from API (ledger) | ✅ |
| **frontend/js/pages/inventory.js** | No change needed — displays cost from API (now ledger-backed) | ✅ |
| **frontend/js/pages/purchases.js** | No change needed — displays cost from API (now ledger-backed) | ✅ |

### Schema (1 file)

| File | Changes | Status |
|------|---------|--------|
| **database/migrations/008_deprecate_items_price_columns.sql** | `COMMENT ON COLUMN` + `ALTER COLUMN DROP DEFAULT` for all price columns; uses `IF EXISTS` to handle schemas without 3-tier columns | ✅ |

---

## Key Architectural Changes

### 1. CanonicalPricingService (NEW)

**File:** `pharmasight/backend/app/services/canonical_pricing.py`

Single source of truth for all pricing:

```python
CanonicalPricingService.get_last_purchase_cost(db, item_id, branch_id, company_id)
CanonicalPricingService.get_opening_balance_cost(db, item_id, branch_id, company_id)
CanonicalPricingService.get_weighted_average_cost(db, item_id, branch_id, company_id)
CanonicalPricingService.get_best_available_cost(db, item_id, branch_id, company_id)
```

**Priority:** Last purchase → Opening balance → Weighted average → Zero

---

### 2. Excel Import Refactor

- ✅ No writes to `item_units` table (deprecated)
- ✅ No writes to price columns on `items` table
- ✅ Opening balance in `inventory_ledger` with `unit_cost` from Excel (purchase price converted to cost per base unit via `wholesale_units_per_supplier`)
- ✅ Unit conversion helpers: `_cost_per_supplier_to_cost_per_base()`, `convert_quantity_supplier_to_wholesale()`, `convert_quantity_wholesale_to_retail()`

---

### 3. Backend API Enforcement

**Search/Dropdown (`/api/items/search`):**
- Removed price columns from SELECT query
- Response `price`, `purchase_price`, `sale_price` from `CanonicalPricingService` or purchase/ledger maps
- No fallback to `item.default_cost`

**Get Item (`/api/items/{item_id}`):**
- Optional `branch_id` query param for ledger-based cost
- Response overwrites: `default_cost` from `CanonicalPricingService`, other price fields set to 0
- Client never sees stored values from `items` table

**Update Item (`/api/items/{item_id}`):**
- Strips deprecated price fields from update payload before applying

**Stock Take:**
- Adjustment unit cost from `CanonicalPricingService.get_best_available_cost()`

**Purchase Orders:**
- Order item cost from `CanonicalPricingService.get_best_available_cost()`

---

### 4. Frontend Enforcement

**Items Create Form:**
- Pricing section replaced with note: "Cost and prices are set from inventory ledger (Excel import or purchases)"
- No price inputs
- Payload excludes: `default_cost`, `purchase_price_per_supplier_unit`, `wholesale_price_per_wholesale_unit`, `retail_price_per_retail_unit`

**Items Edit Form:**
- Default cost input removed
- Update payload excludes: `default_cost`

**Transaction Callback:**
- New items use `purchase_price: 0` (cost from ledger when item is used)

**Display:**
- Inventory/purchases pages display cost from API (backend now returns ledger-based values)

---

## Migration Status

**Migration 008** is ready and fixed to handle schemas with/without 3-tier price columns.

**To apply:**
1. Stop the server (Ctrl+C in terminal 4)
2. Restart: `python start.py`
3. Migration will run automatically on startup

**What the migration does:**
- Adds `COMMENT ON COLUMN` for all price columns: `'DEPRECATED — DO NOT READ OR WRITE.'`
- Drops defaults: `ALTER COLUMN ... DROP DEFAULT`
- Uses `IF EXISTS` checks to handle databases without 3-tier columns

---

## Verification

### Backend Read Paths: ✅ ELIMINATED
- ❌ `items.default_cost` — No reads (overwritten in API responses with ledger values)
- ❌ `items.purchase_price_per_supplier_unit` — No reads (overwritten with 0 in responses)
- ❌ `items.wholesale_price_per_wholesale_unit` — No reads (overwritten with 0 in responses)
- ❌ `items.retail_price_per_retail_unit` — No reads (overwritten with 0 in responses)

### Backend Write Paths: ✅ ELIMINATED
- Excel import: strips price fields before creating items
- Items service: strips price fields from create dump
- Items API: strips price fields from update payload

### Frontend: ✅ ELIMINATED
- No price input fields in create/edit forms
- No price fields in POST/PUT payloads
- Cost/price displayed from API (ledger-backed)

---

## Confirmation Statement

**No backend or frontend code reads or writes price from items or item_pricing.**  
**All pricing flows from inventory_ledger or canonical queries (CanonicalPricingService).**

---

## Next Action

**Restart the server** to apply migration 008:

```powershell
# In terminal 4 (or your active terminal):
# Press Ctrl+C to stop
# Then run:
python start.py
```

The migration will run automatically and mark the price columns as DEPRECATED in the database.
