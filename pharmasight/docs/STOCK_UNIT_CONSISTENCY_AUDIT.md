# Stock Unit Consistency Audit Report

**System:** PharmaSight multi-branch pharmacy ERP  
**Objective:** Determine whether stock is stored, returned, and displayed in a consistent unit (base/retail) across ledger, APIs, and frontend; identify where it appears as packets/cases incorrectly.  
**Audit type:** Analysis only — no code or schema changes.

---

## Executive Summary

- **Ledger:** Stores and aggregates in **base (retail) units** only. No division by pack_size at persistence or in `get_current_stock`.
- **APIs:** All stock-returning endpoints use `SUM(quantity_delta)` or `inventory_balances.current_stock` (both base units). **Inconsistency:** Response field `base_unit` is the **wholesale** unit name (e.g. "packet"), not retail. When the frontend shows `current_stock + base_unit`, it displays e.g. "98 packet" although 98 is **tablets** — a **labeling bug**.
- **Frontend:** Does not divide stock by pack_size. It assumes `current_stock` is a number and uses `stock_display` when present, else `current_stock + base_unit`. The **wrong** display occurs when (1) `stock_display` is missing or is the raw number string (e.g. fast path), and (2) `base_unit` is the wholesale name → "98 packet".
- **Root cause:** **D) UI labeling problem** plus one backend endpoint (**get_all_stock_overview**) that builds unit breakdown assuming stock is in wholesale units.

---

## STEP 1 — Ledger Semantics (Confirmed)

### 1.1 What the ledger stores

| Element | Source | Interpretation |
|--------|--------|----------------|
| `inventory_ledger.quantity_delta` | `backend/app/models/inventory.py` L32 | Numeric(20,4). Comment: "base units; fractional for retail". Post–migration 016: **base = retail** (e.g. tablet). |
| Balance computation | `InventoryService.get_current_stock()` | `func.coalesce(func.sum(InventoryLedger.quantity_delta), 0)` filtered by item_id, branch_id. Returns float. |
| Helper | `inventory_service.py` L29–46 | No division by pack_size. Sum is returned as-is. |

**Answers:**

- **Is current_stock always SUM(quantity_delta)?**  
  **Yes** wherever stock is computed from the ledger. Snapshot table `inventory_balances.current_stock` is maintained by `SnapshotService.upsert_inventory_balance(db, ..., quantity_delta)` so it is the same cumulative sum (increment/decrement by each ledger delta).

- **Is that sum always interpreted as base (retail)?**  
  **Yes.** Code and comments (e.g. `get_current_stock`: "Get current stock balance in base (retail) units"; `format_quantity_display`: "quantity (in retail/base units)") treat the sum as retail. No code path divides this sum by pack_size to convert to wholesale for storage or for the numeric value returned as "current_stock".

- **Is there any division by pack_size at backend level for the stock *value*?**  
  **No.** `pack_size` is used only to *format* the same base quantity into a 3-tier display string (e.g. "1 packet + 8 tablet") in `get_stock_display` / `format_quantity_display`. The numeric value returned as `current_stock` or `stock` is never divided by pack_size.

---

## STEP 2 — Stock-Returning Endpoints (Table)

| Endpoint | Field(s) | Raw Source | Converted? | Assumed Unit | Unit label sent |
|----------|----------|------------|------------|--------------|-----------------|
| `GET /items/search` (heavy) | `current_stock`, `stock_display` | `stock_map` from InventoryBalance or SUM(quantity_delta); `format_quantity_display(stock_qty, item)` for stock_display | No for value; yes for stock_display string only | Base (retail) | `base_unit` = item.base_unit (wholesale name) |
| `GET /items/search?fast=true` | `current_stock`, `total_stock`, `stock_display` | Same stock_map (base); `stock_display = str(int(total))` | No | Base | `base_unit`; stock_display is raw number string e.g. "98" |
| `POST /items/stock-batch` | `current_stock`, `stock_display` | InventoryBalance.current_stock; format_quantity_display(qty, item) | No for value | Base | Not returned; caller has item |
| `GET /items/{id}` (with branch_id) | `current_stock`, `stock_display` | get_current_stock; get_stock_display | No for value | Base | `base_unit` (item.base_unit = wholesale) |
| `GET /items/overview` (list) | `current_stock`, `stock_display` | SUM(quantity_delta) per item; format_quantity_display(stock_qty, item) when branch_id | No for value | Base | `base_unit` (wholesale) |
| `POST /items/adjust-stock` response | `quantity_delta`, `previous_stock`, `new_stock`, `new_stock_display` | get_current_stock before/after; get_stock_display for new_stock_display | No for values | Base | new_stock_display = 3-tier string |
| `GET /inventory/stock/{item_id}/{branch_id}` | (structure varies) | get_current_stock or SUM(quantity_delta) | No | Base | Depends on route |
| `GET /inventory/branch/{branch_id}/stock-overview` | `stock`, `stock_display`, `base_unit` | SUM(quantity_delta); **custom unit breakdown** in loop | **Yes, wrong** | **Treated as wholesale in breakdown** | `base_unit`; stock_display can be wrong (see below) |
| `GET /inventory/branch/{branch_id}/expiring-soon` | `quantity`, `quantity_display` | Batch aggregate SUM(quantity_delta); format_quantity_display(qty_retail, item) | No for quantity; display only for string | Base | quantity_display correct |
| Order book (single/bulk/list) | `current_stock` | SUM(InventoryLedger.quantity_delta) or snapshot | No | Base | None |
| Stock take (counts, session) | `system_quantity`, `current_stock` | get_current_stock | No | Base | N/A |
| Reports (item movement, batch movement) | Ledger rows, running balance | quantity_delta, SUM(quantity_delta) | No | Base | N/A |
| Item availability / check-availability | available_base, required_base | get_current_stock, convert_to_base_units | No for stock value | Base | N/A |

**Critical detail — `GET /inventory/branch/{branch_id}/stock-overview`** (`get_all_stock_overview`):

- **File:** `backend/app/api/inventory.py` L373–397.
- **Raw source:** `stock = stock_map.get(item.id, 0)` from `SUM(InventoryLedger.quantity_delta)` → value is **base (retail)**.
- **Bug:** Unit breakdown is built with `units_list = [(wholesale_name, 1.0), (retail_name, 1.0/pack), (supplier_name, wups)]`. The first tier has multiplier **1.0**, so the code treats `stock` as **wholesale** units. For 98 tablets (pack=10), it produces e.g. "9 carton, 8 packet" instead of "9 packet, 8 tablet". So **stock_display and unit_breakdown from this endpoint are wrong** when pack_size > 1.
- **Fallback:** `f"{stock} {item.base_unit}"` (L415) again pairs base quantity with wholesale label → "98 packet".

---

## STEP 3 — Frontend Display Logic

### 3.1 Use of pack_size / base_unit / stock

- **Frontend does not convert stock by pack_size** for display. No `current_stock / pack_size` or similar.
- **Display pattern:** Prefer `stock_display`; if missing, use `current_stock + ' ' + base_unit`.
- **base_unit in API:** Comes from `item.base_unit`, which in the schema is the **wholesale** unit name (model comment: "base_unit = wholesale_unit (reference unit)").

### 3.2 By screen

| Screen / Component | Stock source | Display logic | Assumption |
|--------------------|-------------|---------------|------------|
| Item search (items.js / inventory.js) | search result: current_stock, stock_display, base_unit | formatStockCell: stock_display \|\| (current_stock + ' ' + base_unit) | If stock_display present, correct 3-tier; else **number is base but label is wholesale** → "98 packet". |
| Item list table (Items page) | Same | formatStockCell | Same. "Base unit" column shows item.base_unit (wholesale name). |
| Stock adjustment modal (inventory.js) | get(itemId, branchId): current_stock, stock_display | currentStockDisplay = stock_display \|\| (current_stock + ' ' + base_unit) | Same risk when stock_display missing. |
| Global item search | search: stock_display, current_stock | stockStr = stock_display \|\| String(current_stock) | Raw number with no unit when stock_display is "98" (fast path). |
| TransactionItemsTable (sales) | item.stock_display, item.available_stock (= current_stock) | "Stock: " + stock_display or available_stock | Prefers stock_display; no division by pack_size. |
| Dashboard (expiring soon, etc.) | quantity_display or quantity + base_unit | quantity_display \|\| (quantity + ' ' + base_unit) | quantity is base; base_unit from API can be wholesale. |
| Stock take item list | item.current_stock | `${item.current_stock \|\| 0}` in table; no unit in cell | Raw number; unit in adjacent column (base_unit). |
| Purchases (order book entry) | entry.current_stock | `${entry.current_stock \|\| 0}` | Raw number, no unit label. |
| Reports | stock_display or stock + base_unit | Same pattern | Same labeling risk. |
| itemMapper.js formatStockCell | stock_availability.unit_breakdown \|\| stock_display \|\| (current_stock + ' ' + base_unit) | Three-tier \|\| 3-tier string \|\| number + base_unit | Same: number always base; base_unit can be wholesale. |

### 3.3 Conclusion (frontend)

- **Does frontend convert stock?** No (no division by pack_size).
- **Assume wholesale?** No; it uses the numeric value as returned.
- **Assume base?** Yes for the **number**; it does not re-interpret it as wholesale.
- **Inconsistent conversion across pages?** Inconsistent **labeling**: when `stock_display` is absent or is a raw number, pages that append `base_unit` show "98 packet" (98 base with wholesale label). When `stock_display` is the proper 3-tier string, they show "1 packet 8 tablet" or "98 tablet". So the **same** base quantity is sometimes labeled as retail (correct) and sometimes as wholesale (incorrect) depending on whether `stock_display` is present and correct.

---

## STEP 4 — Mismatch Scenarios (Exact Files and Lines)

### Scenario A: Backend returns base = 100 tablets; one page shows "100", another "10", another "100 packet"

- **"100" only:** When `stock_display` is the raw number (e.g. fast path `str(int(total))`).  
  - **Backend:** `items.py` L537 (fast path): `"stock_display": str(int(total))` — no unit in string.  
  - **Frontend:** global_item_search.js L71: `stockStr = item.stock_display != null ? item.stock_display : String(item.current_stock)` → "100" with no unit.

- **"10" (wrong):** Not observed. No frontend or backend divides current_stock by pack_size for display.

- **"100 packet" (wrong label):** When frontend shows `current_stock + ' ' + base_unit` and API sends `base_unit = "packet"` (wholesale).  
  - **Backend:** Item response uses `item.base_unit` (wholesale unit name), e.g. items.py L746, L1219; schema item.py L159: "current_stock in base units" but base_unit is not defined as retail in response.  
  - **Frontend:** inventory.js L1352: `currentStockDisplay = (data.stock_display) ? ... : (data.current_stock + ' ' + (data.base_unit || ''))` → "100 packet".  
  - itemMapper.js L62–63: `formatStockCell` fallback `item.current_stock + ' ' + (item.base_unit || '')` → "100 packet".  
  - reports.js L442: `stockNum + ' ' + (it.base_unit || '')` when stock_display null.  
  - dashboard.js L357, L402: `r.quantity + ' ' + (r.base_unit || '')` for quantity_display fallback.

### Scenario B: Stock overview shows "10 packet" instead of "100 tablet"

- **Backend:** `inventory.py` L382–415 `get_all_stock_overview`.  
  - `stock` = SUM(quantity_delta) = 100 (base).  
  - Unit breakdown uses multipliers as if stock were in wholesale: first tier (wholesale) mult 1.0 → 100/1 = 100 "packet"; or with supplier first, 100/10 = 10 "carton". So **stock_display** can be "10 carton" or "100 packet" instead of "100 tablet" or "10 packet 0 tablet".  
  - **Exact lines:** L392 `units_list = [(wholesale_name, 1.0)]` (should be retail=1.0, wholesale=pack_size, etc.); L399–406 loop divides `remaining` by these multipliers; L415 fallback `f"{stock} {item.base_unit}"` → "100 packet".

### Scenario C: Stock adjustment page says "Current stock: 98 packet"

- **Backend:** GET /items/{id} returns `current_stock: 98`, `stock_display: InventoryService.get_stock_display(...)` (correct 3-tier). If branch_id missing or get_stock_display not set, frontend fallback.  
- **Frontend:** inventory.js L1352: when `data.stock_display` is falsy, `currentStockDisplay = String(data.current_stock) + ' ' + (data.base_unit || '')` → "98 packet".  
- **File:line:** `frontend/js/pages/inventory.js` L1352.

### Summary table (files/lines)

| Observation | File | Line(s) |
|-------------|------|--------|
| API returns base_unit = wholesale name | backend model item.py, items API responses | item base_unit column; items.py 746, 811, 1219 |
| Fallback display "N base_unit" (wrong when base_unit is wholesale) | frontend/js/pages/inventory.js | 1352 |
| Same fallback | frontend/js/utils/itemMapper.js | 62–63 |
| Same fallback | frontend/js/pages/reports.js | 442 |
| Same fallback | frontend/js/pages/dashboard.js | 357, 402 |
| Stock overview wrong unit breakdown (treats stock as wholesale) | backend/app/api/inventory.py | 382–415 |
| Fast path returns stock_display as raw number (no unit) | backend/app/api/items.py | 537 |
| Global search shows stock with no unit when stock_display is number | frontend/js/components/global_item_search.js | 71, 153 |

---

## STEP 5 — Root Cause Classification

**Primary: D) UI labeling problem**

- The **numeric** value is base (retail) everywhere: ledger, snapshot, and every endpoint that returns `current_stock` or `stock`.
- The **label** sent and used for that number is often `base_unit`, which in the schema is the **wholesale** unit name. So the same number is correctly "98 tablets" when shown via `stock_display` and incorrectly "98 packet" when shown as `current_stock + base_unit`.

**Secondary: B) Backend inconsistent conversion**

- One endpoint builds a wrong display: **get_all_stock_overview** (inventory.py) builds unit breakdown assuming stock is in wholesale units (multiplier 1.0 for wholesale), so `stock_display` and any list built from it (e.g. dashboard stock overview) can show "X packet" or "X carton" instead of the correct 3-tier breakdown in retail.

**Not A:** Ledger does not store mixed units.  
**Not C:** Frontend does not perform conversion (no division by pack_size); it only displays what the API sends and mislabels when using base_unit as the suffix.

---

## STEP 6 — Recommendations

### 6.1 Where conversion should happen

- **Backend:** Remain the single place that knows item units and pack_size. All stock **values** should stay in base (retail). Any display string (stock_display, quantity_display) should be built in the backend using the same 3-tier logic as `InventoryService.format_quantity_display` / `get_stock_display`.
- **Frontend:** Should not convert quantities. It should only display:
  - A **display string** from the API when present (stock_display, quantity_display), or
  - A numeric value with an **explicit retail unit label** when the API sends one (see below).

### 6.2 What the backend should return

- **Always return stock in base (retail) units** for the numeric field(s). No change to current behaviour.
- **Always return a display string** (e.g. `stock_display`) for every stock-returning endpoint when branch/item context exists, using `InventoryService.format_quantity_display(get_current_stock(...), item)` (or equivalent) so that the label is never ambiguous.
- **Fix get_all_stock_overview** so its unit breakdown uses the same semantics as `format_quantity_display`: input is retail; multipliers to base are retail=1, wholesale=pack_size, supplier=pack_size*wups; then break down total_retail into supplier_whole, wholesale_whole, retail_remainder. Replace the current loop (L382–415) with logic consistent with `inventory_service.get_stock_display` / `format_quantity_display`, or call those helpers.

### 6.3 Unit labels in the response

- **Avoid using `base_unit` as the label for `current_stock`** when `base_unit` is the wholesale unit name. Either:
  - Document that `base_unit` is the wholesale/reference unit name and **not** the unit of `current_stock`, and add a dedicated **retail_unit** (or `stock_unit`) in the response for labeling the numeric stock (e.g. "tablet", "piece"); or
  - Always provide `stock_display` so the frontend does not need to fall back to `current_stock + base_unit`.

### 6.4 Optional: structured stock response

For clarity and to avoid future misuse, the API can expose a single, explicit shape for “stock at branch”:

```json
{
  "base_quantity": 98,
  "base_unit": "tablet",
  "stock_display": "9 packet + 8 tablet",
  "wholesale_quantity": 9,
  "wholesale_unit": "packet",
  "supplier_quantity": 0,
  "supplier_unit": "carton"
}
```

- `base_quantity` = current_stock (retail); `base_unit` = item.retail_unit (e.g. "tablet") so the numeric value is unambiguously labeled.
- `stock_display` = existing 3-tier string.
- Optional: wholesale_quantity = base_quantity / pack_size (for display only), supplier_quantity similarly, with their unit names.

This is the **cleanest, lowest-risk** way to prevent “98 packet”: the frontend always has a correct label for the base quantity and a ready-made display string; no reliance on the old `base_unit` (wholesale name) for labeling stock.

### 6.5 Minimal quick fixes (no new structure)

1. **Backend:** In `get_all_stock_overview`, build unit breakdown from **retail** stock (same logic as `format_quantity_display`), or call `InventoryService.format_quantity_display(stock, item)` and return that as `stock_display`. Remove the custom loop that uses (wholesale_name, 1.0).
2. **Backend:** In item/search and item GET responses, add a field e.g. `retail_unit` (or `stock_unit`) = item.retail_unit for use when displaying `current_stock`. Document that `base_unit` is the wholesale/reference unit name and must not be used as the unit for `current_stock`.
3. **Frontend:** Where fallback is `current_stock + ' ' + base_unit`, use `retail_unit` (or `stock_unit`) when present, and only fall back to `base_unit` when retail_unit is missing (legacy).
4. **Backend:** Ensure fast path search (and any path that omits full item) still returns a proper `stock_display` (e.g. by loading item for stock_display or by returning at least `retail_unit` and documenting that the number is in that unit).

---

*End of audit. No code or schema was modified.*
