# Items Schema & Excel Import – Reference

## 1. Which Excel import service is the app using?

**The app uses `excel_import_service.py` only.**

- **Used:** `pharmasight/backend/app/services/excel_import_service.py`  
  - Imported in `pharmasight/backend/app/api/excel_import.py`:  
    `from app.services.excel_import_service import ExcelImportService`  
  - All import flows call `ExcelImportService.import_excel_data(...)` and other `ExcelImportService.*` methods.

- **Not used:** `pharmasight/backend/app/services/excel_import_service_optimized.py`  
  - Nothing in the app imports or references `OptimizedExcelImportService` or `excel_import_service_optimized`.  
  - It is an alternative implementation and is not wired into the API.

---

## 2. Items-related tables and how they are used

### 2.1 `public.items` (main item table)

**Role:** Single source of truth for product master data and 3-tier pricing.

**Holds:**
- Identity: `id`, `company_id`, `name`, `generic_name`, `sku`, `barcode`, `category`, `base_unit`
- Cost: `default_cost`, `purchase_price_per_supplier_unit`
- 3-tier sell prices: `wholesale_price_per_wholesale_unit`, `retail_price_per_retail_unit`
- Units: `supplier_unit`, `wholesale_unit`, `retail_unit`, `pack_size`, `can_break_bulk`
- VAT: `is_vatable`, `vat_rate`, `vat_code`, `vat_category`, `price_includes_vat`
- Other: `is_active`, `requires_batch_tracking`, `requires_expiry_tracking`, timestamps

**Who reads/writes:**
- **Items API** (`app/api/items.py`): CRUD, search, overview; reads/writes `Item` (and uses 3-tier price columns for search).
- **PricingService** (`app/services/pricing_service.py`): 3-tier prices and tier-specific prices come from **Item** (`get_3tier_pricing`, `get_price_for_tier`); recommended price uses cost + markup/rounding from `item_pricing` / company defaults.
- **Excel import** (`excel_import_service.py`): Creates/updates items; writes 3-tier prices and cost **on the Item model** (`purchase_price_per_supplier_unit`, `wholesale_price_per_wholesale_unit`, `retail_price_per_retail_unit`, `default_cost`).
- **Sales, quotations, purchases, order book, stock take, inventory**: All resolve item by `item_id` from `Item` and use item fields (name, units, VAT, etc.).

**Conclusion:** You do need the **items** table; it is the core table for products and 3-tier pricing.

---

### 2.2 `public.item_units` (unit conversions / breaking bulk)

**Role:** Defines how each item’s units convert to base (e.g. 1 box = 100 tablets).

**Holds:** `id`, `item_id`, `unit_name`, `multiplier_to_base`, `is_default`, timestamps.

**Who reads/writes:**
- **Items API:** Loads `Item.units` (e.g. `selectinload(Item.units)`), create/update item with units, bulk create.
- **Excel import:** `_process_item_units` creates/updates `ItemUnit` rows from Excel (unit name + conversion).
- **Transaction/line-item flows:**  
  - **Purchases API** (`app/api/purchases.py`): Validates line `unit_name` via `ItemUnit` for item.  
  - **Quotations API** (`app/api/quotations.py`): Same for quotation items and conversion to invoice.  
  - **Inventory API** (`app/api/inventory.py`): Uses `ItemUnit` for item IDs to build unit breakdowns.  
  - **TransactionItemsTable (frontend):** After selecting an item, loads units via `api.items.get(item_id)` and uses `item.units` for the unit dropdown.

**Conclusion:** You do need the **item_units** table for unit conversions and for validation in sales/purchases/quotations/inventory.

---

### 2.3 `public.item_pricing` (markup/rounding rules – legacy)

**Role:** Item-level **markup_percent**, **min_margin_percent**, **rounding_rule** used when a “recommended” price is computed from cost (e.g. cost × (1 + markup%), then rounding).  
**It does not store 3-tier prices;** those are on `items`.

**Holds:** `id`, `item_id` (unique), `markup_percent`, `min_margin_percent`, `rounding_rule`, timestamps.

**Who reads:**
- **PricingService:**  
  - `get_markup_percent(item_id, company_id)` → item_pricing then company_pricing_defaults.  
  - `get_rounding_rule(item_id, company_id)` → item_pricing then company_pricing_defaults.  
  - `calculate_recommended_price` uses these to compute a recommended sell price from cost.

**Who writes:**
- **Excel import:** In `_process_item_pricing` it:  
  - Writes **3-tier prices on the Item model** (main path).  
  - Optionally creates/updates **item_pricing** for “backward compatibility (markup calculation)” (e.g. `markup_percent` derived from retail vs cost).

**Conclusion:** You need **item_pricing** if you use recommended-price-from-cost (markup + rounding) anywhere. If you only ever use fixed 3-tier prices from `items`, you could eventually phase it out, but today PricingService still reads from it for markup/rounding.

---

## 3. Which tables do “items” and “transaction items” read from?

### Items API (`app/api/items.py`)

| Endpoint / behaviour        | Tables used                                      |
|----------------------------|--------------------------------------------------|
| CRUD (create/read/update)  | `items`; create/update also writes `item_units` |
| Search                     | `items` (+ optional: inventory_ledger, purchase/supplier/order for last cost/supplier) |
| Overview                   | `items`, `item_units` (eager), inventory_ledger, purchase invoices, suppliers; optionally PricingService (which uses `item_pricing` + company_pricing_defaults) for 3-tier display |
| Bulk create                | `items`, `item_units`                            |
| Recommended price         | Via PricingService → `items`, `item_pricing`, `company_pricing_defaults` |
| 3-tier / tier price        | Via PricingService → **Item** only (not item_pricing) |

So: **items** and **item_units** are the main tables; **item_pricing** is used only where recommended price (markup/rounding) is calculated.

### Transaction-item flows (sales, purchases, quotations, order book)

- **Item master data** (name, base_unit, VAT, etc.): from **`items`**.
- **Unit validation** (allowed units, conversions): from **`item_units`** (e.g. purchases, quotations, inventory).
- **Prices** on lines:  
  - Either from request (user/screen), or  
  - From PricingService (which uses **Item** for 3-tier and **item_pricing** + company defaults for recommended price).

So: **items** and **item_units** are what “items” and “transaction items” read from for master data and units; **item_pricing** is only for the recommended-price calculation path.

---

## 4. Short summary

| Question | Answer |
|----------|--------|
| Which Excel import service is used? | **`excel_import_service.py`**. `excel_import_service_optimized.py` is not used. |
| Do we need `items`? | **Yes.** Core table for products and 3-tier pricing. |
| Do we need `item_units`? | **Yes.** Required for unit conversions and validation in transactions. |
| Do we need `item_pricing`? | **Yes for now.** Used by PricingService for markup/rounding when calculating recommended price; 3-tier prices themselves live on `items`. |
| Where do items API and transaction items read from? | **`items`** for master data and 3-tier prices; **`item_units`** for units; **`item_pricing`** only for markup/rounding in recommended price. |

---

## 5. Clearing company data for a fresh Excel re-import

To drop all items, inventory, purchases, sales, and related data for a company so you can import an Excel sheet afresh, use the script:

- **Script:** `pharmasight/backend/scripts/clear_company_for_reimport.py`
- **Usage (from repo root):**
  ```bash
  cd pharmasight/backend
  python scripts/clear_company_for_reimport.py <company_id> [--yes]
  ```
- **Dry-run (no deletes):**
  ```bash
  python scripts/clear_company_for_reimport.py <company_id> --dry-run
  ```

It deletes (in FK-safe order): import jobs, inventory ledger, stock take data, order book, GRNs, purchase invoices/orders, payments, credit notes, sales invoices, quotations, items (and item_units, item_pricing), suppliers. It does **not** delete companies, branches, or users. Requires `DATABASE_URL` or Supabase tenant DB env vars.
