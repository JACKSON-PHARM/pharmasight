# Automatic Order Book Implementation

## Overview ✅

Enhanced the order book module to **automatically** add items to the order book when sales occur, based on stock levels and 3-tier unit system.

## Business Logic

### Criteria for Automatic Order Book Entry

1. **Item Must Have Sales History**
   - Item must have had at least one completed sale (BATCHED or PAID status)
   - Prevents adding items that have never been sold

2. **Stock Falls Below Supplier Pack Size**
   - Current stock (in retail units) < `pack_size` (supplier unit size)
   - Example: If we buy in packs of 30 tablets, and stock is 25 tablets, that's < 1 pack → add to order book

3. **Quantity Limited by Monthly Sales**
   - Order quantity ≤ total sales in last 30 days
   - Prevents over-ordering based on historical demand

### Example Scenario

**Item: Paracetamol 500mg**
- Supplier Unit: packet (pack_size = 30 tablets)
- Current Stock: 25 tablets
- Monthly Sales: 150 tablets

**Result:**
- Stock (25) < Pack Size (30) ✅
- Item has sales history ✅
- Quantity needed: 30 - 25 = 5 tablets
- Capped at monthly sales: min(5, 150) = 5 tablets
- **Added to order book: 5 tablets**

## Implementation

### 1. Order Book Service
**File**: `backend/app/services/order_book_service.py`

**Key Methods:**
- `check_and_add_to_order_book()`: Checks criteria and adds/updates order book entry
- `process_sale_for_order_book()`: Processes all items from a sales invoice
- `_get_preferred_supplier()`: Gets supplier from last purchase

**Logic Flow:**
```
Sale occurs → Check each item:
  1. Has sales history? → No: Skip
  2. Current stock < pack_size? → No: Skip
  3. Calculate quantity needed (pack_size - stock)
  4. Cap at monthly sales
  5. Add/update order book entry
```

### 2. Integration Points

**Sales Invoice Batching** (`backend/app/api/sales.py`)
- After invoice is batched and stock is reduced
- Calls `OrderBookService.process_sale_for_order_book()`
- Checks all items in the invoice

**Quotation Conversion** (`backend/app/api/quotations.py`)
- When quotation is converted to invoice
- Same order book check after stock reduction

### 3. Order Book Entry Details

**Fields Set Automatically:**
- `reason`: "AUTO_SALE" (distinguishes from manual entries)
- `source_reference_type`: "sales_invoice"
- `source_reference_id`: Invoice ID
- `unit_name`: Item's retail_unit (or base_unit)
- `quantity_needed`: Calculated quantity (in retail units)
- `supplier_id`: From last purchase (if available)
- `priority`: 7 (medium-high priority)

**Update Behavior:**
- If PENDING entry exists, updates quantity (takes maximum)
- Prevents duplicate entries per item

## Unit Conversion

### Stock Calculation
- Stock is tracked in **retail units** (base units)
- `InventoryLedger.quantity_delta` is already in base units

### Sales Quantity Conversion
- `SalesInvoiceItem.quantity` is in **sale unit** (could be retail, wholesale, or supplier unit)
- Converts to retail/base units using `InventoryService.convert_to_base_units()`
- Monthly sales sum is in retail units

### Pack Size Comparison
- `Item.pack_size` = retail units per supplier pack
- Direct comparison: `current_stock < pack_size`

## Example Scenarios

### Scenario 1: First Sale
- Item: New item, never sold before
- **Result**: Not added to order book (no sales history)

### Scenario 2: Stock Above Pack Size
- Item: Paracetamol, pack_size=30
- Current Stock: 50 tablets
- **Result**: Not added (50 >= 30)

### Scenario 3: Stock Below Pack Size
- Item: Paracetamol, pack_size=30
- Current Stock: 25 tablets
- Monthly Sales: 150 tablets
- **Result**: Added with quantity = 5 tablets (30 - 25)

### Scenario 4: High Monthly Sales
- Item: Paracetamol, pack_size=30
- Current Stock: 5 tablets
- Monthly Sales: 10 tablets
- Quantity needed: 25 tablets (30 - 5)
- **Result**: Added with quantity = 10 tablets (capped at monthly sales)

## Manual Entries Still Supported

- Manual additions from transaction pages still work
- Manual entries have `reason` = "MANUAL_ADD" or "MANUAL_SALE"
- Auto entries have `reason` = "AUTO_SALE"
- Both can coexist (manual takes precedence if both exist)

## Benefits

1. **Automatic Reordering**: No manual intervention needed
2. **Smart Thresholds**: Based on actual sales patterns
3. **Prevents Stockouts**: Orders before stock runs out
4. **Prevents Over-ordering**: Limited by monthly sales
5. **3-Tier Aware**: Uses pack_size from supplier unit system

## Testing

To test:
1. Create an item with pack_size = 30
2. Add stock: 50 tablets
3. Make a sale: 30 tablets (stock now = 20)
4. Batch the invoice
5. Check order book → Should see entry for 10 tablets (30 - 20)

## Future Enhancements

- [ ] Configurable reorder threshold (currently = pack_size)
- [ ] Minimum order quantity enforcement
- [ ] Supplier lead time consideration
- [ ] Multi-branch aggregation
- [ ] Email notifications for low stock
