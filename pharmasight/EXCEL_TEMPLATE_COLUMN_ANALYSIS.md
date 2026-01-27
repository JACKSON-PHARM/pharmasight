# Excel Template Column Analysis - 3-Tier System

## Excel Template: `pharmasight_template_fixed_20260126_143121.xlsx`
**Total Rows**: 9,713 items
**Total Columns**: 42

---

## ✅ COLUMNS WE USE (3-Tier System)

### Core Item Fields
1. **Item name*** → `item.name` ✅ REQUIRED
2. **Item code** → `item.sku` ✅ USED
3. **Description** → `item.generic_name` ✅ USED
4. **Category** → `item.category` ✅ USED

### 3-Tier UNIT System (CRITICAL)
5. **Supplier_Unit** → `item.supplier_unit` ✅ USED
6. **Wholesale_Unit** → `item.wholesale_unit` ✅ USED
7. **Retail_Unit** → `item.retail_unit` ✅ USED
8. **Pack_Size** → `item.pack_size` ✅ USED
9. **Can_Break_Bulk** → `item.can_break_bulk` ✅ USED

### Unit Conversion (Legacy Support)
10. **Base Unit (x)** → `item.base_unit` (legacy, also set from retail_unit) ✅ USED
11. **Secondary Unit (y)** → Creates `item_units` entry ✅ USED
12. **Conversion Rate (n) (x = ny)** → `item_units.multiplier_to_base` ✅ USED

### 3-Tier PRICING (on items table)
13. **Purchase_Price_per_Supplier_Unit** → `item.purchase_price_per_supplier_unit` ✅ USED
14. **Wholesale_Price_per_Wholesale_Unit** → `item.wholesale_price_per_wholesale_unit` ✅ USED
15. **Retail_Price_per_Retail_Unit** → `item.retail_price_per_retail_unit` ✅ USED
16. **Sale price** → Fallback for `retail_price_per_retail_unit` ✅ USED (fallback)

### VAT Classification
18. **VAT_Category** → `item.vat_category` ✅ USED
19. **VAT_Rate** → `item.vat_rate` ✅ USED

### Supplier
21. **Supplier** → Creates/links `supplier` record ✅ USED

### Stock
34. **Current stock quantity** → Creates `inventory_ledger` opening balance ✅ USED

### Fallback/Alternative Column Names (for compatibility)
25. **Price_List_Last_Cost** → Fallback for `purchase_price_per_supplier_unit` ✅ USED
27. **Price_List_Retail_Price** → Fallback for `retail_price_per_retail_unit` ✅ USED
28. **Price_List_Wholesale_Price** → Fallback for `wholesale_price_per_wholesale_unit` ✅ USED
30. **Price_List_Retail_Unit_Price** → Fallback for `retail_price_per_retail_unit` ✅ USED
31. **Price_List_Wholesale_Unit_Price** → Fallback for `wholesale_price_per_wholesale_unit` ✅ USED
39. **Purchase price** → Fallback for `purchase_price_per_supplier_unit` ✅ USED

---

## ❌ COLUMNS WE DON'T USE (and why)

### Online Store (Not Implemented)
17. **Online Store Price** → ❌ NOT USED - No online store feature

### Legacy Price List Fields (Redundant with 3-tier)
23. **Supplier_Last_Cost** → ❌ NOT USED - We use `Purchase_Price_per_Supplier_Unit`
24. **Price_List_Pack_Size** → ❌ NOT USED - We use `Pack_Size`
26. **Price_List_Average_Cost** → ❌ NOT USED - We calculate from FEFO batches
29. **Price_List_Trade_Price** → ❌ NOT USED - We use wholesale_price
32. **Price_List_Tax_Percentage** → ❌ NOT USED - We use `VAT_Rate`
33. **Price_List_Tax_Code** → ❌ NOT USED - We use `VAT_Category`

### Supplier Details (Not Stored on Item)
22. **Supplier_Item_Code** → ❌ NOT USED - Not in item model

### VAT Description (Redundant)
20. **VAT_Description** → ❌ NOT USED - We use `VAT_Category` (ZERO_RATED/STANDARD_RATED)

### Stock Management (Not Implemented)
35. **Minimum stock quantity** → ❌ NOT USED - No reorder point system yet

### Price Matching (Not Implemented)
36. **Price_List_Match_Type** → ❌ NOT USED - No price matching feature
37. **Price_Attribution_Source** → ❌ NOT USED - No price source tracking

### Tax/Discount (Handled Differently)
40. **Sale Discount** → ❌ NOT USED - Discounts applied at invoice level, not item level
41. **Tax Rate** → ❌ NOT USED - We use `VAT_Rate`
42. **Inclusive Of Tax** → ❌ NOT USED - We use `price_includes_vat` (but not from Excel)

### HSN Code (Not Implemented)
38. **HSN** → ❌ NOT USED - HSN code not in item model

---

## Summary

**Used**: 20 columns (core 3-tier system + fallbacks + stock)
**Unused**: 22 columns (legacy price list fields, online store, HSN, discounts, etc.)

**Why unused columns exist**: 
- Legacy compatibility with old price list systems
- Future features (online store, HSN codes, minimum stock)
- Alternative column names for flexibility
- Tax/discount handled at invoice level, not item level

---

## Import Process

1. **Run migration**: `add_3tier_units.sql`
2. **Clean up old data**: `cleanup_items_for_fresh_import.sql` (if needed)
3. **Import Excel**: System will read all 3-tier columns and create items properly
