# Dashboard Inventory Valuation — Identity Audit

## 1. File and function responsible for dashboard valuation

| Item | Value |
|------|--------|
| **File** | `pharmasight/backend/app/api/inventory.py` |
| **Function** | `get_total_stock_value(branch_id, ...)` |
| **Endpoint** | `GET /api/inventory/branch/{branch_id}/total-value` |
| **Dashboard usage** | `API.inventory.getTotalStockValue(branchId)` → displays `d.total_value` in "Stock Value (KES)" card |
| **Frontend** | `frontend/js/pages/dashboard.js` (branchId from `getBranchIdForStock()`) |

---

## 2. Current valuation logic — remaining layers

- **Remaining per layer:** `remaining_qty = SUM(quantity_delta)` over all ledger rows in that layer. **Confirmed.**
- **Valuation:** `stock_value = SUM(remaining_qty * unit_cost)` for layers with `remaining_qty > 0`. **Confirmed.**
- Negative layers are excluded: only `if remaining > 0` is added to total. **Confirmed.**

---

## 3. Current layer identity (grouping)

**Documented in code (docstring):**  
`(item_id, branch_id, batch_number, expiry_date, unit_cost)`

**Actually used in code (line 330):**  
`key = (r.item_id, batch_key, expiry_key, cost_key)`  
→ **(item_id, batch_number, expiry_date, unit_cost)**

**Gap:** `company_id` and `branch_id` are **not** part of the grouping key in the implementation, even though the docstring mentions branch_id.

---

## 4. Tenant and branch safety

**Filtering (lines 316–320):**

- `InventoryLedger.item_id.in_(company_item_ids)` — items scoped to `branch.company_id` ✓  
- `InventoryLedger.branch_id == branch_id` ✓  
- `InventoryLedger.company_id == branch.company_id` ✓  

So **tenant (company_id) and branch (branch_id) are enforced in the query filter**. All rows in the loop belong to one company and one branch.

**Current API contract:** The route requires a single `branch_id` (path parameter). The dashboard always calls with one branch (session/selected branch). There is no "all branches" endpoint today.

---

## 5. Risk if branch_id (and company_id) are missing from layer grouping

- **Today:** No functional bug. The query restricts to one branch and one company, so every row has the same `branch_id` and `company_id`. The result is correct for the single-branch dashboard.
- **Future / analytics:**
  - If a future "all branches" view (or analytics) passes multiple branches or omits the branch filter, and reuses the same aggregation logic, layers from different branches would be merged because the key does not include `branch_id` (or `company_id`).
  - Layer identity would be under-specified: same (item_id, batch_number, expiry_date, unit_cost) in two branches would be treated as one layer.
- **Conclusion:** For current behavior, filtering is sufficient. For correct **layer identity** and safe reuse (e.g. all-branches, analytics), the grouping key should explicitly include **company_id** and **branch_id**.

---

## 6. Multi-batch and cost adjustment behavior

- **Multi-batch:** Layers are grouped by (item_id, batch_number, expiry_date, unit_cost). Different batches (e.g. Batch A 20 @ 20, Batch B 50 @ 24) are separate layers and valued as 20×20 + 50×24. **Confirmed.**
- **Negative layers:** Only layers with `remaining > 0` contribute. **Confirmed.**
- **Cost adjustment:** Cost adjustments update `ledger_row.unit_cost` in place. The key includes `unit_cost`, so the updated cost is used when grouping. **Confirmed.** No change to cost adjustment or ledger logic required.

---

## 7. Minimal correction — enforce full identity in grouping

**Required identity:**  
(company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)

**Change:** Include `company_id` and `branch_id` in the layer key in `get_total_stock_value`.

- Use `branch.company_id` and `branch_id` (already in scope).
- Key becomes: `(company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)`.

**Effect:**

- Result for the current API is unchanged (single branch + single company → same key shape, same totals).
- FIFO, cost adjustments, batch valuation, and ledger behavior are unchanged.
- Layer identity is explicit and safe for future all-branches or multi-branch analytics.

---

## 8. Summary

| Check | Status |
|-------|--------|
| Endpoint location | `inventory.py` → `get_total_stock_value` → `GET .../branch/{branch_id}/total-value` ✓ |
| remaining_qty = SUM(quantity_delta) by layer | ✓ |
| Grouping in code | (item_id, batch_number, expiry_date, unit_cost) — missing company_id, branch_id in key |
| company_id / branch_id in filter | ✓ Enforced in query |
| branch_id in grouping key | ✗ Missing (add for identity) |
| company_id in grouping key | ✗ Missing (add for identity) |
| Multi-batch valuation | ✓ Correct |
| remaining > 0 only | ✓ Correct |
| Cost adjustment (updated unit_cost) | ✓ Reflected in grouping |
| Proposed fix | Add company_id and branch_id to layer key only |
