# Excel Import & Items Default Parameters – Plan (No Code Yet)

## 1. Excel Sheet Analysis (`pharmacy_enhanced_template_20260203_105425.xlsx`)

### 1.1 Column structure (first sheet)

| Excel column | Type / sample | Maps to app |
|-------------|----------------|-------------|
| **Item name*** | string (required) | `items.name` |
| Item code | string / NaN | `items.sku` |
| Description | string | `items.description` |
| Category | string | `items.category` |
| **Retail_Unit** | e.g. piece, capsule | `items.retail_unit` (label) |
| **Wholesale_Unit** | e.g. packet, box | `items.wholesale_unit` (label) = **base** |
| **Supplier_Unit** | e.g. box, case | `items.supplier_unit` (label) |
| **Pack_Size** | int (e.g. 1, 100) | `items.pack_size` (retail per wholesale) |
| **Wholesale_Units_per_Supplier** | int (e.g. 50, 6) | `items.wholesale_units_per_supplier` |
| Can_Break_Bulk | bool | `items.can_break_bulk` |
| Base_Unit | string (e.g. piece) | Display label; app uses `base_unit = wholesale_unit` |
| **Retail_Conversion_Formula** | "Wholesale_Units × Pack_Size" | Confirms: **retail = wholesale × pack_size** |
| **Supplier_Conversion_Formula** | "Wholesale_Units ÷ Wholesale_Units_per_Supplier" | Confirms: **supplier qty = wholesale ÷ wholesale_units_per_supplier** |
| Is_Controlled, Is_Cold_Chain, Track_Expiry | bool | `items.*` |
| VAT_Category, VAT_Rate | string, float | `items.vat_category`, `items.vat_rate` |
| Purchase_Price_per_Supplier_Unit | float | Used for opening balance cost (convert to cost per wholesale) |
| Wholesale_Price_per_Wholesale_Unit | float | Alternative for cost per wholesale unit |
| Retail_Price_per_Retail_Unit | float | Sale price per retail unit |
| Sale price, Online Store Price | float | Optional sale prices |
| **Supplier** | string or NaN (pandas may give float) | Create/link supplier; **default supplier** candidate |
| Supplier_Item_Code | - | Optional |
| **Current stock quantity** | int | Opening balance quantity (base = wholesale units) |
| Minimum stock quantity | int | Future: min_stock on item or branch |
| _PL_*, HSN, "Base Unit (x)", "Secondary Unit (y)", "Conversion Rate (n) (x = ny)" | legacy / internal | Ignore or map "Conversion Rate (n)" → pack_size if needed |

### 1.2 Conversion semantics (Excel vs app)

- **Wholesale = default/base unit** (stock and cost are in wholesale units).
- **Retail:** 1 wholesale unit = **Pack_Size** retail units → `retail_qty = wholesale_qty × pack_size`.
- **Supplier:** 1 supplier unit = **Wholesale_Units_per_Supplier** wholesale units → `wholesale_qty = supplier_qty × wholesale_units_per_supplier` (so supplier_qty = wholesale_qty ÷ wholesale_units_per_supplier).

The current `items` table already matches this: `pack_size` = retail per wholesale, `wholesale_units_per_supplier` = wholesale per supplier. No schema change needed for conversion logic; only **column name / source** handling in import (see below).

### 1.3 Why app import might be failing

- **Header names:** Excel has `Item name*` (with asterisk). The service already accepts `Item name*` in `item_name_fields`; validation should pass.
- **Empty/NaN:** Columns like `Supplier` or `Item code` can be NaN (float). Code that does `str(NaN)` or doesn’t treat `float('nan')` as empty can break (e.g. supplier name lookup, SKU).
- **Numeric "Supplier":** If pandas reads empty Supplier as NaN, the column dtype can be float; any logic assuming string (e.g. supplier name) can fail.
- **Frontend:** File upload, sheet choice, or column mapping might send wrong sheet or wrong structure; need to confirm what the UI sends (form data, mapping, sync vs async).

So the plan should include: **robust NaN/empty handling** in the import service and, for dev, a **standalone script** that reads the Excel file directly and uses the same conversion rules.

---

## 2. Items table: default parameters (when no ledger history)

### 2.1 Goal

- **Today:** Last cost and last supplier are derived only from **inventory_ledger** and **purchase invoices** (e.g. `CanonicalPricingService.get_best_available_cost`, last purchase supplier).
- **Change:** For items with **no** inventory_ledger (and optionally no purchase) records, allow **default** values so the UI and PO flows can show a suggested cost and supplier (e.g. from Excel or manual entry).

These defaults are **fallbacks only** when there is no transaction history. Once there is any ledger/purchase data, the app keeps using ledger/invoice as source of truth.

### 2.2 Proposed new columns on `items` (additive only)

| Column | Type | Nullable | Purpose |
|--------|------|----------|---------|
| `default_cost_per_base` | `NUMERIC(20,4)` | YES | Default cost per base (wholesale) unit. Used only when no ledger record exists for that item (e.g. new item from Excel). |
| `default_supplier_id` | `UUID` FK → `suppliers.id` | YES | Default supplier. Used only when no purchase history (e.g. "last supplier" from Excel or manual). |

- **Naming:** `default_*` to make it clear these are fallbacks, not the live “last cost” or “last supplier” from transactions.
- **Usage in API:** When computing “cost” or “last supplier” for an item:
  - If the item has at least one relevant ledger (or purchase) record → use existing logic (ledger / invoice).
  - If the item has **no** ledger/purchase history → use `default_cost_per_base` and `default_supplier_id` for display/suggestions only.

No removal of existing columns; no change to ledger or invoice logic. This is **additive** and backward compatible.

### 2.3 Migration strategy (high level)

1. **Migration script:** `ALTER TABLE items ADD COLUMN default_cost_per_base NUMERIC(20,4) NULL`, and `ADD COLUMN default_supplier_id UUID NULL REFERENCES suppliers(id)`. Add index on `default_supplier_id` if we ever filter by it.
2. **Backend:**  
   - In `CanonicalPricingService` (or wherever “best available cost” is computed): if no ledger/purchase cost found for the item, return `item.default_cost_per_base` (if not null) instead of 0 or None, when desired.  
   - In items API (e.g. list/detail, PO context): when deriving “last supplier”, if no purchase history, use `item.default_supplier_id` → supplier name for display.
3. **Excel import (app + dev script):** When creating/updating an item from Excel, set `default_cost_per_base` from Wholesale_Price_per_Wholesale_Unit (or from Purchase_Price_per_Supplier_Unit converted to per-wholesale). Set `default_supplier_id` from the “Supplier” column (find-or-create supplier, then set FK). These defaults are then used until the item gets real purchases/ledger entries.
4. **Frontend:** No breaking change; existing “last cost” / “last supplier” fields can start showing these defaults when there is no history.

---

## 3. Standalone dev script (load Excel directly into DB)

### 3.1 Purpose

- Bypass the app (no HTTP, no auth, no tenant routing).
- Read `pharmacy_enhanced_template_20260203_105425.xlsx` (or a path passed as argument).
- Use the **same** conversion rules: wholesale = base, retail = wholesale × pack_size, supplier = wholesale ÷ wholesale_units_per_supplier.
- Insert/update **items**, **suppliers**, **item_pricing**, and **inventory_ledger** (opening balances) for a given **company_id**, **branch_id**, **user_id** (e.g. from env or CLI).
- Development-only: documented as such, not part of production deploy path.

### 3.2 Suggested behaviour

1. **Config:** Company ID, branch ID, user ID (and DB URL) from env vars or CLI (e.g. `--company-id`, `--branch-id`, `--user-id`, `--db-url`). Optional `--file` for Excel path.
2. **Read Excel:** First sheet, pandas; normalize headers (spaces/asterisk) so “Item name*” → item name, “Current stock quantity” → current_stock_quantity, etc.
3. **NaN/empty:** Treat NaN and empty string as missing; do not pass float NaN to DB or string "nan" to supplier name / SKU.
4. **Suppliers:** For each distinct non-empty Supplier name, find-or-create in `suppliers`; store `supplier_id` for that row.
5. **Items:** For each row, find item by (company_id, name) or create; set all existing item columns plus `default_cost_per_base` and `default_supplier_id` from this row (cost from Wholesale_Price_per_Wholesale_Unit or converted from Purchase_Price_per_Supplier_Unit; supplier from find-or-create).
6. **Units:** No change to 3-tier model: wholesale_unit = base, pack_size, wholesale_units_per_supplier as today.
7. **Opening balance:** For each item, if “Current stock quantity” > 0, create one OPENING_BALANCE ledger row (quantity_delta in base units, unit_cost from default cost or converted purchase price).
8. **Idempotency:** Same as app: by item name; update if exists and (optionally) if no real transactions; otherwise skip or update only non-structural + defaults.
9. **Logging:** Print progress (e.g. rows processed, items created/updated, opening balances created) and any errors.

### 3.3 Placement

- e.g. `pharmasight/scripts/load_items_from_excel_dev.py` or `pharmasight/backend/scripts/load_items_from_excel_dev.py`, with a short README in `docs/` or in the script docstring stating “development only”.

---

## 4. App Excel import fixes (to make “load from app” work)

These are the changes that will make the **in-app** upload work with the enhanced template, without changing the items table structure (that’s covered in §2).

1. **Column name mapping:** Ensure all enhanced-template headers are accepted:
   - `Item name*` → already supported.
   - `Retail_Unit`, `Wholesale_Unit`, `Supplier_Unit`, `Pack_Size`, `Wholesale_Units_per_Supplier` → already in service.
   - `Retail_Conversion_Formula` / `Supplier_Conversion_Formula` → ignore (informational only).
   - `Current stock quantity` (with space) → already in normalize list.
   - `Wholesale_Price_per_Wholesale_Unit`, `Purchase_Price_per_Supplier_Unit` → already used.
2. **NaN/empty handling:** In the import service, wherever row values are read (item name, SKU, barcode, supplier name, codes, prices, quantities):
   - Coerce pandas NaN to None or empty string before any DB or string operation.
   - Treat `float('nan')` and string `"nan"` as missing.
3. **Supplier column:** If the column is numeric (NaN for empty), use a safe getter (e.g. only use value if it’s a non-empty string or valid number that we intentionally map to a name). Prefer: “if value is not None and not (isinstance(value, float) and math.isnan(value)) and str(value).strip()”.
4. **Optional:** If the frontend sends column mapping, ensure “Item name*” and “Current stock quantity” etc. are mappable; document the expected system field ids for the enhanced template.

After these, the same conversion semantics (wholesale = base, retail = wholesale × pack_size, supplier from wholesale_units_per_supplier) already match the Excel; no change to that logic beyond using the right columns and NaN handling.

---

## 5. Transition order (no breaking changes)

1. **Phase 1 – Fix current import**
   - Add NaN/empty handling and column mapping for the enhanced template in the Excel import service.
   - Verify in-app upload with `pharmacy_enhanced_template_20260203_105425.xlsx` (create/update items, opening balances, suppliers). No new columns yet.

2. **Phase 2 – Default parameters on items**
   - Add migration for `default_cost_per_base` and `default_supplier_id` on `items`.
   - Update Excel import (app + dev script) to set these from Excel when creating/updating items.
   - Update “best cost” and “last supplier” logic to use these defaults only when the item has no ledger/purchase history. Keep ledger/invoice as source of truth when history exists.

3. **Phase 3 – Dev script**
   - Implement standalone script that reads the Excel file, applies same conversion rules and NaN handling, and writes to items/suppliers/ledger (and default_* when Phase 2 is in). Document as dev-only.

4. **Phase 4 – Optional**
   - Minimum stock: if we want “Minimum stock quantity” from Excel, add `minimum_stock` (or similar) to items/branch and wire it in a later change.

---

## 6. Summary

| Topic | Conclusion |
|-------|------------|
| **Excel conversion** | Wholesale = default; retail = wholesale × Pack_Size; supplier = wholesale ÷ Wholesale_Units_per_Supplier. Current schema already supports this. |
| **Items table change** | Add `default_cost_per_base`, `default_supplier_id`; use only when no ledger/purchase history. Additive, non-breaking. |
| **Standalone dev script** | New script: read Excel, normalize headers/NaN, find-or-create suppliers/items, write opening balances and default_*; same conversion rules; dev-only. |
| **Why app import fails** | Likely NaN/empty handling and/or “Supplier” as float; plus confirm frontend sends correct file and mapping. |
| **Order** | Fix import (NaN + columns) → add default columns + migration → use defaults in API when no history → add dev script; document. |

---

## 7. Implementation status (Phases 1–3 done)

- **Phase 1:** Excel import fixed: API coerces NaN to None when parsing Excel; service accepts `Wholesale_Price_per_Wholesale_Unit` and enhanced template columns.
- **Phase 2:** Migration `010_items_default_cost_and_supplier.sql` adds `default_cost_per_base` and `default_supplier_id` on `items`. Item model, CanonicalPricingService (fallback cost), and items API (fallback last_supplier) updated. Excel import (authoritative, non-destructive, bulk) sets default cost and default supplier when creating/updating items.
- **Phase 3:** Standalone dev script `pharmasight/backend/scripts/load_items_from_excel_dev.py` reads Excel, coerces NaN, and calls `ExcelImportService.import_excel_data(..., force_mode='AUTHORITATIVE')` for development-only loading.

**Run migration before using defaults:**  
`psql ... -f pharmasight/database/migrations/010_items_default_cost_and_supplier.sql`

---

## 8. Troubleshooting: Import runs but tables stay empty

**Symptom:** Progress shows (e.g. 500/9707) but the Items table (or Inventory) shows no rows.

**Causes and fixes:**

1. **Wrong database (tenant vs default)**  
   Import writes to the database for the current context (tenant if you opened the app via a tenant link, otherwise default). The Items list uses the same context. If you imported with a tenant link but then view without it (or the opposite), you are looking at a different database.  
   **Fix:** In the Import Excel modal, check **Import target**. Open the app from the same link (tenant or default) when viewing items.

2. **Background import failed without clearing progress**  
   If the worker hits an error (e.g. missing `item_pricing` table, or tenant DB unreachable), it marks the job as `failed` and sets `error_message`. If you see "Processing 500/9707" and it never completes, the job may be stuck from a previous run.  
   **Fix:** Use **Run import synchronously** (checkbox in the Import modal, on by default). The request will block until the import finishes and any error will appear in the UI. For a fresh start, use **Clear for re-import** (when you have no live transactions), then import again with sync on.

3. **Same file hash – reusing an old job**  
   Uploading the same file again can return "Import already in progress" and show progress for the previous job.  
   **Fix:** If you need a new run, clear for re-import first, or use a different file. The toast will say "Same file is already importing" when this happens.

4. **Reload items afresh after partial or failed import**  
   If the import timed out or was partial and you want to start over:  
   - On the **Items** page, click **Clear for re-import** (only allowed when the company has no live sales/purchases/stock movements beyond opening balance).  
   - Then run **Excel Import** again with your file. Sync import timeout is 90 minutes for large sheets; keep the tab open until it completes.
