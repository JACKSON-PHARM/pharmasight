# Order Book Fine-Tuning Implementation

## Changes Made ✅

### 1. **Quantity Rounding to Supplier Units**

**Before:**
- Ordered in retail units (e.g., "10 tablets")
- Direct quantity from calculation

**After:**
- Orders are rounded to supplier units (packs)
- Logic:
  - If needed ≤ 1.5 packs → order 1 pack
  - If needed > 1.5 packs → round up to next whole pack
- Example:
  - Stock: 25 tablets, pack_size: 30
  - Needed: 5 tablets = 0.17 packs → order **1 pack** (30 tablets)
  - Needed: 35 tablets = 1.17 packs → order **2 packs** (60 tablets)

**Implementation:**
```python
quantity_needed_supplier_units = quantity_needed_retail_units / pack_size

if quantity_needed_supplier_units <= 0:
    packs_needed = 0
elif quantity_needed_supplier_units <= 1.5:
    packs_needed = 1
else:
    packs_needed = int(quantity_needed_supplier_units) + (1 if quantity_needed_supplier_units % 1 > 0 else 0)

quantity_needed_retail_units = packs_needed * pack_size  # For display
unit_name = supplier_unit  # Use supplier unit name
```

### 2. **Simplified Source Tracking**

**Before:**
- `source_reference_type`: "sales_invoice", "quotation", etc.
- `source_reference_id`: Invoice/Quotation ID
- `reason`: "AUTO_SALE", "MANUAL_ADD", etc.

**After:**
- `reason`: "AUTO_SALE" (auto-generated) or "MANUAL_ADD" (manual)
- `created_by`: User ID (for tracking who created it)
- `source_reference_type`: Set to `None` (not used)
- `source_reference_id`: Set to `None` (not used)

**Benefits:**
- Simpler tracking
- Clear distinction: auto vs manual
- User tracking via `created_by`

### 3. **Only Stock-Reducing Transactions Trigger Auto-Add**

**Implementation:**
- `process_sale_for_order_book()` now checks `invoice.status == "BATCHED"`
- Only BATCHED invoices trigger order book (stock has been reduced)
- DRAFT invoices, quotations, and purchases do NOT trigger

**Flow:**
1. **Sales Invoice Batching** → Stock reduced → Invoice status = BATCHED → Order book check ✅
2. **Quotation Conversion** → Invoice created → Stock reduced → Invoice status set to BATCHED → Order book check ✅
3. **Quotation (not converted)** → No stock reduction → No order book ❌
4. **Purchase Invoice** → Stock increased → No order book ❌
5. **Manual Addition** → User clicks "Add to Order Book" → `reason="MANUAL_ADD"` ✅

## Updated Files

### `backend/app/services/order_book_service.py`
- Added rounding logic to supplier units
- Simplified to use `is_auto` parameter instead of `source_reference_type/id`
- Updated `process_sale_for_order_book()` to only process BATCHED invoices

### `backend/app/api/order_book.py`
- Manual entries set `source_reference_type/id` to `None`
- Default `reason="MANUAL_ADD"` for manual entries

### `backend/app/api/quotations.py`
- Set invoice status to BATCHED when converting (since stock is reduced)
- Ensures order book check works correctly

## Example Scenarios

### Scenario 1: Stock Below Pack Size
- Item: Paracetamol, pack_size=30
- Current Stock: 25 tablets
- After Sale: 20 tablets
- Calculation: 30 - 20 = 10 tablets needed
- Rounded: 10/30 = 0.33 packs → **1 pack** (30 tablets)
- Order Book: 1 pack (30 tablets) in supplier_unit

### Scenario 2: More Than 1.5 Packs Needed
- Item: Paracetamol, pack_size=30
- Current Stock: 10 tablets
- After Sale: 5 tablets
- Calculation: 30 - 5 = 25 tablets needed
- Rounded: 25/30 = 0.83 packs → **1 pack** (30 tablets)

### Scenario 3: More Than 1.5 Packs
- Item: Paracetamol, pack_size=30
- Current Stock: 5 tablets
- After Sale: 0 tablets
- Monthly Sales: 50 tablets
- Calculation: min(30 - 0, 50) = 30 tablets needed
- But if monthly sales = 40 tablets: min(30, 40) = 30 tablets
- Rounded: 30/30 = 1.0 packs → **1 pack** (30 tablets)

### Scenario 4: More Than 1.5 Packs
- Item: Paracetamol, pack_size=30
- Current Stock: 10 tablets
- Monthly Sales: 50 tablets
- Calculation: min(30 - 10, 50) = 20 tablets needed
- Rounded: 20/30 = 0.67 packs → **1 pack** (30 tablets)

### Scenario 5: Exactly 1.5 Packs
- Item: Paracetamol, pack_size=30
- Current Stock: 15 tablets
- Calculation: 30 - 15 = 15 tablets needed
- Rounded: 15/30 = 0.5 packs → **1 pack** (30 tablets)

### Scenario 6: More Than 1.5 Packs
- Item: Paracetamol, pack_size=30
- Current Stock: 5 tablets
- Monthly Sales: 50 tablets
- Calculation: min(30 - 5, 50) = 25 tablets needed
- Rounded: 25/30 = 0.83 packs → **1 pack** (30 tablets)

### Scenario 7: More Than 1.5 Packs (Edge Case)
- Item: Paracetamol, pack_size=30
- Current Stock: 0 tablets
- Monthly Sales: 50 tablets
- Calculation: min(30 - 0, 50) = 30 tablets needed
- Rounded: 30/30 = 1.0 packs → **1 pack** (30 tablets)

### Scenario 8: More Than 1.5 Packs
- Item: Paracetamol, pack_size=30
- Current Stock: 0 tablets
- Monthly Sales: 50 tablets
- Calculation: min(30 - 0, 50) = 30 tablets needed
- But if we need 35 tablets: 35/30 = 1.17 packs → **2 packs** (60 tablets)

## Testing

To test the rounding:
1. Create item with pack_size=30
2. Add stock: 50 tablets
3. Make sale: 30 tablets (stock = 20)
4. Batch invoice
5. Check order book → Should see **1 pack** (not 10 tablets)

To test source tracking:
1. Auto entry: `reason="AUTO_SALE"`, `source_reference_type=None`, `source_reference_id=None`
2. Manual entry: `reason="MANUAL_ADD"`, `source_reference_type=None`, `source_reference_id=None`

To test stock-reducing only:
1. Create quotation → No order book entry
2. Convert quotation → Invoice BATCHED → Order book entry created ✅
3. Create purchase → No order book entry ❌
