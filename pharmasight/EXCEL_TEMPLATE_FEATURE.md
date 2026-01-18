# ✅ Excel Template Download Feature

## What Was Implemented

### 1. **Template Download Button**
- Added "Download Template" button on the Items page
- Button is placed before the "Import Excel" button
- Downloads a properly formatted Excel template with exact headers

### 2. **Template Headers**
The template includes these exact headers (matching your specification):
1. **Item name*** (required)
2. **Item code**
3. **Description**
4. **Category**
5. **HSN**
6. **Sale price**
7. **Purchase price**
8. **opening stock quantity**
9. **Tax Rate**
10. **Inclusive Of Tax**
11. **Base Unit (x)**
12. **Secondary Unit (y)**
13. **Conversion Rate (n) (x = ny)**

### 3. **Updated Import Mapping**
The import function now correctly maps template headers to item fields:
- `Item name*` → `name` (required)
- `Item code` → `sku`
- `Description` → `generic_name`
- `Category` → `category`
- `Purchase price` → `default_cost`
- `Base Unit (x)` → `base_unit` (required)
- `Secondary Unit (y)` + `Conversion Rate (n)` → `ItemUnit` conversion

### 4. **User Flow**

1. **Download Template:**
   - Click "Download Template" button
   - Excel file downloads: `PharmaSight_Items_Template_YYYY-MM-DD.xlsx`
   - File has headers in row 1

2. **Fill Template:**
   - Open the downloaded template
   - Fill in your items (keep headers unchanged)
   - Save the file

3. **Import:**
   - Click "Import Excel" button
   - Select your filled template
   - Preview shows first 5 rows
   - Click "Import Items" to upload

## Fields Mapping Details

### Imported Fields:
- ✅ **Item name*** → Item name (required)
- ✅ **Item code** → SKU
- ✅ **Description** → Generic name
- ✅ **Category** → Category
- ✅ **Purchase price** → Default cost
- ✅ **Base Unit (x)** → Base unit (required)
- ✅ **Secondary Unit (y)** + **Conversion Rate (n)** → Unit conversion

### Not Currently Imported (Future Enhancement):
- **HSN** - Not in current item model
- **Sale price** - Calculated from purchase price using markup
- **opening stock quantity** - Requires inventory import separately
- **Tax Rate** - Uses default 16% (can be configured per item later)
- **Inclusive Of Tax** - Uses default false (can be configured later)

These fields are included in the template for future use or manual configuration.

## Usage Example

### Template Row:
```
Item name*: FELVIN (PIROXICAM 20MG)
Item code: 
Description: nsaids
Category: F
HSN: 
Sale price: 500
Purchase price: 65
opening stock quantity: 15
Tax Rate: 
Inclusive Of Tax: 
Base Unit (x): packets
Secondary Unit (y): capsules
Conversion Rate (n): 100
```

### Creates:
- Item name: "FELVIN (PIROXICAM 20MG)"
- SKU: (empty)
- Generic name: "nsaids"
- Category: "F"
- Default cost: 65
- Base unit: "packets"
- Unit conversion: 1 packet = 100 capsules

## Testing

1. **Download Template:**
   ```javascript
   // In browser console
   downloadItemTemplate()
   ```
   Should download Excel file with headers.

2. **Fill Template:**
   - Open downloaded file
   - Add at least one item with:
     - Item name* (required)
     - Purchase price (required)
     - Base Unit (x) (required)

3. **Import:**
   - Click "Import Excel"
   - Select filled template
   - Preview should show your data
   - Click "Import Items"
   - Items should appear in the items list

## Notes

- Template uses XLSX.js library (already loaded in `index.html`)
- Headers must match exactly (case-sensitive for import)
- Users should NOT change header row
- Empty cells are handled gracefully
- Required fields: Item name*, Purchase price, Base Unit (x)
- Template filename includes date: `PharmaSight_Items_Template_2026-01-10.xlsx`
