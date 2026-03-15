# Dashboard and Current Stock Report — Analysis (No Code Yet)

This document captures what is happening for three issues you raised, so we can agree on behaviour before changing any code.

---

## 1. Dashboard has no branch selector (only date)

**Current behaviour**

- The dashboard uses a **date range** selector (Today / This week / etc.) and an **Apply** button to load metrics.
- There is **no branch selector** on the dashboard page.
- The **branch** used for stock-related KPIs (Stock Value, Items in stock, Expiring items) comes from the **same** context as the rest of the app:
  - `getBranchIdForStock()` in `frontend/js/pages/dashboard.js`:
  - Reads `BranchContext.getBranch()` (header/session), then `CONFIG.BRANCH_ID`, then `localStorage.pharmasight_config.BRANCH_ID`.
- So the dashboard always shows metrics for **one branch at a time** — the branch currently selected in the header (e.g. “Pharmasight Main Branch (HQ)”).
- There is **no “All branches”** option and no way on the dashboard to switch branch without changing the global branch in the header.

**Gap**

- Users cannot:
  - Choose “All branches” to see aggregated metrics across branches.
  - Choose a **specific branch** from the dashboard itself (they must use the header branch switcher).

**Conclusion**

- This is a **product/UX gap**, not a bug in the existing logic. The dashboard is “single-branch by current session”; adding branch scope (current / specific / all) would require explicit product/UI decisions and implementation.

---

## 2. Dashboard stock valuation (4.4M) “not true”

**Where the number comes from**

- The “Stock Value (KES)” card calls:
  - `API.inventory.getTotalStockValue(branchId)`  
  - → `GET /api/inventory/branch/{branch_id}/total-value`
- Backend: `get_total_stock_value()` in `pharmasight/backend/app/api/inventory.py`.

**How it’s calculated (current logic)**

- Valuation uses **remaining batch layers** from the inventory ledger:
  - Layer identity: `(company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)`.
  - For each layer: `remaining = SUM(quantity_delta)` over all ledger rows in that layer.
  - Only layers with `remaining > 0` are valued.
  - `total_value = SUM(remaining * unit_cost)` over those layers.
- **No date filter**: the endpoint uses **all** ledger rows for that branch (i.e. “current” state), not “as of” a date.
- So the 4.4M is the **current** inventory value at **layer cost** for the **current** branch.

**Why it might not match expectations**

1. **Different from “sum of Current Stock report”**  
   - The **Current Stock / Valuation** report (Inventory → Current Stock) uses a **different** endpoint and a **different** cost source:
     - Endpoint: `GET /api/inventory/valuation` (with branch_id, as_of_date, valuation, stock_only).
     - Cost: **one cost per item** from `CanonicalPricingService.get_cost_per_retail_for_valuation_batch()`:
       - “Last PURCHASE” from `InventoryLedger` (per retail unit), or
       - OPENING_BALANCE / pack_size for items with no purchase.
     - So the report does: **per item** `value = stock_qty * cost_per_retail` and sums those.
   - So we have:
     - **Dashboard**: `SUM(remaining_qty * unit_cost)` **per layer** (each batch at its own cost).
     - **Report**: `SUM(stock_qty * last_cost_per_item)` **per item** (one cost per item).
   - With multiple batches at different costs (e.g. old batch at 10, new at 24), the two totals can differ. So the dashboard 4.4M can be “correct” from a layer perspective while the report total is different (and vice versa).

2. **No “as of” date on the dashboard**  
   - Dashboard value is “now”; the report can use an `as_of_date`. So if the user expects “value as of today’s close” and the ledger has been updated since, the number can still feel wrong if they are mentally comparing to another source (e.g. report with a different date).

3. **Data or scope**  
   - If there are duplicate ledger rows, incorrect `unit_cost` in some batches, or the wrong branch is selected, the number would be wrong. That would require a data/audit check rather than a formula bug.

**What to verify before changing code**

- Compare **dashboard total** vs **report total** for the **same branch** and **same date** (e.g. run report “as of today” and sum the report’s “Value” column).
- If they differ: confirm whether the business rule is “layer-based (dashboard)” or “one cost per item (report)” and whether we want them to align (e.g. by making the dashboard use the same valuation as the report, or by adding a second KPI).
- If they match and 4.4M still “feels” wrong: check a few items in the ledger (batches, quantities, unit costs) and confirm there are no data issues or wrong branch.

---

## 3. Current Stock report vs search (AMPICLO-DAWA example)

**What the user sees**

- **Current Stock report** (screenshot 2):  
  - AMPICLO-DAWA 500MG CAPS 100’S  
  - Stock: 5 packet + 5 capsule  
  - Unit cost: **0.04**  
  - Value: **18.13**
- **Search (e.g. sales)** (screenshot 3):  
  - Same item, **Cost: Ksh 3.59** (and “3.5 cost per capsule” is described as making sense).

**How the Current Stock report gets its numbers**

- Endpoint: `GET /api/inventory/valuation` (branch, as_of_date, valuation, stock_only).
- Backend:
  - Stock per item: `SUM(quantity_delta)` up to `as_of_date` (no batch grouping in this step).
  - Cost: `get_cost_per_retail_for_valuation_batch()` → **last PURCHASE** from ledger (per **retail/base** unit), or OPENING_BALANCE-derived per retail.
  - So **unit_cost** in the response is **per base/retail unit** (e.g. per capsule).
  - **value** = `stock_qty * unit_cost` (both in base units).
- For 5 packets + 5 capsules with 100 capsules per packet:  
  - Base qty = 5×100 + 5 = **505** capsules.  
  - If cost per capsule = 0.0359: value = 505 × 0.0359 ≈ **18.13**. So **0.04** is a rounded “per capsule” cost and **18.13** is **total value** of that stock.

**Interpretation of “Value” and “Unit cost”**

- **Value 18.13** = total value of **all** that item’s stock (5 packets + 5 capsules), not “price of one packet”.
- **Unit cost 0.04** = cost **per capsule** (base unit). It is **not** “per packet”.
- So the report is internally consistent **if** we read “Unit cost” as “per base unit (capsule)”.

**Where search “Cost” comes from**

- Sales (and similar) search shows “Cost: Ksh 3.59” from the item’s `purchase_price` / `default_cost` / `last_unit_cost` in the API that serves the search (e.g. snapshot or items overview).
- Snapshot: `last_purchase_price` from ledger (per base unit).
- Items overview: `SupplierInvoiceItem.unit_cost_exclusive` (last invoice) or `CanonicalPricingService.get_best_available_cost` (per base unit).
- So **if** both are per base unit, we’d expect the same order of magnitude (e.g. 0.04 vs 3.59 would not both be “per capsule”).
- **3.59** is consistent with **cost per packet** (e.g. 0.0359 × 100 ≈ 3.59). So either:
  - The search (or the API it uses) is returning or displaying cost **per packet** in some path, or
  - The same underlying cost is shown in different units: report = per capsule (0.04), search = per packet (3.59).

**Why it feels out of sync**

- Report does **not** label the unit: it says “Unit cost” and “Value” without “per capsule” or “total”.
- So it’s easy to read:
  - **18.13** as “price of a packet” instead of “total value of 5 packets + 5 capsules”.
  - **0.04** as something vague instead of “per capsule”.
- In search, “Cost: Ksh 3.59” fits the user’s mental model (e.g. “about 3.5 per packet”), so the **same** underlying cost (0.0359 per capsule ≈ 3.59 per packet) appears in two different unit contexts and looks inconsistent.

**Conclusion for this item**

- The **math** in the report (value = stock × cost per base unit) is consistent.
- The **confusion** is mainly:
  - **Labelling**: “Unit cost” and “Value” don’t state the unit or “total”.
  - **Unit consistency**: Report shows base-unit cost (0.04); search may show packet cost (3.59). Same cost, different display unit.
- Before code changes, we should confirm:
  - In which unit the search is intended to show cost (per base vs per packet) and whether that’s consistent across APIs.
  - That the report should either:
    - Explicitly label “Unit cost (per [base unit])” and “Value (total)”, and/or
    - Optionally show cost in the same unit as the item’s common display (e.g. per packet) so it aligns with search.

---

## Summary table

| Issue | What’s happening | Next step (no code yet) |
|-------|-------------------|---------------------------|
| **1. No branch selector on dashboard** | Branch = session/header only; no “all” or branch dropdown on dashboard. | Decide: do we want branch scope (current / specific / all) on the dashboard? Then design UI and API. |
| **2. Dashboard 4.4M “not true”** | Dashboard = layer-based valuation (remaining × unit_cost per batch); report = one cost per item. No date filter on dashboard. | Compare dashboard total vs report total (same branch, same date). Decide which valuation rule is canonical and whether dashboard should match report or show a second metric. Optionally add as_of_date to dashboard. |
| **3. Report vs search (AMPICLO-DAWA)** | Report: unit_cost = per capsule (0.04), value = total (18.13). Search: cost 3.59 (likely per packet). Same cost, different units; report doesn’t label units. | Confirm search cost unit (per base vs per packet). Then: add labels (“per capsule”, “total”) and/or align display unit (e.g. show per packet in report where relevant). |

---

## Files involved (for when we implement)

- **Dashboard branch and KPIs**: `frontend/js/pages/dashboard.js` (`getBranchIdForStock`, card loading), `backend/app/api/inventory.py` (`get_total_stock_value`).
- **Current Stock report**: `frontend/js/pages/inventory.js` (Current Stock tab, Apply, table rendering), `backend/app/api/inventory.py` (`get_stock_valuation`), `CanonicalPricingService.get_cost_per_retail_for_valuation_batch`.
- **Search cost**: `backend/app/services/item_search_service.py`, snapshot (e.g. `last_purchase_price`), items overview (`default_cost` / `last_cost_map`), `frontend/js/components/TransactionItemsTable.js` (display of Cost).

No code has been changed; this document is for shared understanding and to decide next steps before implementation.
