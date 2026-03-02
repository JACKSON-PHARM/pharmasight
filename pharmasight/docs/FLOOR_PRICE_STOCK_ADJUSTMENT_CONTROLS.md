# Floor Price Controls on Stock Adjustments

## Overview

When adding stock (via manual adjustment or supplier invoice batch), items that are selling at **floor price** or have **margin below standard** require the user to re-enter the unit cost to confirm they are aware of the price.

## Flows Covered

1. **Manual stock adjustment** (`POST /items/{id}/adjust-stock`)
2. **Supplier invoice batch** (`POST /purchases/invoice/{id}/batch`)

## When Confirmation Is Required

- Item has `floor_price_retail` set
- Unit cost being added is > 0 (donations/samples with zero cost are skipped)
- Margin when selling at floor may be below company minimum (especially critical)

## Implementation

### Backend

- **`pricing_config_service.check_stock_adjustment_requires_confirmation`**: Returns `{ requires_confirmation, reason, floor_price, margin_below_standard }` when item has floor price.
- **`AdjustStockRequest.confirm_unit_cost`**: Optional field. When backend returns `PRICE_CONFIRMATION_REQUIRED`, the client must resubmit with `confirm_unit_cost` exactly matching `unit_cost`.
- **`BatchSupplierInvoiceBody.confirmations`**: Optional list of `{ item_id, unit_cost_base }` for each line needing confirmation when batching supplier invoices.

### Error Response Format

```json
{
  "detail": {
    "code": "PRICE_CONFIRMATION_REQUIRED",
    "message": "Item has a floor price. Please re-enter the unit cost to confirm.",
    "floor_price": 200,
    "margin_below_standard": true,
    "expected_unit_cost": 150
  }
}
```

For supplier invoice batch, the `items` array lists each line needing confirmation:

```json
{
  "detail": {
    "code": "PRICE_CONFIRMATION_REQUIRED",
    "message": "Some items have a floor price or margin below standard...",
    "items": [
      {
        "item_id": "uuid",
        "item_name": "Item Name",
        "unit_cost_base": 150,
        "floor_price": 200,
        "margin_below_standard": false
      }
    ]
  }
}
```

### Frontend

1. **Adjust Stock Modal**: On first submit, if `PRICE_CONFIRMATION_REQUIRED` is returned, a warning section appears in the modal asking the user to re-enter the unit cost. They must type the same value to confirm awareness.
2. **Supplier Invoice Batch**: On first batch attempt, if any lines need confirmation, a modal lists each item with an input to re-enter the unit cost. User clicks "Confirm & Batch" to resubmit with confirmations.

## Files Modified

- `backend/app/services/pricing_config_service.py` – `check_stock_adjustment_requires_confirmation`
- `backend/app/schemas/item.py` – `confirm_unit_cost` on `AdjustStockRequest`
- `backend/app/schemas/purchase.py` – `BatchSupplierInvoiceBody`, `BatchLineConfirmation`
- `backend/app/api/items.py` – floor/margin check in `adjust_stock`
- `backend/app/api/purchases.py` – pre-pass and confirmation validation in `batch_supplier_invoice`
- `frontend/js/pages/inventory.js` – confirmation section in adjust-stock modal
- `frontend/js/pages/purchases.js` – `showBatchPriceConfirmationModal`, `batchSupplierInvoice` with confirmations
- `frontend/js/api.js` – `batchInvoice(invoiceId, body)` accepts optional body
