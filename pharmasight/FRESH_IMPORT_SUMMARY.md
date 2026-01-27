# Fresh 3-Tier Import - Complete Summary

## ✅ Excel Template Analysis Results

**File**: `pharmasight_template_fixed_20260126_143121.xlsx`  
**Rows**: 9,713 items  
**Total Columns**: 42

### Column Usage
- **Used**: 26 columns (61.9%)
- **Unused**: 16 columns (38.1%)
- **Status**: ✅ All critical 3-tier columns are present!

---

## 📋 Complete Process

### 1. Run Migration
```bash
psql -U your_user -d pharmasight -f database/add_3tier_units.sql
```
**What it does**: Adds 3-tier columns to `items` table

### 2. Clean Up Old Data (Optional)
```bash
psql -U your_user -d pharmasight -f database/cleanup_items_for_fresh_import.sql
```
**What it does**: Deletes all items, units, pricing, opening balances

**⚠️ WARNING**: Only run if you want to start completely fresh!

### 3. Import Excel
1. Open PharmaSight frontend
2. Go to **Items** page
3. Click **"Import Excel"**
4. Select the Excel file
5. Wait for import (9,713 items)

---

## 📊 Used Columns (26)

### Core Item Fields
1. `Item name*` → `item.name` (required)
2. `Item code` → `item.sku`
3. `Description` → `item.generic_name`
4. `Category` → `item.category`

### 3-Tier Unit System (CRITICAL)
5. `Supplier_Unit` → `item.supplier_unit`
6. `Wholesale_Unit` → `item.wholesale_unit`
7. `Retail_Unit` → `item.retail_unit`
8. `Pack_Size` → `item.pack_size`
9. `Can_Break_Bulk` → `item.can_break_bulk`

### Unit Conversion
10. `Base Unit (x)` → `item.base_unit`
11. `Secondary Unit (y)` → `item_units.unit_name`
12. `Conversion Rate (n) (x = ny)` → `item_units.multiplier_to_base`

### 3-Tier Pricing (CRITICAL)
13. `Purchase_Price_per_Supplier_Unit` → `item.purchase_price_per_supplier_unit`
14. `Wholesale_Price_per_Wholesale_Unit` → `item.wholesale_price_per_wholesale_unit`
15. `Retail_Price_per_Retail_Unit` → `item.retail_price_per_retail_unit`
16. `Sale price` → Fallback for retail price

### VAT
17. `VAT_Category` → `item.vat_category`
18. `VAT_Rate` → `item.vat_rate`

### Supplier & Stock
19. `Supplier` → Creates/links supplier
20. `Current stock quantity` → Opening balance

### Fallback Columns (used if primary missing)
21. `Price_List_Last_Cost` → Fallback for purchase price
22. `Price_List_Retail_Price` → Fallback for retail price
23. `Price_List_Wholesale_Price` → Fallback for wholesale price
24. `Price_List_Retail_Unit_Price` → Fallback for retail price
25. `Price_List_Wholesale_Unit_Price` → Fallback for wholesale price
26. `Purchase price` → Fallback for purchase price

---

## ❌ Unused Columns (16)

These columns exist in Excel but are **NOT imported**:

1. `Online Store Price` - No online store feature
2. `VAT_Description` - We use VAT_Category instead
3. `Supplier_Item_Code` - Not stored on item
4. `Supplier_Last_Cost` - We use Purchase_Price_per_Supplier_Unit
5. `Price_List_Pack_Size` - We use Pack_Size
6. `Price_List_Average_Cost` - We calculate from FEFO batches
7. `Price_List_Trade_Price` - We use wholesale_price
8. `Price_List_Tax_Percentage` - We use VAT_Rate
9. `Price_List_Tax_Code` - We use VAT_Category
10. `Minimum stock quantity` - Not implemented yet
11. `Price_List_Match_Type` - No price matching feature
12. `Price_Attribution_Source` - No price source tracking
13. `HSN` - HSN code not in item model
14. `Sale Discount` - Discounts at invoice level, not item
15. `Tax Rate` - We use VAT_Rate
16. `Inclusive Of Tax` - Not read from Excel

**Why they exist**: Legacy compatibility, future features, alternative column names

---

## ✅ Verification Queries

After import, run these to verify:

```sql
-- Check items created
SELECT COUNT(*) FROM items;  -- Should be ~9,713

-- Check 3-tier structure
SELECT 
    name,
    supplier_unit,
    wholesale_unit,
    retail_unit,
    pack_size,
    purchase_price_per_supplier_unit,
    wholesale_price_per_wholesale_unit,
    retail_price_per_retail_unit,
    vat_category,
    vat_rate
FROM items
LIMIT 10;

-- Check units created
SELECT COUNT(*) FROM item_units;  -- Should be > 0

-- Check opening balances
SELECT COUNT(*) FROM inventory_ledger 
WHERE transaction_type = 'OPENING_BALANCE';
```

---

## 🎯 Expected Results

After successful import:

1. **Items**: ~9,713 items created with 3-tier structure
2. **Units**: Item units created from 3-tier (retail=1, supplier=pack_size, wholesale=pack_size)
3. **Pricing**: All prices on `items` table (not `item_pricing`)
4. **Stock**: Opening balances created in `inventory_ledger`
5. **Display**: Stock shows as "X packets + Y tablets" format

---

## 📝 Files Created

1. `database/add_3tier_units.sql` - Migration script
2. `database/cleanup_items_for_fresh_import.sql` - Cleanup script
3. `EXCEL_TEMPLATE_COLUMN_ANALYSIS.md` - Detailed column analysis
4. `FRESH_IMPORT_GUIDE.md` - Step-by-step guide
5. `QUICK_START_FRESH_IMPORT.md` - Quick reference
6. `analyze_excel_columns.py` - Column analysis script
7. `FRESH_IMPORT_SUMMARY.md` - This file

---

## 🚀 Ready to Import!

Your Excel template has all the required 3-tier columns. Follow the 3-step process above to import fresh data.
