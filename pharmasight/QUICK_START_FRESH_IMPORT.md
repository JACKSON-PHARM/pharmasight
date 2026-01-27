# Quick Start: Fresh 3-Tier Import

## 🚀 3-Step Process

### Step 1: Run Migration
```bash
psql -U your_user -d pharmasight -f database/add_3tier_units.sql
```

### Step 2: Clean Up (Optional - Only if you want to start fresh)
```bash
psql -U your_user -d pharmasight -f database/cleanup_items_for_fresh_import.sql
```

### Step 3: Import Excel
1. Open PharmaSight frontend
2. Go to **Items** page
3. Click **"Import Excel"**
4. Select: `C:\Users\Envy\Downloads\pharmasight_template_fixed_20260126_143121.xlsx`
5. Wait for import to complete (9,713 items)

---

## 📊 Excel Template Analysis

**Total Columns**: 42  
**Used**: 20 columns (3-tier system)  
**Unused**: 22 columns (legacy/not implemented)

### ✅ Critical 3-Tier Columns (MUST HAVE)

| Column | Purpose |
|--------|---------|
| `Item name*` | Item name (required) |
| `Supplier_Unit` | What we buy (packet/box/bottle) |
| `Wholesale_Unit` | What pharmacies buy |
| `Retail_Unit` | What customers buy (tablet/capsule/ml) |
| `Pack_Size` | Retail units per packet (e.g., 30) |
| `Can_Break_Bulk` | Can sell individual units? |
| `Purchase_Price_per_Supplier_Unit` | Cost per packet |
| `Wholesale_Price_per_Wholesale_Unit` | Price per packet to pharmacies |
| `Retail_Price_per_Retail_Unit` | Price per tablet to customers |
| `VAT_Category` | ZERO_RATED or STANDARD_RATED |
| `VAT_Rate` | 0.00 or 16.00 |
| `Current stock quantity` | Opening balance |

### ❌ Unused Columns (Safe to Ignore)

These columns exist in Excel but are **NOT imported**:

- `Online Store Price` - No online store feature
- `VAT_Description` - We use VAT_Category
- `Supplier_Item_Code` - Not stored
- `Price_List_*` fields (many) - Legacy price list system
- `Minimum stock quantity` - Not implemented
- `HSN` - Not in model
- `Sale Discount` - Discounts at invoice level
- `Tax Rate` - We use VAT_Rate
- `Inclusive Of Tax` - Not read from Excel

**Why they exist**: Legacy compatibility, future features, alternative column names.

---

## ✅ Verification After Import

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
    retail_price_per_retail_unit
FROM items
LIMIT 5;

-- Check units created
SELECT COUNT(*) FROM item_units;  -- Should be > 0

-- Check opening balances
SELECT COUNT(*) FROM inventory_ledger 
WHERE transaction_type = 'OPENING_BALANCE';
```

---

## 🐛 Common Issues

### Issue: "Items created but prices are 0"
**Cause**: Column names don't match  
**Fix**: Check Excel has exact column names:
- `Purchase_Price_per_Supplier_Unit`
- `Wholesale_Price_per_Wholesale_Unit`
- `Retail_Price_per_Retail_Unit`

### Issue: "Units not created"
**Cause**: Pack_Size = 0 or units are empty  
**Fix**: Ensure `Pack_Size` > 0, `Supplier_Unit`, `Wholesale_Unit`, `Retail_Unit` are not empty

### Issue: "VAT always 0%"
**Cause**: VAT_Category column missing or wrong value  
**Fix**: Ensure column is `VAT_Category` with values `ZERO_RATED` or `STANDARD_RATED`

---

## 📝 Notes

- **Import Mode**: System auto-detects AUTHORITATIVE (if no live transactions) or NON_DESTRUCTIVE
- **Stock Display**: After import, stock shows as "X packets + Y tablets" format
- **Pricing**: All prices stored on `items` table (not `item_pricing`)
- **Units**: Created automatically from 3-tier structure (retail=1, supplier=pack_size, wholesale=pack_size)
