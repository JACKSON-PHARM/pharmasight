# Complete 3-Tier System Implementation - All 5 Questions Answered

## 1. EXACT get_stock_display() Function

**Location**: `backend/app/services/inventory_service.py` lines 298-320

```python
@staticmethod
def get_stock_display(
    db: Session,
    item_id: UUID,
    branch_id: UUID
) -> str:
    """
    Get stock display using 3-tier units: "X packets + Y tablets" or "X packets (Z tablets)" or "Y tablets".
    Stock is tracked in retail units (base units). Uses supplier_unit, retail_unit, pack_size when present.
    
    CALCULATION LOGIC:
    - Stock is ALWAYS in retail units (base units) from inventory_ledger
    - full_packets = total_retail // pack_size  (integer division)
    - partial_units = total_retail % pack_size  (modulo/remainder)
    
    Example: 157 tablets, pack_size=30
    - full_packets = 157 // 30 = 5
    - partial_units = 157 % 30 = 7
    - Returns: "5 packet + 7 tablet"
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return "0"
    
    # Get total stock in retail units (base units)
    total_retail = InventoryService.get_current_stock(db, item_id, branch_id)
    
    # Get 3-tier unit info
    supplier_unit = getattr(item, "supplier_unit", None) or "piece"
    retail_unit = getattr(item, "retail_unit", None) or item.base_unit
    pack_size = max(1, int(getattr(item, "pack_size", None) or 1))
    
    # Calculate full packets and remainder
    full_packets = total_retail // pack_size  # Integer division: 157 // 30 = 5
    partial_units = total_retail % pack_size   # Remainder: 157 % 30 = 7
    
    # Format display
    if full_packets > 0 and partial_units > 0:
        return f"{full_packets} {supplier_unit} + {partial_units} {retail_unit}"
    elif full_packets > 0:
        return f"{full_packets} {supplier_unit} ({full_packets * pack_size} {retail_unit})"
    else:
        return f"{partial_units} {retail_unit}"
```

**How it calculates:**
- Stock is ALWAYS tracked in **retail units** (base units) in `inventory_ledger`
- `full_packets = total_retail // pack_size` (integer division: 157 // 30 = 5)
- `partial_units = total_retail % pack_size` (remainder: 157 % 30 = 7)
- Display: "5 packet + 7 tablet"

---

## 2. Excel Import Service - 3-Tier Columns

**Location**: `backend/app/services/excel_import_service.py`

**UPDATED**: `_create_item_from_excel()` now reads ALL 3-tier columns from Excel template and sets them on **Item model** (not ItemPricing):

- `Supplier_Unit` → `item.supplier_unit`
- `Wholesale_Unit` → `item.wholesale_unit`
- `Retail_Unit` → `item.retail_unit`
- `Pack_Size` → `item.pack_size`
- `Can_Break_Bulk` → `item.can_break_bulk`
- `Purchase_Price_per_Supplier_Unit` → `item.purchase_price_per_supplier_unit`
- `Wholesale_Price_per_Wholesale_Unit` → `item.wholesale_price_per_wholesale_unit`
- `Retail_Price_per_Retail_Unit` → `item.retail_price_per_retail_unit`
- `VAT_Category` → `item.vat_category`
- `VAT_Rate` → `item.vat_rate`

**COMPLETE CODE**: See updated `_create_item_from_excel()` method in excel_import_service.py

**KEY CHANGE**: All 3-tier pricing is stored on **Item model**, not ItemPricing table.

---

## 3. VAT Category Logic in items_service.py

**Location**: `backend/app/services/items_service.py` lines 111-112

```python
# VAT category mapping in create_item():
if data.vat_category:
    dump["vat_code"] = dump.get("vat_code") or data.vat_category

# VAT Rules:
# - vat_category = "ZERO_RATED" → vat_rate = 0.00 (medicines)
# - vat_category = "STANDARD_RATED" → vat_rate = 16.00 (non-medical)
# - Maps vat_category to vat_code for legacy compatibility
```

**VAT Calculation in Sales** (`backend/app/api/sales.py` line 82-124):
```python
# Copy VAT classification from item
item_vat_rate = Decimal(str(item.vat_rate or 0))

# Calculate VAT on line total
line_vat = line_total_exclusive * item_vat_rate / Decimal("100")
line_total_inclusive = line_total_exclusive + line_vat
```

**VAT Logic Flow**:
1. Item has `vat_category` ("ZERO_RATED" or "STANDARD_RATED")
2. Item has `vat_rate` (0.00 or 16.00)
3. Sales invoice uses `item.vat_rate` for calculation
4. VAT = `line_total_exclusive * vat_rate / 100`

**Excel Import VAT Logic**:
```python
vat_category_raw = _normalize_column_name(row, ['VAT_Category', 'VAT Category']) or 'ZERO_RATED'
vat_category = vat_category_raw.strip().upper()
vat_rate_raw = _normalize_column_name(row, ['VAT_Rate', 'VAT Rate', 'Tax Rate']) or '0'
vat_rate = ExcelImportService._parse_decimal(vat_rate_raw)
if vat_category == 'STANDARD_RATED' and vat_rate == 0:
    vat_rate = Decimal('16.00')
elif vat_category == 'ZERO_RATED':
    vat_rate = Decimal('0.00')
```

---

## 4. Transaction Logic: Selling 7 Tablets (pack_size=30)

**Scenario**: Item has `pack_size=30`, stock = 157 tablets, user sells 7 tablets

**COMPLETE FLOW** (`backend/app/api/sales.py`):

### Step 1: User Creates Invoice (DRAFT)
```python
# User selects item, enters quantity=7, unit_name="tablet"
item_data = {
    "item_id": "...",
    "unit_name": "tablet",
    "quantity": 7.0
}
```

### Step 2: Check Availability (line 85-93)
```python
is_available, available, required = InventoryService.check_stock_availability(
    db, item_data.item_id, invoice.branch_id,
    7.0, "tablet"
)
# Converts: 7 tablets * 1 (multiplier) = 7 base units
# Checks: available_base (157) >= required_base (7) ✅
```

### Step 3: Get Price (line 100-103)
```python
price_info = PricingService.calculate_recommended_price(
    db, item_id, branch_id, company_id, "tablet", tier="retail"
)
# Uses: item.retail_price_per_retail_unit = 25.00
# Returns: recommended_unit_price = 25.00
```

### Step 4: Calculate Totals (line 121-125)
```python
line_total_exclusive = Decimal("25.00") * Decimal("7") = 175.00
line_vat = 175.00 * 0.00 / 100 = 0.00  # Zero-rated
line_total_inclusive = 175.00 + 0.00 = 175.00
```

### Step 5: When Invoice is BATCHED (line 405-447)
```python
# Convert quantity to base units
quantity_base = InventoryService.convert_to_base_units(
    db, item_id, 7.0, "tablet"
)
# Returns: 7 (base units) - because tablet multiplier = 1

# Allocate stock (FEFO)
allocations = InventoryService.allocate_stock_fefo(
    db, item_id, branch_id, 7, "tablet"
)
# Returns: [{"quantity": 7, "batch_number": "...", "unit_cost": ..., ...}]

# Create ledger entry (NEGATIVE for sale)
ledger_entry = InventoryLedger(
    quantity_delta=-7,  # Negative (sale reduces stock)
    unit_cost=...,  # Cost per tablet (from FEFO batch)
    total_cost=... * 7
)
```

### Step 6: Stock After Sale
- Before: 157 tablets
- After: 157 - 7 = 150 tablets
- Display: `get_stock_display()` → "5 packet (150 tablet)"

**KEY POINT**: Stock is ALWAYS tracked in **retail units** (tablets). Selling 7 tablets reduces stock by 7 base units, regardless of pack_size. The ledger stores `quantity_delta=-7` in base units.

---

## 5. Wholesale vs Retail Sales Distinction

**IMPLEMENTATION**: Added `sales_type` field to distinguish wholesale vs retail sales.

### Database Migration
**File**: `database/add_sales_type.sql`
```sql
ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS sales_type VARCHAR(20) DEFAULT 'RETAIL';
COMMENT ON COLUMN sales_invoices.sales_type IS 'RETAIL (customers) or WHOLESALE (pharmacies). Determines which pricing tier to use.';
```

### Model Update
**File**: `backend/app/models/sale.py`
```python
sales_type = Column(String(20), default="RETAIL")  # RETAIL or WHOLESALE
```

### Schema Update
**File**: `backend/app/schemas/sale.py`
```python
sales_type: str = Field(default="RETAIL", description="RETAIL (customers) or WHOLESALE (pharmacies)")
```

### API Logic
**File**: `backend/app/api/sales.py` (line 95-103)
```python
# Get appropriate tier based on sales_type
sales_type = getattr(invoice, 'sales_type', 'RETAIL') or 'RETAIL'
pricing_tier = 'wholesale' if sales_type == 'WHOLESALE' else 'retail'

price_info = PricingService.calculate_recommended_price(
    db, item_id, branch_id, company_id, unit_name, tier=pricing_tier
)
# Uses:
# - WHOLESALE → item.wholesale_price_per_wholesale_unit (per packet)
# - RETAIL → item.retail_price_per_retail_unit (per tablet)
```

### Frontend Update
**File**: `frontend/js/pages/sales.js`
- Added `sales_type` dropdown in invoice form (RETAIL/WHOLESALE)
- Defaults to RETAIL
- Sends `sales_type` in invoice creation

**How it works**:
- `sales_type = "RETAIL"` → Uses `retail_price_per_retail_unit` (per tablet)
- `sales_type = "WHOLESALE"` → Uses `wholesale_price_per_wholesale_unit` (per packet)
- Pricing service automatically selects correct tier and converts units

---

## Summary

1. **Stock Display**: Calculates `full_packets = total // pack_size`, `partial = total % pack_size`
2. **Excel Import**: Reads all 3-tier columns from template and sets on **Item model** (not ItemPricing)
3. **VAT Logic**: `vat_category` → `vat_rate` (0% or 16%), used in sales calculations
4. **Transaction**: Selling 7 tablets reduces stock by 7 base units, tracked in `inventory_ledger` as `quantity_delta=-7`
5. **Wholesale vs Retail**: `sales_type` field determines which pricing tier to use (wholesale_price vs retail_price)
