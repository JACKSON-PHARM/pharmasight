# pack_size in valuation / report queries — audit

Single-purpose audit: **every place `pack_size` appears in valuation or report code paths**. No code changed.

---

## 1. Dashboard total-value (Stock Value KPI)

**Endpoint:** `GET /api/inventory/branch/{branch_id}/total-value`  
**Function:** `get_total_stock_value()` in `pharmasight/backend/app/api/inventory.py`

**Result:** **`pack_size` does not appear.**  
Valuation is layer-based: `SUM(remaining_qty * unit_cost)` per layer; no item join, no `pack_size` used.

---

## 2. Current Stock / Valuation report

**Endpoint:** `GET /api/inventory/valuation` (branch_id, as_of_date, valuation, stock_only)  
**Function:** `get_stock_valuation()` in `pharmasight/backend/app/api/inventory.py`

### 2a. Cost used for value (unit_cost and value columns)

Cost comes from **`CanonicalPricingService.get_cost_per_retail_for_valuation_batch()`** (see section 3).  
`get_stock_valuation` itself does **not** use `pack_size` for the cost or value calculation; it only uses the per-retail cost returned by that helper.

### 2b. pack_size used for display only (stock_display)

**File:** `pharmasight/backend/app/api/inventory.py`  
**Lines:** 567–577 (inside the loop that builds `result_rows`)

```python
# Build stock_display from item + qty (avoid N+1 get_stock_display)
if stock_qty > 0:
    wu = _unit_for_display(getattr(item, "wholesale_unit", None), "piece")
    ru = _unit_for_display(getattr(item, "retail_unit", None), "piece")
    su = _unit_for_display(getattr(item, "supplier_unit", None), "piece")
    pack = max(1, int(getattr(item, "pack_size", None) or 1))   # <-- pack_size HERE
    wups = max(0.0001, float(getattr(item, "wholesale_units_per_supplier", None) or 1))
    u_per_supp = pack * wups
    supp_whole = int(stock_qty // u_per_supp) if u_per_supp >= 1 else 0
    rem = stock_qty - (supp_whole * u_per_supp)
    wholesale_whole = int(rem // pack) if pack >= 1 else 0
    retail_rem = int(rem % pack) if pack >= 1 else int(stock_qty)
    # ... parts for "5 packet + 5 capsule" style string
```

**Purpose:** Build the human-readable `stock_display` string (e.g. "5 packet + 5 capsule").  
**Effect on valuation:** None. Used only for display; `unit_cost` and `value` are already set from `cost_per_retail` (section 3).

---

## 3. Cost per retail for valuation (source of unit_cost and value)

**Function:** `CanonicalPricingService.get_cost_per_retail_for_valuation_batch()`  
**File:** `pharmasight/backend/app/services/canonical_pricing.py`  
**Called by:** `get_stock_valuation()` (Current Stock report). Not used by dashboard total-value.

### 3a. Last PURCHASE path — no pack_size

**Lines:** 294–318  

- Takes last **PURCHASE** ledger row per item (`transaction_type == "PURCHASE"`, `quantity_delta > 0`).
- Uses `InventoryLedger.unit_cost` as-is (docstring: “already per retail”).
- **`pack_size` is not used.**

### 3b. Fallback for items with no PURCHASE — pack_size used

**Lines:** 320–331  

```python
# 2) OPENING_BALANCE / weighted avg / default: cost is per WHOLESALE → divide by pack_size
missing = [iid for iid in item_ids if iid not in result]
if missing:
    cost_raw = CanonicalPricingService.get_best_available_cost_batch(
        db, missing, branch_id, company_id
    )
    for iid in missing:
        cost = cost_raw.get(iid) or Decimal("0")
        item = items.get(iid)
        pack_size = max(1, int(getattr(item, "pack_size", None) or 1))   # <-- pack_size HERE
        result[iid] = cost / Decimal(str(pack_size))
```

**Intent (docstring):** For items with no last PURCHASE, treat “cost” as per **wholesale** and convert to per retail: `cost_per_retail = cost / pack_size`.

**What `get_best_available_cost_batch` actually returns (same file, ~179–273):**

1. **Last PURCHASE** from ledger → `unit_cost` (per **retail** in current design).
2. **OPENING_BALANCE** from ledger → `unit_cost` (docstrings say per **wholesale** for opening).
3. **Weighted average** over ledger (qty×cost/sum qty) → unit depends on how ledger was written.
4. **Item.default_cost_per_base** → per **retail** (base).

So “missing” items (no last PURCHASE) can get cost from (2) OPENING_BALANCE, (3) weighted avg, or (4) default_cost_per_base. The code **always** does `cost / pack_size` for every missing item.

- **OPENING_BALANCE:** Dividing by `pack_size` is correct if opening balance cost is stored per wholesale.
- **default_cost_per_base:** Already per retail; dividing by `pack_size` is **wrong** and understates cost (e.g. 0.04 → 0.0004 when pack_size=100).
- **Weighted average:** Depends on whether ledger rows are per retail or wholesale; one rule for all can be wrong.

So the only place `pack_size` affects **valuation/report numbers** (unit_cost and value) is this fallback in `get_cost_per_retail_for_valuation_batch`. The assumption “cost is per wholesale” does not hold for `default_cost_per_base` (and possibly for some wavg cases), which can explain incorrect report totals and odd unit costs for items with no purchase history.

---

## 4. Summary table

| Location | File | Use of pack_size | Affects valuation/report number? |
|----------|------|-------------------|-----------------------------------|
| Dashboard total-value | `api/inventory.py` | Not used | N/A |
| Current Stock report – cost/value | `api/inventory.py` | Not used (cost from canonical_pricing) | N/A |
| Current Stock report – stock_display | `api/inventory.py` ~571 | `pack = pack_size` for “5 packet + 5 capsule” | No (display only) |
| Cost per retail (PURCHASE path) | `canonical_pricing.py` | Not used | N/A |
| Cost per retail (fallback path) | `canonical_pricing.py` ~330–331 | `result[iid] = cost / pack_size` | **Yes** – wrong when cost is already per retail (e.g. default_cost_per_base) |

---

## 5. Conclusion

- **Valuation/report queries:** `pack_size` appears in exactly two places:
  1. **inventory.py** – building `stock_display` only (no effect on unit_cost or value).
  2. **canonical_pricing.py** – fallback of `get_cost_per_retail_for_valuation_batch`: divide by `pack_size` for all items that have no last PURCHASE.

- **Likely bug:** That fallback assumes every such cost is per wholesale. For items whose cost comes from **default_cost_per_base** (and possibly some weighted-avg cases), cost is already per retail; dividing by `pack_size` understates cost and report value and can make “unit cost” look nonsensical (e.g. 0.04 → 0.0004 for pack_size 100).

**Recommended next step:** In `get_cost_per_retail_for_valuation_batch`, only apply `cost / pack_size` when the cost source is OPENING_BALANCE (or another source known to be per wholesale). Do **not** divide by `pack_size` when the source is `default_cost_per_base` (and clarify/document the unit for weighted average and use pack_size only when appropriate).
