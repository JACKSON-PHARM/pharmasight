# Harte Pharmacy – Excel column map

Use this when importing the **Harte reports** style Excel (e.g. `harte reports.csv.xlsx`). The import recognises these headers automatically; you do **not** need to rename columns or use the column-mapping UI unless you want to override.

---

## Column map: Harte → PharmaSight

| # | Harte column (exact) | PharmaSight field | Notes |
|---|----------------------|-------------------|--------|
| 1 | **Description** | Item name | Product name. Required. Blank rows are skipped. No duplicates. |
| 2 | **pack size** | Pack size | Retail units per 1 wholesale (e.g. 20 = 1 pack has 20 units). Default 1 if empty. |
| 3 | **Brand** | Category | Free-text category (e.g. brand name). |
| 4 | **Category** | product_category | PHARMACY → PHARMACEUTICAL, COSMETICS → COSMETICS. |
| 5 | **Sub Category** | pricing_tier + product_category | SUPPLEMENTS→NUTRITION_SUPPLEMENTS, MOISTURIZER/LOTION/PERFUMES/etc→BEAUTY_COSMETICS, INSULIN INJ/VACCINE INJ→INJECTABLES, CONTROLLED/NON PHARM→STANDARD, ANTIDIABETICS/STATINS/etc→CHRONIC_MEDICATION. Many others mapped; see guide. |
| 6 | **Cost price** | Cost per base unit | Used for default cost / opening balance cost. |
| 7 | **Selling price** | Retail price | Sale price per retail unit. Map to “Retail Price / Sale Price” in UI if you want it stored. |
| 8 | **Wsale price** | Wholesale unit price | Price per wholesale unit (cost or selling). |
| 9 | **Quantity Available** | Current stock (opening balance) | Treated as **retail (base) units** when this is the only quantity column. Enter count in smallest unit (e.g. tablets, pieces). |
| 10 | Stock Value With C.P | — | Not imported (informational only). |
| 11 | Stock Value With Wsale.P | — | Not imported (informational only). |
| 12 | Stock Value With S.P | — | Not imported (informational only). |

**Unit names (not in Harte file):** Harte’s export does not include supplier/wholesale/retail **unit name** columns. PharmaSight supports them; use the **Download Template** from Items to get a sheet that includes:

- **Supplier_Unit** – e.g. carton, crate  
- **Wholesale_Unit** – e.g. box, bottle (base unit)  
- **Retail_Unit** – e.g. tablet, piece, ml  

Plus conversion columns: **Pack_Size** (retail per wholesale), **Wholesale_Units_per_Supplier**. After importing a Harte file, complete unit names and conversions in Items (per-item setup) so the item can be used in transactions.

---

## Summary

- **Use as-is:** Description, pack size, Brand, Category, Sub Category, Cost price, Selling price, Wsale price, Quantity Available.
- **Item name:** From **Description** (no mapping needed).
- **Item code:** Not in Harte file → PharmaSight **auto-generates** (e.g. A00001, A00002).
- **Stock:** **Quantity Available** = opening stock in **retail (base) units** (e.g. 43 = 43 units).
- **After import:** Each item has `setup_complete = false` until the user completes pack size/units in Items and saves; then that item can be used in sales, purchases, and GRN.

---

## Unit names and conversions (PharmaSight full template)

The **Download Template** from the Items page includes both **unit name** and **conversion** columns. Harte’s file only has **pack size** (one conversion); it does not have supplier/wholesale/retail unit names.

| PharmaSight column | Meaning | In Harte file? |
|--------------------|--------|-----------------|
| **Supplier_Unit** | Supplier unit name (e.g. carton, crate) | No |
| **Wholesale_Unit** | Wholesale unit name (e.g. box, bottle) | No |
| **Retail_Unit** | Retail unit name (e.g. tablet, piece) | No |
| **Pack_Size** | Retail per 1 wholesale | Yes → **pack size** |
| **Wholesale_Units_per_Supplier** | Wholesale units per 1 supplier | No |

So: we did **not** remove unit name columns. They are in the PharmaSight template and in the import column-mapping dropdown as “Supplier unit name”, “Wholesale unit name”, “Retail unit name”. Harte’s report simply doesn’t export them; complete them in the app after import (item setup).

---

## If you use the column-mapping UI

Optional mapping for full control:

| Map this (Harte) | To this (PharmaSight field) |
|------------------|-----------------------------|
| Description | item_name |
| pack size | pack_size |
| Brand | category |
| Category | (auto → product_category) |
| Sub Category | (auto → pricing_tier) |
| Cost price | purchase_price_per_supplier_unit or wholesale_unit_price |
| Selling price | retail_price_per_retail_unit |
| Wsale price | wholesale_price_per_wholesale_unit |
| Quantity Available | current_stock_quantity |

For unit names (if your file has them): map to **supplier_unit**, **wholesale_unit**, **retail_unit**.
