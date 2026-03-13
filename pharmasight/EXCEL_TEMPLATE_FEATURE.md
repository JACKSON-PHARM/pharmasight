# Excel Template Download and Import

## Template format (current)

The **Download Template** button (Items / Inventory page) generates an Excel file that matches the backend import format.

### Headers (row 1)

| Column | Meaning | Required |
|--------|--------|----------|
| Item_Name | Item name | **Yes** |
| Description | Generic name / description | No |
| Item_Code | SKU | No |
| Barcode | Barcode | No |
| Category | Category | No |
| Supplier_Unit | e.g. carton | No |
| Wholesale_Unit | Base unit, e.g. box | No |
| Retail_Unit | e.g. tablet | No |
| Pack_Size | Retail per 1 wholesale (e.g. 100) | No |
| Wholesale_Units_per_Supplier | e.g. 12 | No |
| Can_Break_Bulk | Yes/No | No |
| Track_Expiry | Yes/No | No |
| Purchase_Price_per_Supplier_Unit | Cost per supplier unit | No |
| Wholesale_Price_per_Wholesale_Unit | Selling price per wholesale unit | No |
| Retail_Price_per_Retail_Unit | Selling price per retail unit | No |
| **Current_Stock_Quantity** | **Opening stock in wholesale (base) units only** | No |
| Opening_Batch_Number | Required if Track_Expiry=Yes and opening stock > 0 | No |
| Opening_Expiry_Date | YYYY-MM-DD | No |
| Supplier | Supplier name | No |
| VAT_Category | ZERO_RATED or STANDARD_RATED | No |
| VAT_Rate | e.g. 0 or 16 | No |
| Product_Category | PHARMACEUTICAL, COSMETICS, EQUIPMENT, SERVICE | No |
| Pricing_Tier | Optional | No |

### Current stock (units)

- **Base unit in PharmaSight = wholesale unit** (e.g. box, bottle). All ledger quantities are stored in wholesale (base) units.
- **Current_Stock_Quantity** must be in **wholesale (base) units**, not retail.
  - Example: item “Paracetamol 500mg box of 100 tablets” — if you have 50 boxes, enter **50**, not 5000 (tablets).
- There is a single column for opening stock. If you only have retail counts, convert to wholesale first (e.g. 5000 tablets ÷ 100 per box = 50 boxes).

### Instructions sheet

The downloaded file has a second sheet **Instructions** with the same column guide. Import uses only the first sheet (**Pharmasight Template**).

### User flow

1. Click **Download Template** → `pharmasight_template.xlsx` downloads.
2. Fill data from row 2 onward; keep row 1 headers unchanged.
3. Click **Import Excel**, select the file, map columns if needed, then run import.

## Notes

- Template uses the XLSX.js library (loaded in `index.html`).
- Backend accepts these exact headers and common variants (e.g. "Item name*", "Current stock quantity"); the template uses canonical names (e.g. Item_Name, Current_Stock_Quantity).
- Required for import: **Item_Name**. Other fields are optional.
- For items with **Track_Expiry = Yes** and opening stock > 0, provide **Opening_Batch_Number** and **Opening_Expiry_Date** (YYYY-MM-DD).
