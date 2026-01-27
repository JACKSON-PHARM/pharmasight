# Document Listing Fix

## Problem ❌
All document listing pages (Sales Invoices, Quotations, Purchase Invoices, Purchase Orders, GRNs) were failing to display with "Network error: Failed to fetch" errors.

## Root Cause
The API endpoints were not eagerly loading relationship data (like `items`), but the Pydantic response schemas expected these relationships to be present. When SQLAlchemy tried to serialize the response, it attempted to lazy-load relationships outside of an active database session, causing failures.

## Fix ✅

### Added Eager Loading with `selectinload`

All document listing endpoints now use `selectinload` to eagerly load relationships before serialization:

1. **Sales Invoices** (`/api/sales/branch/{branch_id}/invoices`)
   - Added: `selectinload(SalesInvoice.items)`

2. **Quotations** (`/api/quotations/branch/{branch_id}`)
   - Added: `selectinload(Quotation.items)`

3. **Purchase Invoices** (`/api/purchases/invoice`)
   - Added: `selectinload(SupplierInvoice.items)`

4. **Purchase Orders** (`/api/purchases/order`)
   - Added: `selectinload(PurchaseOrder.items)`

5. **GRN** (`/api/purchases/grn/{grn_id}`)
   - Added: `selectinload(GRN.items)`

## Files Modified

### `backend/app/api/sales.py`
```python
@router.get("/branch/{branch_id}/invoices", response_model=List[SalesInvoiceResponse])
def get_branch_invoices(branch_id: UUID, db: Session = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    invoices = db.query(SalesInvoice).options(
        selectinload(SalesInvoice.items)
    ).filter(...).all()
```

### `backend/app/api/quotations.py`
```python
@router.get("/branch/{branch_id}", response_model=List[QuotationResponse])
def get_branch_quotations(branch_id: UUID, db: Session = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    quotations = db.query(Quotation).options(
        selectinload(Quotation.items)
    ).filter(...).all()
```

### `backend/app/api/purchases.py`
- `list_supplier_invoices()`: Added `selectinload(SupplierInvoice.items)`
- `list_purchase_orders()`: Added `selectinload(PurchaseOrder.items)`
- `get_grn()`: Added `selectinload(GRN.items)`

## Why This Fixes It

**Before:**
- Query returned invoices without items loaded
- Pydantic tried to serialize `items: List[...]` from schema
- SQLAlchemy attempted lazy load → **Failed** (session closed or outside transaction)

**After:**
- Query eagerly loads items with `selectinload`
- All data available in memory before serialization
- Pydantic serializes successfully ✅

## Testing

After restarting the backend, all document listing pages should now work:
- ✅ Sales Invoices page
- ✅ Quotations page
- ✅ Purchase Invoices page
- ✅ Purchase Orders page
- ✅ GRN details page

## Next Steps

1. **Restart backend server** to load changes
2. **Test each document listing page**:
   - Sales → Sales Invoices
   - Sales → Quotations
   - Purchases → Supplier Invoices
   - Purchases → Purchase Orders
3. **Verify** that lists display correctly without errors
