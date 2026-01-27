# Fresh 3-Tier Import Guide

## Overview
After running the 3-tier migration, you may want to wipe existing items and import fresh from Excel to ensure proper 3-tier structure.

---

## Step 1: Run Database Migration

**File**: `database/add_3tier_units.sql`

```bash
# Connect to your database
psql -U your_user -d pharmasight

# Run migration
\i database/add_3tier_units.sql
```

**What it does**:
- Adds 3-tier unit columns to `items` table
- Adds 3-tier pricing columns to `items` table
- Adds `vat_category` column
- Backfills existing rows with defaults

---

## Step 2: Clean Up Old Items Data (Optional)

**File**: `database/cleanup_items_for_fresh_import.sql`

**⚠️ WARNING**: This DELETES all items, units, pricing, and opening balances!

**When to use**:
- You want to start completely fresh
- Old items don't have 3-tier structure
- You're okay losing all existing items

**How to run**:
```bash
psql -U your_user -d pharmasight -f database/cleanup_items_for_fresh_import.sql
```

**What it deletes**:
1. All opening balances (from previous Excel imports)
2. All item_units (will be recreated from 3-tier)
3. All item_pricing (legacy table)
4. All items (cascades to units/pricing)

**Verify cleanup**:
```sql
SELECT COUNT(*) FROM items;  -- Should be 0
SELECT COUNT(*) FROM item_units;  -- Should be 0
SELECT COUNT(*) FROM item_pricing;  -- Should be 0
SELECT COUNT(*) FROM inventory_ledger WHERE transaction_type = 'OPENING_BALANCE';  -- Should be 0
```

---

## Step 3: Import Excel Template

**Template**: `C:\Users\Envy\Downloads\pharmasight_template_fixed_20260126_143121.xlsx`
**Rows**: 9,713 items

### Via Frontend:
1. Go to **Items** page
2. Click **"Import Excel"** button
3. Select the Excel file
4. System will:
   - Detect import mode (AUTHORITATIVE if no live transactions)
   - Read all 3-tier columns
   - Create items with 3-tier structure
   - Create item_units from 3-tier
   - Set pricing on items table
   - Create opening balances

### Via API:
```bash
curl -X POST "http://localhost:8000/api/excel/import" \
  -F "company_id=YOUR_COMPANY_UUID" \
  -F "branch_id=YOUR_BRANCH_UUID" \
  -F "user_id=YOUR_USER_UUID" \
  -F "file=@C:/Users/Envy/Downloads/pharmasight_template_fixed_20260126_143121.xlsx"
```

---

## Step 4: Verify Import

```sql
-- Check items created
SELECT COUNT(*) FROM items;

-- Check 3-tier structure
SELECT 
    name,
    supplier_unit,
    wholesale_unit,
    retail_unit,
    pack_size,
    can_break_bulk,
    purchase_price_per_supplier_unit,
    wholesale_price_per_wholesale_unit,
    retail_price_per_retail_unit,
    vat_category,
    vat_rate
FROM items
LIMIT 10;

-- Check item_units created
SELECT i.name, iu.unit_name, iu.multiplier_to_base
FROM items i
JOIN item_units iu ON iu.item_id = i.id
ORDER BY i.name, iu.multiplier_to_base DESC;

-- Check opening balances
SELECT COUNT(*) FROM inventory_ledger WHERE transaction_type = 'OPENING_BALANCE';
```

---

## Excel Column Mapping

### ✅ USED COLUMNS (20 columns)

| Excel Column | Maps To | Used For |
|-------------|---------|----------|
| Item name* | `item.name` | Item name (required) |
| Item code | `item.sku` | SKU |
| Description | `item.generic_name` | Generic name |
| Category | `item.category` | Category |
| **Supplier_Unit** | `item.supplier_unit` | 3-tier: what we buy |
| **Wholesale_Unit** | `item.wholesale_unit` | 3-tier: what pharmacies buy |
| **Retail_Unit** | `item.retail_unit` | 3-tier: what customers buy |
| **Pack_Size** | `item.pack_size` | 3-tier: retail units per packet |
| **Can_Break_Bulk** | `item.can_break_bulk` | 3-tier: can sell individual units |
| Base Unit (x) | `item.base_unit` | Legacy (also set from retail_unit) |
| Secondary Unit (y) | `item_units.unit_name` | Unit conversion |
| Conversion Rate (n) | `item_units.multiplier_to_base` | Unit conversion |
| **Purchase_Price_per_Supplier_Unit** | `item.purchase_price_per_supplier_unit` | 3-tier pricing |
| **Wholesale_Price_per_Wholesale_Unit** | `item.wholesale_price_per_wholesale_unit` | 3-tier pricing |
| **Retail_Price_per_Retail_Unit** | `item.retail_price_per_retail_unit` | 3-tier pricing |
| Sale price | `item.retail_price_per_retail_unit` | Fallback for retail price |
| **VAT_Category** | `item.vat_category` | VAT classification |
| **VAT_Rate** | `item.vat_rate` | VAT rate (0% or 16%) |
| Supplier | `suppliers.name` | Supplier reference |
| Current stock quantity | `inventory_ledger` | Opening balance |

**Fallback columns** (used if primary column missing):
- Price_List_Last_Cost → purchase_price_per_supplier_unit
- Price_List_Retail_Price → retail_price_per_retail_unit
- Price_List_Wholesale_Price → wholesale_price_per_wholesale_unit
- Purchase price → purchase_price_per_supplier_unit

### ❌ UNUSED COLUMNS (22 columns)

| Excel Column | Why Not Used |
|-------------|--------------|
| Online Store Price | No online store feature |
| VAT_Description | We use VAT_Category instead |
| Supplier_Item_Code | Not stored on item |
| Supplier_Last_Cost | We use Purchase_Price_per_Supplier_Unit |
| Price_List_Pack_Size | We use Pack_Size |
| Price_List_Average_Cost | We calculate from FEFO batches |
| Price_List_Trade_Price | We use wholesale_price |
| Price_List_Tax_Percentage | We use VAT_Rate |
| Price_List_Tax_Code | We use VAT_Category |
| Minimum stock quantity | No reorder point system |
| Price_List_Match_Type | No price matching feature |
| Price_Attribution_Source | No price source tracking |
| HSN | HSN code not in item model |
| Sale Discount | Discounts at invoice level, not item |
| Tax Rate | We use VAT_Rate |
| Inclusive Of Tax | Not read from Excel (set via form) |

---

## Import Process Flow

1. **Excel Read**: Reads all 42 columns
2. **Column Normalization**: Matches column names (case-insensitive, space/underscore normalization)
3. **Item Creation**: Creates item with 3-tier fields from Excel
4. **Unit Creation**: Creates item_units from 3-tier (retail=1, supplier=pack_size, wholesale=pack_size)
5. **Pricing**: Sets pricing on items table (not item_pricing)
6. **Opening Balance**: Creates inventory_ledger entries for stock

---

## Troubleshooting

### Issue: Items created but 3-tier fields are default values
**Solution**: Check Excel column names match exactly (case-sensitive in some cases)

### Issue: Units not created
**Solution**: Check Pack_Size > 0, Supplier_Unit/Wholesale_Unit/Retail_Unit are not empty

### Issue: Prices are 0
**Solution**: Check Purchase_Price_per_Supplier_Unit, Wholesale_Price_per_Wholesale_Unit, Retail_Price_per_Retail_Unit columns exist

### Issue: VAT always 0%
**Solution**: Check VAT_Category column (should be "ZERO_RATED" or "STANDARD_RATED")

---

## Next Steps After Import

1. **Verify Items**: Check items page shows 3-tier prices
2. **Check Stock**: Verify stock displays as "X packets + Y tablets"
3. **Test Sales**: Create a sale and verify correct pricing tier is used
4. **Check VAT**: Verify VAT calculation uses item.vat_rate
