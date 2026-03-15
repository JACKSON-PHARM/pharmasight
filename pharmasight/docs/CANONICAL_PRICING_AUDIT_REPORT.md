# Canonical Pricing Audit Report (No Code Changes)

**Scope:** CanonicalPricingService and related pricing helpers used by Current Stock Report, inventory valuation, and dashboard stock valuation.  
**Constraint:** Audit only — no modifications to canonical_pricing.py, inventory.py, reports, ledger, or transactions.

---

## 1. Pricing flow diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ DASHBOARD STOCK VALUATION (Stock Value KPI)                                       │
│ GET /api/inventory/branch/{branch_id}/total-value                               │
│ get_total_stock_value() — api/inventory.py                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
    │
    │  Does NOT use CanonicalPricingService.
    │  Reads InventoryLedger directly: SUM(remaining_qty × unit_cost) per layer.
    │  Ledger unit_cost used as-is (per retail).
    ▼
    [Layer aggregation: (company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)]
    → total_value = Σ (remaining × unit_cost) for layers with remaining > 0


┌─────────────────────────────────────────────────────────────────────────────────┐
│ CURRENT STOCK REPORT (Valuation report)                                           │
│ GET /api/inventory/valuation?branch_id=...&as_of_date=...&valuation=last_cost   │
│ get_stock_valuation() — api/inventory.py                                          │
└─────────────────────────────────────────────────────────────────────────────────┘
    │
    │  1) stock_map = SUM(quantity_delta) per item (up to as_of_date)
    │  2) cost_per_retail = CanonicalPricingService.get_cost_per_retail_for_valuation_batch(...)
    │  3) For each item: value = stock_qty × cost_per_retail[item_id]
    │  4) unit_cost and value in response = cost_per_retail and value from step 3
    ▼
    get_cost_per_retail_for_valuation_batch() — canonical_pricing.py
    │
    ├─ Path A: Item HAS last PURCHASE (ledger, transaction_type=PURCHASE, qty_delta>0)
    │     → result[item_id] = ledger.unit_cost   (no pack_size)
    │     → Unit: per retail ✓
    │
    └─ Path B: Item has NO last PURCHASE ("missing")
          → cost_raw = get_best_available_cost_batch(db, missing, branch_id, company_id)
          → result[iid] = cost_raw[iid] / pack_size   ← ONLY place pack_size used in cost
          → Unit: assumes cost_raw was "per wholesale" (see §3)
          → If cost_raw is actually per retail → result is wrong (over-division)


    get_best_available_cost_batch() — canonical_pricing.py (used only in Path B)
    │
    ├─ 1) Last PURCHASE (ledger)     → unit_cost as-is  → per retail (ledger convention)
    ├─ 2) OPENING_BALANCE (ledger)  → unit_cost as-is  → per retail (after migration)
    ├─ 3) Weighted average (ledger) → SUM(qty×cost)/SUM(qty) → same unit as ledger = per retail
    ├─ 4) Item.default_cost_per_base → per base (retail) by definition
    └─ 5) Zero
    │
    │  Returns same dict to get_cost_per_retail_for_valuation_batch, which then
    │  divides EVERY "missing" item by pack_size — regardless of which sub-source (2–4) supplied the cost.
    ▼
    So: OPENING_BALANCE, wavg, and default_cost_per_base are all per retail, but Path B
    treats them as "per wholesale" and divides by pack_size → understated unit_cost and value.
```

**Summary:** Dashboard does not use any pricing service; it uses ledger unit_cost directly. Current Stock Report is the only consumer of `get_cost_per_retail_for_valuation_batch`. The only place that uses `pack_size` in cost logic is Path B (fallback) in that function.

---

## 2. Every pricing function and what uses it

| Function | File | Used by | Purpose |
|----------|------|--------|--------|
| `get_last_purchase_cost` | canonical_pricing.py | get_best_available_cost, (purchases/items for last cost) | Last PURCHASE ledger row unit_cost |
| `get_opening_balance_cost` | canonical_pricing.py | get_best_available_cost | OPENING_BALANCE ledger row unit_cost |
| `get_weighted_average_cost` | canonical_pricing.py | get_best_available_cost, pricing_config_service (outlier check) | SUM(qty×cost)/SUM(qty) over positive movements |
| `get_best_available_cost` | canonical_pricing.py | pos_snapshot_service, pricing_service, items API, purchases API, stock_take | Single-item best cost (1→2→3→4→0) |
| `get_best_available_cost_batch` | canonical_pricing.py | get_cost_per_retail_for_valuation_batch only (for "missing" items) | Batch version of same priority |
| `get_cost_per_retail_for_valuation_batch` | canonical_pricing.py | get_stock_valuation (Current Stock Report) only | Cost per retail for report; applies pack_size in fallback |

**Current Stock Report:** Uses only `get_cost_per_retail_for_valuation_batch`.  
**Dashboard stock valuation:** Uses no CanonicalPricingService; uses ledger directly.  
**Inventory valuation (layer-based):** Same as dashboard; no pricing service.

---

## 3. Cost sources and unit returned (per path)

| Path | Source | Unit returned | Notes |
|------|--------|----------------|-------|
| Last PURCHASE (ledger) | InventoryLedger.unit_cost, transaction_type=PURCHASE, quantity_delta>0 | Per retail | Architecture and Item model state ledger unit_cost is per retail. |
| OPENING_BALANCE (ledger) | InventoryLedger.unit_cost, OPENING_BALANCE | Per retail | Excel/import creates opening balance with "cost per base" (see §4); after migration, ledger is retail. |
| Weighted average | SUM(quantity_delta × unit_cost)/SUM(quantity_delta), quantity_delta>0 | Same as ledger → per retail | No pack_size in formula. |
| default_cost_per_base | Item.default_cost_per_base | Per base (retail) | Column semantics and name: cost per base unit. |
| Zero fallback | — | 0 | N/A |

**Conclusion:** Every source that feeds `get_best_available_cost_batch` (and thus the "missing" path of `get_cost_per_retail_for_valuation_batch`) returns cost **per retail**. The docstring in `get_cost_per_retail_for_valuation_batch` that says "OPENING_BALANCE / default: unit_cost is per wholesale" is **out of date** relative to the current architecture (ledger and default_cost_per_base are per retail).

---

## 4. Every place pack_size is used in pricing logic

| Location | File:Line | Why used | Converts cost? | Converts quantity? |
|----------|-----------|----------|----------------|--------------------|
| get_cost_per_retail_for_valuation_batch, fallback (Path B) | canonical_pricing.py:330–331 | Docstring: "cost is per WHOLESALE → cost_per_retail = cost / pack_size" | **Yes:** `result[iid] = cost / pack_size` | No |

No other use of `pack_size` exists inside CanonicalPricingService. No other pricing helper in this service uses pack_size.

**Effect:** For every item that has no last PURCHASE, the cost returned by `get_best_available_cost_batch` (OPENING_BALANCE, wavg, or default_cost_per_base — all per retail) is divided by `pack_size`. So a correct retail cost of 3.59 becomes 3.59/100 = 0.0359 (or smaller for larger pack_size). That understates unit_cost and therefore value (value = stock_qty × unit_cost) for those items in the Current Stock Report.

---

## 5. Ledger assumption: does any ledger row still contain wholesale/packet cost?

**Item model (app/models/item.py):**  
"retail_unit … ledger quantity_delta and unit_cost are per retail".

**InventoryLedger (app/models/inventory.py):**  
unit_cost documented as "Cost per base unit" (base = retail in this codebase).

**Excel import / opening balance:**  
- Comment: "Create opening balance: unit_cost from Excel (purchase price) converted to cost per base".  
- `_create_opening_balance(..., unit_cost_per_base=default_cost_per_base)` — same value as default_cost_per_base, which is "Cost per base unit fallback" on Item.  
- So OPENING_BALANCE is written with cost per base (retail).

**Conclusion:** The codebase and write paths assume ledger unit_cost is **per retail** everywhere (PURCHASE, OPENING_BALANCE, and any migration that normalized costs). There is no evidence that any ledger row is still stored "per packet/wholesale". Therefore any division by pack_size that assumes "cost is per wholesale" is legacy logic and is incorrect when all costs are already per retail.

---

## 6. Explaining the symptom (unit_cost ≈ 0 or 0.00002, total value > 0)

**Step-by-step for an item that has no last PURCHASE (e.g. only OPENING_BALANCE or only default_cost_per_base):**

1. **Ledger (or Item):**  
   - OPENING_BALANCE row has unit_cost = 3.59 (per capsule), or  
   - Item has default_cost_per_base = 3.59.

2. **get_cost_per_retail_for_valuation_batch:**  
   - Path A (last PURCHASE): skipped (no PURCHASE for this item).  
   - Path B (missing):  
     - `cost_raw = get_best_available_cost_batch(missing, ...)`  
     - For this item, cost_raw[item_id] = 3.59 (from OPENING_BALANCE or default_cost_per_base).  
     - pack_size = 100.  
     - `result[item_id] = 3.59 / 100 = 0.0359`.

3. **Report output:**  
   - unit_cost = 0.0359 (or rounded 0.04 in UI).  
   - value = stock_qty × 0.0359 (e.g. 505 × 0.0359 ≈ 18.13).  
   So we see a **small** unit_cost and a value that is **understated** by 100× vs the correct 505 × 3.59.

If the UI shows unit_cost as 0.00 or 0.00002:  
- 0.00 can be rounding of 0.0359 to 2 decimals.  
- 0.00002 can be 3.59 / (100 × 1795) or a very large pack_size (e.g. 3.59/179500), or a different item with different cost/pack_size.  
- **Double division:** In the code paths audited there is **only one** division by pack_size (in get_cost_per_retail_for_valuation_batch). There is no second division in CanonicalPricingService or in the valuation report path. If a double division were present elsewhere (e.g. another caller or frontend), that would have to be in a different path not traced here. In the canonical pricing and Current Stock Report path, a single erroneous division by pack_size is sufficient to produce very small unit_cost and understated value for items with no PURCHASE.

**Why total stock value is still non-zero:** The report total is the sum over all items. Items that have a last PURCHASE get correct (retail) cost and contribute correct value. Only items that fall into Path B (no PURCHASE) get divided by pack_size; their contribution is small but non-zero (e.g. qty × 0.0359). So the total is dominated by correctly priced items and is non-zero, while some rows show unit_cost ≈ 0 or tiny.

---

## 7. Which paths assume packet pricing

Only one path assumes "cost is per wholesale (packet)" and applies a conversion:

- **get_cost_per_retail_for_valuation_batch**, Path B (missing items):  
  - Assumes `cost_raw` from `get_best_available_cost_batch` is per wholesale.  
  - Converts via `cost / pack_size`.  
  - In reality, `get_best_available_cost_batch` returns per-retail from OPENING_BALANCE, wavg, and default_cost_per_base, so this assumption is wrong.

No other path in CanonicalPricingService or in the valuation/report flow uses pack_size or assumes packet cost.

---

## 8. Recommendation

- **Remove the pack_size division** in `get_cost_per_retail_for_valuation_batch` for the fallback (Path B).  
  - Treat the result of `get_best_available_cost_batch` as **already per retail** for all sources (last PURCHASE, OPENING_BALANCE, weighted average, default_cost_per_base).  
  - So for "missing" items, set `result[iid] = cost` (no division by pack_size).

- **Do not** remove or change any other logic (ledger writes, sales, supplier invoices, stock/cost adjustments, search, or transaction posting). Only this one conversion in the valuation report’s cost path is inconsistent with the "ledger and defaults are per retail" architecture.

- After the change, the Current Stock Report will show unit_cost and value consistent with the rest of the system (e.g. 3.59 per capsule, value 505 × 3.59), and the symptom (unit_cost ≈ 0 or 0.00002 with non-zero total value) for items without a last PURCHASE will be resolved.

---

**End of audit. No code has been modified.**
