# Stock Take Counting Enhancements

## ✅ New Features Added

### 1. Batch Number & Expiry Date Tracking
- **Batch Number**: Required if item has `requires_batch_tracking = true`
- **Expiry Date**: Required if item has `requires_expiry_tracking = true`
- Both fields are optional for items that don't require batch/expiry tracking

### 2. Shelf Location (REQUIRED)
- **Shelf Name/Location**: Now REQUIRED for all counts
- No count can be saved without a shelf name
- Allows tracking which shelf the count was performed on
- Supports multiple counts per item (different shelves = different batches)

### 3. Unit Selection & Mixed Unit Counting
- **Unit Dropdown**: Users can select which unit to count in (PACKET, TABLET, BOX, etc.)
- **Automatic Conversion**: Quantities are automatically converted to base units
- **Mixed Unit Support**: Users can count the same item multiple times:
  - Example: Count "3" in PACKET unit for Shelf A1
  - Then count "25" in TABLET unit for Shelf A1
  - System stores both counts separately and converts to base units

### 4. Multiple Counts Per Item Per Shelf
- **Different Shelves = Different Batches**: 
  - Shelf A1: 20 items (Batch B001)
  - Shelf A2: 15 items (Batch B002)
  - Both counts are saved separately
- **Same Shelf, Different Units**:
  - Shelf A1: 3 packets (converted to base units)
  - Shelf A1: 25 tablets (converted to base units)
  - Both counts are saved separately

## 📋 Database Migration Required (URGENT)

**File**: `database/add_stock_take_batch_fields.sql`

**What it does**:
1. Adds `batch_number` column (VARCHAR(200))
2. Adds `expiry_date` column (DATE)
3. Adds `unit_name` column (VARCHAR(50))
4. Adds `quantity_in_unit` column (NUMERIC(20, 4))
5. Makes `shelf_location` NOT NULL (required)
6. Sets default 'UNKNOWN' for any existing NULL shelf_locations
7. Adds indexes for performance

**How to Run**:
1. Go to: https://supabase.com/dashboard/project/kwvkkbofubsjiwqlqakt/sql/new
2. Copy contents of `database/add_stock_take_batch_fields.sql`
3. Paste and Run
4. **VERIFY**: Run this query to confirm:
   ```sql
   SELECT column_name, is_nullable 
   FROM information_schema.columns 
   WHERE table_name = 'stock_take_counts' 
     AND column_name IN ('shelf_location', 'batch_number', 'expiry_date', 'unit_name', 'quantity_in_unit');
   ```
   Expected: `shelf_location.is_nullable = 'NO'` (required)

## 🎯 User Workflow

### Counting an Item

1. **Search for item** → Click "Count"
2. **Enter Shelf Name** (required) → e.g., "A1", "Shelf 3", "Front Counter"
3. **If item requires batch tracking**:
   - Enter Batch Number (required)
   - Enter Expiry Date (required if item requires expiry tracking)
4. **Select Unit** → Choose from dropdown (PACKET, TABLET, BOX, etc.)
5. **Enter Quantity** → Enter quantity in selected unit
6. **Add Notes** (optional)
7. **Click "Save Count"**

### Mixed Unit Counting Example

**Scenario**: User has 3 packets and 25 tablets on Shelf A1

1. First count:
   - Shelf: "A1"
   - Unit: "PACKET"
   - Quantity: "3"
   - Save → System converts 3 packets to base units

2. Second count (same shelf, different unit):
   - Shelf: "A1"
   - Unit: "TABLET"
   - Quantity: "25"
   - Save → System converts 25 tablets to base units

**Result**: Two separate count records for the same item on the same shelf, both converted to base units.

### Multiple Shelves Example

**Scenario**: Item is on multiple shelves with different batches

1. Shelf A1:
   - Shelf: "A1"
   - Batch: "B001"
   - Expiry: "2026-12-31"
   - Unit: "PACKET"
   - Quantity: "10"
   - Save

2. Shelf A2:
   - Shelf: "A2"
   - Batch: "B002"
   - Expiry: "2027-01-15"
   - Unit: "PACKET"
   - Quantity: "5"
   - Save

**Result**: Two separate count records, one per shelf/batch combination.

## 🔧 Technical Details

### Frontend Changes
- Updated `selectItemForCounting()` to show:
  - Shelf location input (required)
  - Batch number input (conditional)
  - Expiry date input (conditional)
  - Unit selection dropdown
  - Quantity input
- Updated `saveCount()` to:
  - Validate shelf location is provided
  - Validate batch/expiry if required
  - Get unit multiplier from dropdown
  - Convert quantity to base units
  - Send all fields to backend

### Backend Changes
- Updated `StockTakeCount` model to include:
  - `batch_number` (String, nullable)
  - `expiry_date` (Date, nullable)
  - `unit_name` (String, nullable)
  - `quantity_in_unit` (Numeric, nullable)
  - `shelf_location` (String, NOT NULL)
- Updated `create_count()` endpoint to:
  - Validate shelf_location is required
  - Validate batch/expiry if item requires it
  - Convert quantity to base units using `InventoryService.convert_to_base_units()`
  - Store both `quantity_in_unit` and `counted_quantity` (base units)
  - Allow multiple counts per item (different shelf/batch combinations)

### Database Schema
```sql
-- New columns in stock_take_counts:
batch_number VARCHAR(200) NULL
expiry_date DATE NULL
unit_name VARCHAR(50) NULL
quantity_in_unit NUMERIC(20, 4) NULL
shelf_location VARCHAR(100) NOT NULL  -- Changed from nullable
```

## ✅ Validation Rules

1. **Shelf Location**: Always required
2. **Batch Number**: Required if `item.requires_batch_tracking = true`
3. **Expiry Date**: Required if `item.requires_expiry_tracking = true`
4. **Unit Selection**: Must be a valid unit for the item
5. **Quantity**: Must be >= 0

## 📝 Notes

- **Unit Conversion**: All quantities are stored in base units in `counted_quantity`
- **Original Unit**: Stored in `quantity_in_unit` and `unit_name` for reference
- **Multiple Counts**: System allows multiple counts per item (different shelves/batches)
- **Same Shelf Updates**: If count exists for same item/shelf/batch/expiry, it updates the existing count
- **Different Shelves**: Creates new count record (different shelf = different batch location)
