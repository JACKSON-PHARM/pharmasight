# Excel import – client column mapping guide

This guide helps when onboarding clients whose Excel uses different column names (e.g. “harte reports” style). PharmaSight can accept their columns and map them to the correct fields.

## Import behaviour (flexible but strict)

- **Item name is the main column** – required; other columns are optional and mapped when present.
- **Blank rows** – rows with no item name are **silently skipped** (no error).
- **Duplicate item names** – the same item name must not appear twice in the file (case-insensitive). Import fails with a clear error listing duplicates.
- **Single quantity column** – when the file has only one stock column (e.g. “Quantity Available”, “Current stock quantity”), it is treated as **retail (base) units**. Ledger and stock are stored in base/retail; no conversion is applied when `pack_size` is 1.
- **No transactions until setup complete** – items created or overwritten by import get `setup_complete = false`. They can be searched and edited, but **cannot be added to sales, purchases, or GRN** until the user completes item setup (pack size, units) and saves the item. Then the item is ready for transactions.

## 1. Item code (SKU)

- If **Item_Code** (or SKU) is **missing** or empty, PharmaSight **auto-generates** a unique code (e.g. `A00001`, `A00002`) during import.
- No need to fill item code in the sheet if the client does not use it.

## 2. Item name

- **PharmaSight template:** `Item_Name`
- **Client “harte reports” style:** column is often **`Description`** (product name).
- Import accepts **`Description`** as the item name when `Item_Name` is not present, so their file works without changing column headers.
- If using the **column mapping** UI, map: **Description → Item name**.

## 3. Categories and pricing

PharmaSight has two notions that affect pricing and reporting:

| PharmaSight field       | Meaning | Your client’s file |
|-------------------------|--------|---------------------|
| **product_category**    | High-level type: PHARMACEUTICAL, COSMETICS, EQUIPMENT, SERVICE | Often **Category** (e.g. PHARMACY, COSMETICS) |
| **pricing_tier**       | Drives default margin: CHRONIC_MEDICATION, STANDARD, BEAUTY_COSMETICS, NUTRITION_SUPPLEMENTS, etc. | Often **Sub Category** (e.g. SUPPLEMENTS, MOISTURIZER) |
| **category**           | Free-text label (e.g. brand, internal code) | **Category**, **Sub Category**, or **Brand** |

### Automatic mapping (no mapping UI needed)

Import already maps many client values:

- **Category**  
  - `PHARMACY` → **product_category** = PHARMACEUTICAL  
  - `COSMETICS` → **product_category** = COSMETICS  

- **Sub Category** → **pricing_tier** (examples):  
  - SUPPLEMENTS → NUTRITION_SUPPLEMENTS  
  - MOISTURIZER, LOTION, PERFUMES, SKIN CARE, SOAP, etc. → BEAUTY_COSMETICS  
  - INSULIN INJ, VACCINE INJ → INJECTABLES  
  - CONTROLLED, NON PHARM → STANDARD  
  - ANTIDIABETICS, ANTIHYPERTENSIVE, STATINS, etc. → CHRONIC_MEDICATION  

- **Brand** can be read as **category** (free text) if you map or use it that way.

So when the client uses **Category** and **Sub Category**, the right **product_category** and **pricing_tier** are set automatically where we have a rule.

## 4. Prices and quantity (client “harte reports” style)

These client columns are recognised by name (no mapping needed if headers match):

| Client column           | PharmaSight use |
|------------------------|-----------------|
| **Cost price**         | Cost / purchase price (cost per base unit when no wholesale cost column) |
| **Wsale price**        | Wholesale unit price (cost or selling price per wholesale unit) |
| **Selling price**      | Retail/sale price (map to **Retail Price / Sale Price** in column mapping if needed) |
| **pack size**          | Pack size (retail units per wholesale unit) |
| **Quantity Available** | Opening stock (**must be in wholesale/base units**; see below) |
| **Brand**              | Can be used as category (free text) |

## 5. Current stock (quantity) – units

- When the file has **only one quantity column** (e.g. “Quantity Available”, “Current stock quantity”), it is treated as **retail (base) units**. Enter the number in the smallest unit you use (e.g. tablets, pieces).
- Example: 5000 tablets in stock → enter **5000**. With `pack_size = 1` (default for minimal import), that is stored as 5000 base units.
- If the client later configures pack size (e.g. 100 tablets per box), existing ledger is already in retail; new stock movements use the same base (retail) convention.

## 6. What to tell the client

1. **Item name:** Their **Description** column is used as the item name; they can keep that header.
2. **Item code:** Optional; if empty, we auto-generate (e.g. A00001, A00002).
3. **Category / Sub Category:** We map these to **product_category** and **pricing_tier**; they can keep PHARMACY / COSMETICS and their Sub Category values.
4. **Stock:** “Quantity Available” must be in **wholesale (base) units** (e.g. number of boxes, not number of tablets).
5. **Prices:** We read **Cost price**, **Wsale price**, and (with mapping if needed) **Selling price**.
6. **Column mapping (optional):** In the import UI they can map any header to the right PharmaSight field (e.g. Description → Item name, Selling price → Retail Price) for full control.

## 7. Quick reference – “harte reports” columns

| Their column             | Goes to / note |
|--------------------------|----------------|
| Description              | Item name (auto) |
| pack size                | Pack size (auto) |
| Brand                    | Category (auto if used) |
| Category                 | product_category (PHARMACY→PHARMACEUTICAL, COSMETICS→COSMETICS) |
| Sub Category             | pricing_tier (see mapping above) |
| Cost price               | Cost (auto) |
| Selling price            | Retail price (map if needed) |
| Wsale price              | Wholesale price / cost (auto) |
| Quantity Available       | Current stock in **wholesale units** (auto) |
| Stock Value With C.P / … | Not imported (informational only) |
