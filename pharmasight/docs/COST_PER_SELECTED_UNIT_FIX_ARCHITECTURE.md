# Cost per Selected Unit Consistency — Analysis & Architecture

## Summary

PharmaSight stores all inventory cost as **base unit cost** (cost per retail unit, e.g. per tablet). When the user selects a different unit (e.g. Packet, Box), the UI must **display and accept cost in that selected unit**, then **convert to base unit cost** before sending to the backend. This document identifies affected modules, current behaviour, and the proposed fix.

---

## Core System Rule (unchanged)

- **Storage:** `inventory_ledger.unit_cost` and all cost fields = cost per **base (retail) unit**.
- **Quantities:** Stored in base units; conversion is only for display and input.
- No separate storage for “packet cost” or “box cost”; everything normalizes to base.

---

## Affected Modules

| Module | File(s) | Cost field / behaviour |
|--------|---------|------------------------|
| **Adjust Stock** | `frontend/js/pages/inventory.js` | `adjustStockCost` — currently always shows base unit cost; does not update when unit selector changes. **Broken.** |
| **Cost & Metadata Adjustment** | `frontend/js/pages/inventory.js` | Cost adjustment: user picks Wholesale vs Retail; conversion when submitting. **Bug:** wholesale→base conversion is wrong (multiplies instead of divides). |
| **Purchase (GRN)** | `backend/app/api/purchases.py`, `frontend/js/components/TransactionItemsTable.js` | Backend expects **cost per selected unit** and converts to base (`unit_cost_base = unit_cost / multiplier`). Table shows `unit_price = baseCost * mult` and recalculates on unit change. **Correct.** |
| **Supplier Invoice** | `backend/app/api/purchases.py`, `frontend/js/pages/purchases.js`, `TransactionItemsTable.js` | Backend expects **unit_cost_exclusive** in selected unit; divides by multiplier to get base. Frontend sends `item.unit_price` (per selected unit). **Correct.** |

---

## Files Responsible for Cost Display and Unit Selection

### Adjust Stock

- **`pharmasight/frontend/js/pages/inventory.js`**
  - `showAdjustStockModal(itemId)` (≈1337–1524): builds modal; `lastCost` from item (base unit); cost input initialised with `lastCost`; label “Unit cost (per base unit)”.
  - `unitMultiplierMap` and `updateImpactPreview()`: used for **quantity** preview only; cost is not tied to selected unit.
  - `submitAdjustStock(itemId)` (≈1528–1674): reads `adjustStockCost` and sends as `unit_cost` in payload. Backend uses it as base unit cost.

- **Backend:** `backend/app/api/items.py` `adjust_stock` (≈1063–1316), `backend/app/schemas/item.py` `AdjustStockRequest.unit_cost` (“Cost per base unit”). Backend is correct; no change.

### Cost & Metadata Adjustment

- **`pharmasight/frontend/js/pages/inventory.js`**
  - `updateCostAdjustmentUnitUI()`, `loadBatchesForAdjustmentItem()`, cost adjustment submit (≈2045–2210).
  - User selects “Wholesale” or “Retail”. On submit: if `unitKind === 'retail'` then `newCost = newCostRaw * pack_size` (wrong: that converts retail→wholesale; backend expects base = retail).

- **Backend:** `backend/app/api/items.py` `post_cost_adjustment` expects `new_unit_cost` = cost per base (retail) unit. No change.

### Purchase / Supplier Invoice

- **`pharmasight/frontend/js/components/TransactionItemsTable.js`**
  - Purchase mode: `item.unit_price = baseCost * mult` (cost per selected unit); `recalcAddRowPriceFromBasis()` and `updateAddRowFromDom()` recalc on unit change.
  - Payloads send `unit_price` / `unit_cost_exclusive` as displayed (per selected unit).
- **`pharmasight/frontend/js/pages/purchases.js`**: maps `item.unit_price` → `unit_cost_exclusive` for invoice; GRN payload uses same table item shape.
- **Backend:** `purchases.py` uses `unit_cost / multiplier` or `unit_cost_exclusive / multiplier` to get base. No change.

---

## Current Cost Calculation Logic

### Adjust Stock (current — wrong)

1. Modal opens: cost input = `lastCost` (from item’s default_cost / default_cost_per_base = base unit).
2. User changes unit (e.g. to Packet): cost input **unchanged**; still shows base unit cost.
3. User may type “270” thinking it’s per packet; backend treats 270 as per base unit → wrong.
4. Submit: `payload.unit_cost = parseFloat(costEl.value)`; backend uses as base unit cost.

### Cost & Metadata Adjustment (current — wrong for wholesale)

- Backend expects `new_unit_cost` = cost per **base (retail)** unit.
- If user selects “Retail”: enters cost per tablet → should send as-is. Code does `newCost = newCostRaw * pack_size` when `unitKind === 'retail'` → wrong (sends 2.7×100 = 270).
- If user selects “Wholesale”: enters cost per packet → should send `newCostRaw / pack_size`. Code does not divide; only multiplies when retail → wrong.

### Purchase / Supplier Invoice (current — correct)

- Table: cost per selected unit = `baseCost * mult`; on unit change, price is recalculated from basis.
- Backend: receives cost per selected unit; converts to base with `/ multiplier`.

---

## Proposed Fix Architecture

### 1. Adjust Stock (`inventory.js`)

- **State:** Keep `baseUnitCost` (from API) in closure or data attributes when opening the modal (same as current `lastCost`).
- **Display:**
  - Add a cost **label** that depends on selected unit, e.g. “Unit cost (per [base unit])” vs “Unit cost (per packet)”.
  - When **unit selector changes**:  
    `displayCost = baseUnitCost × selectedUnitMultiplier`  
    and set the cost input value to `displayCost`. Update the label to “Unit cost (per [selected unit name])”.
  - On first load, if the first option is base unit (multiplier 1), show `baseUnitCost`; if first option is packet, show `baseUnitCost × packSize`.
- **Save:**
  - Before building payload:  
    `base_unit_cost = displayCost / selectedUnitMultiplier`  
    (if multiplier 0 or missing, treat as 1).  
    Send `payload.unit_cost = base_unit_cost` so backend still receives cost per base unit.
- **Confirmation flow (PRICE_CONFIRMATION_REQUIRED):**  
  Backend returns `expected_unit_cost` in **base** unit. When showing the confirmation input, show expected value in the **current selected unit** (expected_base × multiplier) so the user re-enters in the same unit they’re working in. On resubmit, convert confirmed value back to base (divide by multiplier) and send as `confirm_unit_cost`.

### 2. Cost & Metadata Adjustment (`inventory.js`)

- Backend expects **cost per base (retail) unit**.
- **Rule:**  
  - If user chose **Retail**: value entered is per tablet → send as-is: `newCost = newCostRaw`.  
  - If user chose **Wholesale**: value entered is per packet → convert to per tablet: `newCost = newCostRaw / pack_size`.
- Remove the incorrect `newCost = newCostRaw * pack_size` when `unitKind === 'retail'`.

### 3. Purchase / Supplier Invoice

- No code change: already display and send cost per selected unit; backend converts to base.

### 4. Shared utility (optional)

- A small helper in `inventory.js` (or a shared util) can encapsulate:
  - `displayCost = baseUnitCost * selectedMultiplier`
  - `baseUnitCost = displayCost / selectedMultiplier`
- Same logic can be used by Adjust Stock and, if needed later, by any other module that adds unit-aware cost editing. No new shared module is strictly required for this fix; the logic is minimal and can live next to the adjust-stock and cost-adjustment code.

---

## Implementation Checklist

- [x] **Adjust Stock:** Store base unit cost; on unit change update cost input and label; on submit convert display cost to base and send; handle confirmation in selected unit and convert `confirm_unit_cost` to base.
- [x] **Cost & Metadata Adjustment:** Send retail as-is; convert wholesale to base by dividing by `pack_size`.
- [x] **Backend:** No change (already base-unit only).
- [x] **Purchase / Supplier Invoice:** No change (already correct).

---

## Guardrails (do not change)

- Do not change inventory storage model or base-unit architecture.
- Do not introduce separate cost storage for packets/boxes.
- Do not change quantity conversion logic.
- Do not change sales module behaviour.
