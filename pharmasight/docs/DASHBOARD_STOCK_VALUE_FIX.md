# Dashboard Stock Value Fix — Deliverables

## 1. File and function responsible for the metric

- **File:** `pharmasight/backend/app/api/inventory.py`
- **Function:** `get_total_stock_value(branch_id, ...)`
- **Endpoint:** `GET /api/inventory/branch/{branch_id}/total-value`
- **Consumer:** Dashboard loads it via `API.inventory.getTotalStockValue(branchId)` and displays `d.total_value` in the "Stock Value (KES)" card.

---

## 2. Correct valuation rule (current implementation)

**Rule:**  
`stock_value = SUM(remaining_qty * base_unit_cost)` where:
- **remaining_qty** = current quantity remaining in each batch layer (not raw movements).
- **base_unit_cost** = cost per base unit stored for that batch (after any cost adjustment).

The ledger records **movements** (`quantity_delta`), not current state. Valuing with `SUM(quantity_delta * unit_cost)` over all rows is wrong because:
- Cost adjustments change `unit_cost` in place (no new row; quantity_delta unchanged).
- FIFO sales create negative `quantity_delta` rows; we must value only **remaining** stock per layer.
- Returns and adjustments create mixed in/out movements; only net remaining per layer should be valued.

---

## 3. Table / model used: remaining per batch layer

- **Table:** `inventory_ledger` (model `InventoryLedger`).
- There is no separate “remaining quantity” table. Remaining per batch layer is **derived** by aggregating movements:
  - **Layer key:** `(item_id, branch_id, batch_number, expiry_date, unit_cost)`.
  - **Remaining:** `SUM(quantity_delta)` over all ledger rows in that layer.
- **Filters:** `branch_id`, `company_id`, and `item_id IN (company items)`.

Cost adjustments **update** the existing ledger row’s `unit_cost` (and `total_cost`) in place, so the layer’s `unit_cost` reflects the current batch cost.

---

## 4. Correct query / logic

1. Load ledger rows for the branch and company (items scoped to company).
2. Group by `(item_id, batch_number, expiry_date, unit_cost)`.
3. For each group: `remaining = SUM(quantity_delta)`.
4. For each group with `remaining > 0`: `total_value += remaining * unit_cost`.

So we **do not** use `quantity_delta` alone (no `SUM(quantity_delta * unit_cost)` over all rows). We first collapse to **remaining per layer**, then value only positive remaining at that layer’s cost.

**Implementation (Python):**  
Fetch rows (item_id, batch_number, expiry_date, unit_cost, quantity_delta). Aggregate in memory by layer key; sum quantity_delta per layer; then add `remaining * unit_cost` for layers with remaining > 0.

---

## 5. Multi-batch and cost adjustments

- **Multi-batch:** Each distinct (batch_number, expiry_date, unit_cost) is a layer. Different batches (and different cost layers within the same batch) are valued at their own `unit_cost`. Multi-batch items are valued correctly.
- **Cost adjustments:** `post_cost_adjustment` updates `ledger_row.unit_cost` (and `total_cost`) in place. The valuation logic groups by current `unit_cost`, so the updated batch is valued at the new cost.
- Valuation therefore matches batch layers and respects cost-only updates.

---

## 6. What was not changed

- Base-unit storage architecture
- Ledger structure (append-only movements; cost adjustment updates unit_cost in place as designed)
- Cost conversion logic
- Other endpoints (e.g. stock overview) that use their own aggregation
