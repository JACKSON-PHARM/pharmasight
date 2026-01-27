# 3-Tier Pricing System Implementation

## Overview
Complete implementation of a 3-tier pricing system for PharmaSight, supporting:
- **Tier 1**: Supplier/Wholesale Purchase Price
- **Tier 2**: Wholesale Sale Price  
- **Tier 3**: Retail Sale Price
- Each price is associated with a specific unit (e.g., piece, box, carton)

## Database Changes

### Migration Script
**File**: `database/add_3tier_pricing.sql`

Added columns to `item_pricing` table:
- `supplier_unit` - Unit for supplier price
- `supplier_price_per_unit` - Purchase price per supplier_unit
- `wholesale_unit` - Unit for wholesale price
- `wholesale_price_per_unit` - Wholesale sale price per wholesale_unit
- `retail_unit` - Unit for retail price
- `retail_price_per_unit` - Retail sale price per retail_unit
- `online_store_price_per_unit` - Online store price per retail_unit (optional)

**To apply migration:**
```sql
\i database/add_3tier_pricing.sql
```

## Backend Changes

### 1. Models (`backend/app/models/item.py`)
- Updated `ItemPricing` model to include all 3-tier pricing fields
- All fields are optional to maintain backward compatibility

### 2. Schemas (`backend/app/schemas/item.py`)
- Updated `ItemPricingBase` schema to include 3-tier pricing fields
- All fields are optional with proper validation

### 3. Excel Import Service (`backend/app/services/excel_import_service.py`)
- Updated `_process_item_pricing()` to extract 3-tier prices from Excel template
- Handles columns:
  - `Purchase_Price_per_Supplier_Unit` → supplier_price_per_unit
  - `Wholesale_Price_per_Wholesale_Unit` → wholesale_price_per_unit
  - `Retail_Price_per_Retail_Unit` → retail_price_per_unit
  - `Online Store Price` → online_store_price_per_unit
- Updated `_process_item_units()` to handle unit conversions from Excel template
- Supports `Base Unit (x)`, `Secondary Unit (y)`, and `Conversion Rate (n)` columns

### 4. Pricing Service (`backend/app/services/pricing_service.py`)
- Added `get_3tier_pricing()` method to retrieve all 3-tier prices for an item
- Added `get_price_for_tier()` method to get price for a specific tier with unit conversion
- Updated `calculate_recommended_price()` to prioritize 3-tier pricing over markup-based pricing
- Supports tier parameter: 'supplier', 'wholesale', or 'retail' (defaults to 'retail')

### 5. Items API (`backend/app/api/items.py`)
- Updated search endpoint to include `pricing_3tier` in response
- Updated overview endpoint to include 3-tier pricing
- Added new endpoints:
  - `GET /items/{item_id}/pricing/3tier` - Get all 3-tier prices
  - `GET /items/{item_id}/pricing/tier/{tier}` - Get price for specific tier
- Updated search endpoint to include stock availability with unit breakdown

## Frontend Changes

### 1. Items Page (`frontend/js/pages/items.js`)
- Updated items table to display 3-tier pricing columns:
  - Supplier Price (with unit)
  - Wholesale Price (with unit)
  - Retail Price (with unit, highlighted in green)
- Updated stock display to show unit breakdown (e.g., "8 boxes + 40 tablets")
- Uses `stock_availability.unit_breakdown` when available

### 2. Stock Display
- Enhanced to show both packets and individual units
- Format: "8 boxes + 40 tablets" instead of just "840 tablets"
- Falls back to simple number display if unit breakdown not available

## Excel Template Support

The system now fully supports the Excel template format:
- **Item name*** - Item name
- **Supplier_Unit** - Unit for supplier price
- **Purchase_Price_per_Supplier_Unit** - Tier 1 price
- **Wholesale_Unit** - Unit for wholesale price
- **Wholesale_Price_per_Wholesale_Unit** - Tier 2 price
- **Retail_Unit** - Unit for retail price
- **Retail_Price_per_Retail_Unit** - Tier 3 price
- **Online Store Price** - Optional online price
- **Base Unit (x)** - Base unit name
- **Secondary Unit (y)** - Secondary unit name
- **Conversion Rate (n) (x = ny)** - Conversion rate
- **VAT_Category** - VAT classification
- **VAT_Rate** - VAT rate (0% for zero-rated, 16% for standard-rated)

## Usage

### Importing from Excel
1. Use the Excel template with 3-tier pricing columns
2. Import via "Import Excel" button in Items page
3. System will automatically:
   - Extract 3-tier prices
   - Create/update units
   - Set VAT information
   - Create opening balances (if in authoritative mode)

### Using 3-Tier Pricing in Sales
- The pricing service automatically uses retail tier pricing when available
- Falls back to markup-based pricing if 3-tier not configured
- Prices are converted to the requested unit automatically

### API Usage

**Get 3-tier pricing for an item:**
```javascript
GET /api/items/{item_id}/pricing/3tier
```

**Get specific tier price:**
```javascript
GET /api/items/{item_id}/pricing/tier/retail?unit_name=box
```

**Search items with 3-tier pricing:**
```javascript
GET /api/items/search?company_id=...&branch_id=...&include_pricing=true
// Response includes pricing_3tier field
```

## VAT Handling

VAT is properly handled based on category:
- **ZERO_RATED** - 0% VAT (most medicines)
- **STANDARD** - 16% VAT (some items/services)
- **EXEMPT** - No VAT

VAT information is extracted from Excel template and stored in item records.

## Backward Compatibility

- All 3-tier pricing fields are optional
- System falls back to markup-based pricing if 3-tier not configured
- Existing items continue to work with legacy pricing
- Excel import supports both old and new formats

## Testing

1. **Database Migration**: Run `add_3tier_pricing.sql`
2. **Import Excel**: Import the provided template
3. **Verify Items Page**: Check that 3-tier prices display correctly
4. **Verify Sales**: Check that retail prices are used in POS
5. **Verify Stock Display**: Check that stock shows packets + units

## Notes

- Prices are stored per unit, not per pack
- Unit conversion is handled automatically
- Stock display shows both packets and individual units
- All prices include clear unit attribution
- VAT calculation is based on item category
