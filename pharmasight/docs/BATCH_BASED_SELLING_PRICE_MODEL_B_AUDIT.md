# Batch-Based Selling Price (Model B) — Architectural Audit

**Status:** Architecture validation only — no code changes, no migrations, no refactors  
**Date:** 2025-02-26  
**Scope:** Full repository analysis to assess feasibility of making selling price depend on actual batch cost, with margin validation against selected batch and optional user override within capped margin rules.

---

## SECTION 1 — Current Cost Resolution Logic

### 1.1 When `PricingService.calculate_recommended_price()` is called: how is cost determined?

**File:** `pharmasight/backend/app/services/pricing_service.py`

- **Signature:** `calculate_recommended_price(db, item_id, branch_id, company_id, unit_name, tier="retail")`. There is **no `batch_id` parameter**.

- **Cost source:** The method obtains cost by calling **`PricingService.get_item_cost(db, item_id, branch_id, use_fefo=True)`** (lines 349–350 for markup path; 306–307 for 3-tier path when building margin). It does **not** call any API that accepts a batch or ledger entry ID.

- **Inside `get_item_cost()` (lines 40–83):**
  1. **If `use_fefo=True` (default):** Calls `InventoryService.get_stock_by_batch(db, item_id, branch_id)`. If the returned list is non-empty, returns **`Decimal(str(batches[0]["unit_cost"]))`** — i.e. the **first batch’s cost** in FEFO order. So cost is **FEFO first batch’s cost** (per base unit; see note below).
  2. **Else:** Queries `InventoryLedger` for the **most recent PURCHASE** (by `created_at` desc) for that item_id + branch_id and returns its `unit_cost`.
  3. **If still no cost:** Falls back to **`CanonicalPricingService.get_best_available_cost(db, item_id, branch_id, item.company_id)`**, which uses: last purchase cost → opening balance cost → weighted average cost → `items.default_cost_per_base` → 0. None of these are batch-specific.

**Conclusion:** Cost is determined by:
- **Primary (when use_fefo=True):** The **first batch** in FEFO order from `get_stock_by_batch` (that batch’s `unit_cost`; see 1.2).
- **Fallbacks:** Latest purchase cost (single ledger row), or CanonicalPricingService (last purchase / opening balance / weighted average / default). None of these are “specific batch” in the sense of “the batch that will later be allocated to this line.”

**Note on units:** `get_stock_by_batch` returns `unit_cost` from the ledger aggregation (avg per batch). Ledger `unit_cost` is stored per transaction; the service uses it as cost per base unit for pricing. `get_item_cost` returns “cost per base unit” as used by `calculate_recommended_price` for margin and price calculation.

### 1.2 Is cost derived from specific batch? Weighted average? Latest purchase? Ledger? CanonicalPricingService?

| Source | When used |
|--------|-----------|
| **Specific batch (FEFO first)** | Yes, when `use_fefo=True`: cost = first batch’s `unit_cost` from `get_stock_by_batch`. The “batch” is the (batch_number, expiry_date) group; cost is that group’s average `unit_cost` (from ledger). |
| **Weighted average** | Only as a fallback inside **CanonicalPricingService.get_best_available_cost** when there is no last purchase and no opening balance. Not used by `get_item_cost` when FEFO returns data. |
| **Latest purchase** | Yes, as first fallback in `get_item_cost` when FEFO returns no batches; and inside CanonicalPricingService when FEFO and last-purchase path are not used. Latest purchase is a single ledger row (no batch identity passed to pricing). |
| **Inventory ledger** | All cost ultimately comes from `InventoryLedger`: FEFO uses ledger grouped by batch; last purchase uses ledger; CanonicalPricingService uses ledger (and item default only when no ledger). |
| **CanonicalPricingService** | Used only when FEFO returns no batches and there is no last purchase in the direct ledger query. It provides last purchase / opening balance / weighted average / default — none batch-scoped for a specific line. |

### 1.3 Is cost branch-specific?

**Yes.** Every cost path is scoped by `branch_id`:
- `get_stock_by_batch(db, item_id, branch_id)` — branch-specific.
- Ledger queries in `get_item_cost` and in CanonicalPricingService filter by `branch_id`.

### 1.4 Does recommended price depend on batch ID?

**No.** Recommended price does **not** depend on any batch ID or ledger entry ID:
- `calculate_recommended_price` has no `batch_id` (or ledger id) parameter.
- It depends only on (item_id, branch_id, company_id, unit_name, tier). Cost is “whatever FEFO first batch (or fallback) returns at call time” — the batch is not an input and is not stored on the line at pricing time.

### 1.5 If not, why? Where in the call chain could batch ID be injected?

- **Why it doesn’t depend on batch ID today:** The design is “recommend a price at line add time” before any stock is allocated. Batch is only chosen later at **batch sync** (allocate_stock_fefo). So the API has no batch to bind to when the line is created.
- **Where batch ID could be injected (for Model B):**
  - **Option A:** If batch were selected **before** pricing (e.g. user picks batch in POS, or system pre-allocates at add-to-cart): then `get_recommended_price` and `calculate_recommended_price` could accept an optional `batch_id` (or `ledger_entry_id`), and `get_item_cost` could accept optional `batch_id` and return that ledger row’s `unit_cost`. Resolution would then be batch-specific.
  - **Option B:** If batch is still chosen only at batch sync: then at **batch sync** time, after `allocate_stock_fefo`, the allocated batch(es) and their costs are known. One could then (for Model B) recalculate “recommended price” for the allocated batch and optionally enforce/update price and margin against that batch’s cost — but that would be a **different** flow (post-allocation validation/recalc), not “inject batch into current pricing call.”

### 1.6 When an invoice line is created: is batch selected before pricing, or is pricing resolved before batch assignment? Exact execution order.

**Pricing is resolved before batch assignment.** Batch is assigned only at batch sync.

**Exact execution order (create invoice with first item / add item):**

1. **Create invoice (POST /invoice)** — per item in request body:
   - `InventoryService.check_stock_availability(...)` — no allocation, no batch.
   - If `unit_price_exclusive` not provided:  
     `PricingService.calculate_recommended_price(db, item_id, branch_id, company_id, unit_name, tier)`  
     → internally `get_item_cost(db, item_id, branch_id, use_fefo=True)`  
     → `get_stock_by_batch(db, item_id, branch_id)` → cost = first FEFO batch’s cost.  
     No batch ID is passed or stored.
   - Line totals computed from `unit_price`, `discount_*`.
   - `SalesInvoiceItem` created with `batch_id=None`, `unit_price_exclusive=unit_price`, `unit_cost_used=unit_cost` (from FEFO/fallback).

2. **Add item (POST /invoice/{id}/items)** — same pattern:
   - Stock check (no allocation).
   - If no price: `calculate_recommended_price` → `get_item_cost(..., use_fefo=True)` → FEFO first batch cost.
   - New line created with `batch_id=None`, `unit_price_exclusive`, `unit_cost_used`.

3. **Batch (POST /invoice/{id}/batch)** — later:
   - For each line: `InventoryService.allocate_stock_fefo(...)` → returns allocations (each with `unit_cost`, `ledger_entry_id`).
   - `invoice_item.batch_id = allocations[0]["ledger_entry_id"]` — **batch_id set here for the first time.**
   - Ledger SALE entries created with allocated batch’s `unit_cost`.
   - **`unit_cost_used` on the line is not updated** from the allocation; it remains the value from step 1 or 2.

So: **pricing first (no batch) → batch assignment later; cost used for pricing can differ from cost of the batch actually allocated.**

---

## SECTION 2 — Batch Selection Flow

### 2.1 When multiple batches exist for an item: how is batch selected?

**FEFO (First Expiry First Out).** Selection is not manual at line level.

- **At line add time:** No batch is selected. Only “first FEFO batch’s cost” is used for recommended price.
- **At batch sync:** `InventoryService.allocate_stock_fefo(db, item_id, branch_id, quantity_base, unit_name)` is called. It:
  - Queries ledger grouped by (batch_number, expiry_date, unit_cost, ledger.id), HAVING sum(quantity_delta) > 0.
  - Orders by `expiry_date ASC NULLS LAST`, then `batch_number ASC`.
  - Consumes from batches in that order until quantity_needed is satisfied.
  - Returns a list of allocations; each has `batch_number`, `expiry_date`, `quantity`, `unit_cost`, `ledger_entry_id`.

So batch selection is **automatic, FEFO, at batch sync time only.**

### 2.2 Manual selection? During batch sync?

- **Manual:** There is no API or flow in the scanned code that lets the user pick a specific batch for a line when adding to the invoice. Batch is always determined by FEFO at batch.
- **During batch sync:** Yes. The only place batch is chosen and `batch_id` set is inside `batch_sales_invoice` when calling `allocate_stock_fefo` and then `invoice_item.batch_id = allocations[0]["ledger_entry_id"]`.

### 2.3 At what point is `batch_id` attached to `SalesInvoiceItem`?

**Only in `batch_sales_invoice`** (`sales.py`), after `allocate_stock_fefo` returns:

```python
if allocations:
    invoice_item.batch_id = allocations[0]["ledger_entry_id"]
```

Until then, every `SalesInvoiceItem` is created with `batch_id=None` (create invoice and add item both set `batch_id=None`).

### 2.4 Is cost revalidated after batch is assigned?

**No.** After assignment:
- `batch_id` is set.
- New SALE ledger rows are written with the allocated batch’s `unit_cost`.
- **`SalesInvoiceItem.unit_cost_used` is not updated** from the allocation. It remains the cost that was used at line creation (FEFO first batch or fallback at that time). So there is no revalidation of margin or price against the **actually allocated** batch’s cost.

---

## SECTION 3 — Margin Validation

### 3.1 How is minimum margin currently validated?

Margin is validated in three places (all in `pharmasight/backend/app/api/sales.py`):

1. **Create invoice (first item)** — ~237–248:  
   After `unit_price` and `unit_cost_used` are set (from price_info or get_item_cost), `cost_per_sale_unit = unit_cost_used * mult`; `margin_percent = (unit_price - cost_per_sale_unit) / cost_per_sale_unit * 100`; compared to `PricingService.get_min_margin_percent(...)`; if below and user lacks `sales.sell_below_min_margin`, HTTP 400.

2. **Add invoice item** — ~582–593:  
   Same logic: margin from `unit_price` and `unit_cost_used`; compared to min_margin; permission check.

3. **Batch with body.items** — ~1231–1246:  
   When syncing lines from frontend, for each line with `unit_price_exclusive > 0`: `cost_info = PricingService.get_item_cost(db, line.item_id, invoice.branch_id)` (no batch_id); then `cost_per_sale_unit = cost_info * mult`; margin vs min_margin; permission check. So at batch time, margin is re-checked but still using **current FEFO/fallback cost**, not the cost of the batch that is about to be allocated.

**PATCH line (update_sales_invoice_item):** Does **not** re-validate margin when `unit_price_exclusive` is updated; it only recalculates line totals.

### 3.2 Is margin validated against recommended cost? unit_cost_used? Batch cost?

| Check | Cost used |
|-------|-----------|
| Create invoice / Add item | **unit_cost_used** (set from `price_info["unit_cost_used"]` when price from recommended, else from `get_item_cost`). So “recommended cost” and “unit_cost_used” are the same at line creation — both are FEFO first batch (or fallback) at that moment. |
| Batch with body.items | **Fresh `get_item_cost`** (again FEFO/fallback at batch time). Not the line’s existing `unit_cost_used`, and **not** the cost of the batch that will be allocated in the same request. |

So margin is validated against:
- **Recommended cost** (indirectly): at line creation, unit_cost_used comes from the same cost used to compute recommended price.
- **unit_cost_used** at line creation and when user sends a custom price.
- **Not** the specific batch that gets assigned: at batch sync, validation uses `get_item_cost` (current FEFO/fallback), then allocation runs; the allocated batch’s cost is never used for margin check or to update the line.

### 3.3 If multiple batch costs exist, can incorrect margin validation occur?

**Yes.**

- **Scenario:** Item has Batch A (cost 80) and Batch B (cost 100). FEFO order is A then B.
- At **add item:** FEFO first = A → cost 80 → recommended price from 80 + margin → unit_cost_used = 80. Margin validated against 80. OK.
- Before batch, other sales consume A. At **batch sync:** FEFO first is now B. `get_item_cost` returns 100. If body.items is sent, margin is checked against 100 and current line price — could fail even though line was valid when created. If body.items is not sent, margin is not re-checked; we allocate B (cost 100) but line still has unit_price from cost 80 and unit_cost_used=80. So we sold at “80 + margin” but deducted cost 100 — margin validation was against the wrong cost.
- **Worse:** If FEFO order were B then A at add time: we’d price and validate against 100; at batch we might allocate A (80). Then we’d have sold at 100-based price but cost 80 — margin check would have been against 100, not the batch actually used.

So with multiple batch costs, **margin can be validated against a different cost than the batch actually allocated**, and **unit_cost_used** can disagree with the allocated batch’s cost. Model B would require margin to be validated (and selling price to be determined) against the **selected/allocated** batch cost.

---

## SECTION 4 — Data Model Assessment

### 4.1 Can selling price safely depend on batch cost using existing schema?

**SalesInvoiceItem** already has:
- **batch_id** (FK to inventory_ledger.id) — set at batch time; nullable until then.
- **unit_cost_used** — cost used for margin at line creation; not updated when batch is assigned.
- **unit_price_exclusive** — selling price.

**For Model B (selling price and margin depend on actual batch cost):**

- **Schema:** The columns are sufficient to **store** a batch-specific cost and price: we can store the allocated batch’s cost in `unit_cost_used` (or keep it and add a separate field if we want to keep “cost at pricing time” for audit). So **storing** batch-driven price and cost does not require new columns for the core case.
- **Semantic correctness:** Today, `unit_cost_used` is “cost at line creation (FEFO/fallback)”; it is **not** “cost of the batch in batch_id.” So for Model B we must either:
  - Update `unit_cost_used` at batch time to the allocated batch’s cost (and optionally recalc or validate price then), or
  - Keep `unit_cost_used` as “cost used for pricing” and add a separate “batch cost at allocation” if we need both for reporting/audit.

So: **the existing schema can support Model B** provided we (1) set/update cost from the allocated batch at batch time (or when batch is pre-selected), and (2) define whether we keep one or two cost fields for audit. No mandatory new columns for basic Model B; optional extra column only if we want to retain “cost at pricing” and “cost at allocation” separately.

### 4.2 What structural changes would be required?

- **Logic/semantics, not necessarily schema:**  
  - Ensure selling price is computed from **batch cost** (either by passing batch into pricing when batch is known, or by recalculating/validating at batch time using allocated batch cost).  
  - Ensure margin validation always uses the **same** cost as the one used for that line’s selling price (the batch cost).  
  - Optionally: update `unit_cost_used` at batch time to the allocated batch’s cost so reports and COGS use batch cost.

- **Schema (optional):**  
  - If we want to keep “cost at pricing” for audit when it differs from “batch cost,” add e.g. `unit_cost_at_pricing` and use `unit_cost_used` as “batch cost at allocation.” Otherwise, overwriting `unit_cost_used` at batch time is enough.

- **No change required** to: `batch_id`, `unit_price_exclusive`, or line total columns for Model B to be representable.

---

## SECTION 5 — Architectural Gaps (If We Switch to Model B)

### 5.1 Required changes in PricingService

**File:** `pharmasight/backend/app/services/pricing_service.py`

- **`get_item_cost`:** Add optional parameter e.g. `batch_id: Optional[UUID] = None` (or `ledger_entry_id`). When provided, return that ledger entry’s `unit_cost` (and ensure unit semantics match current “per base unit” usage). When not provided, keep current behaviour (FEFO first or fallback).
- **`calculate_recommended_price`:** Add optional parameter e.g. `batch_id: Optional[UUID] = None`. When provided, pass it to `get_item_cost` so cost is batch-specific; recommended price and `unit_cost_used` in the returned dict then correspond to that batch. When not provided, keep current behaviour (no batch).
- **Call sites:** Any caller that knows the batch (e.g. batch sync after allocation, or a future “select batch then price” flow) must pass batch_id into these methods so that price and margin are batch-based.

No change to markup/margin/tier/rounding logic itself; only to how **cost** is resolved (batch-specific vs current FEFO/fallback).

### 5.2 Required changes in Sales API flow

**File:** `pharmasight/backend/app/api/sales.py`

- **Create invoice / Add item:**  
  - If Model B is “batch selected before pricing”: API would need to accept an optional batch_id (or batch selection) per line and pass it into `calculate_recommended_price`; then store that batch_id on the line (and possibly reserve/allocate that batch). Today no batch is selected here.  
  - If Model B is “batch chosen at batch sync, then enforce batch cost”: create/add item can stay as today; the critical change is in batch_sales_invoice (below).

- **Batch (batch_sales_invoice):**  
  - After `allocate_stock_fefo`, we have per-line allocations with `unit_cost` and `ledger_entry_id`.  
  - For Model B: **margin validation** must use the **allocated** batch’s cost (e.g. `allocations[0]["unit_cost"]`), not `get_item_cost` without batch.  
  - Optionally: recalculate “recommended” price from allocated batch cost; if current `unit_price_exclusive` is below that or below min margin vs batch cost, either reject or update price (per product rules).  
  - Set `invoice_item.unit_cost_used = allocations[0]["unit_cost"]` (or equivalent) so stored cost matches the batch actually used. Today this is not done.

- **Batch with body.items:** When syncing lines and validating margin, either: (a) do not rely on margin check here and rely on post-allocation check, or (b) pass the batch that will be allocated into cost resolution. (b) would require allocating first or having a deterministic “preview” of which batch will be used; (a) is simpler and aligns with “validate after allocation.”

### 5.3 Required changes in batch selection timing

- **Current:** Batch selected only at batch sync (FEFO); no batch at line creation.
- **Model B option 1 (batch first):** Select batch **before** or **at** line add (e.g. user picks batch, or system pre-allocates FEFO). Then pricing and margin use that batch’s cost. Requires: batch selection API or pre-allocation, and passing batch_id into pricing and into line creation.
- **Model B option 2 (batch at sync):** Keep current timing. At batch sync, after FEFO allocation, use allocated batch’s cost to validate margin (and optionally recalc/update price and unit_cost_used). No change to “when” batch is chosen; only “how we use” the chosen batch’s cost after allocation.

### 5.4 Risks to invoice totals

- If at batch time we **recalculate** price from batch cost and **update** `unit_price_exclusive` and line totals, invoice totals change at batch — frontend and any pre-batch document would be out of sync unless they are refreshed after batch. So either: (1) only **validate** at batch (reject if below margin) and do not auto-update price, or (2) update price and totals at batch and treat “post-batch” as the authoritative invoice (with clear UX).
- If we only validate and optionally update `unit_cost_used` (for COGS) but do not change `unit_price_exclusive`, invoice totals stay unchanged; margin is then “correct” only if the price was already valid for the allocated batch (e.g. by chance or because we validated and rejected invalid cases).

### 5.5 Risks to KRA document generation

**File:** `pharmasight/backend/app/services/document_pdf_generator.py` (and related document services)

- Documents read stored `unit_price_exclusive`, `line_total_*`, and line data from the invoice. They do not recompute price from batch.  
- If we **do not** change how we store price (only add validation and maybe update `unit_cost_used`), KRA docs are unchanged.  
- If we **update** `unit_price_exclusive` (and thus line totals) at batch time, KRA document will reflect the post-batch values as long as the document is generated after batch. Risk is only if something generates or caches a document before batch with different totals.

### 5.6 Risks to stock deduction logic

**File:** `pharmasight/backend/app/api/sales.py` — `batch_sales_invoice`

- Stock deduction uses `allocate_stock_fefo` and creates SALE ledger entries with the allocated batch’s `unit_cost`. It does not read `unit_cost_used` from the line for deduction. So **stock deduction logic does not need to change** for Model B. The only change is to pricing/margin and to what we store in `unit_cost_used` (and optionally `unit_price_exclusive`) after allocation.

---

## SECTION 6 — Feasibility Summary

### 6.1 Is Model B feasible without rewriting major flows?

**Yes, with contained changes.**

- **PricingService:** Add optional batch-scoped cost (and optionally batch parameter to recommended price). Existing “no batch” path remains for backward compatibility and for flows that still don’t have a batch (e.g. recommended-price before batch selection).
- **Sales API:**  
  - Create/add item: can stay as is if we adopt “validate and align at batch” (option 2).  
  - Batch: add margin validation against allocated batch cost; optionally set `unit_cost_used` from allocation; optionally recalc/validate price and update line (with clear product decision on whether to update totals at batch).
- **Batch selection:** Remain FEFO at batch sync; no need to move to “batch before pricing” unless product requires it.
- **Line total formula:** Unchanged. No change to document generation logic beyond using stored values.
- **Stock deduction:** No change.

So Model B is feasible without rewriting the whole sales or inventory flow; the main work is cost resolution with optional batch, and batch-time validation/update of cost (and optionally price).

### 6.2 Safest migration path

1. **Phase 1 (backend only, additive):**  
   - Add optional `batch_id` (or ledger_entry_id) to `get_item_cost` and `calculate_recommended_price`; when provided, resolve cost from that batch and return price/cost for that batch. When not provided, behaviour unchanged.  
   - No change yet to sales API behaviour.

2. **Phase 2 (batch sync):**  
   - In `batch_sales_invoice`, after `allocate_stock_fefo`:  
     - Use allocated batch cost for **margin validation** (replace current `get_item_cost` margin check with cost from `allocations[0]["unit_cost"]`).  
     - Set `invoice_item.unit_cost_used` to the allocated batch’s cost (e.g. from first allocation) so COGS and reports reflect batch cost.  
   - Do **not** yet change `unit_price_exclusive` or line totals at batch (avoid invoice total changes mid-flow).

3. **Phase 3 (policy):**  
   - Decide: if margin fails against allocated batch cost, reject batch with a clear error, or allow with permission.  
   - Optionally: when margin fails, offer to recalc price from batch cost and update line (then recalc invoice totals) — with explicit UX so users know totals can change at batch.

4. **Phase 4 (optional — batch-before-pricing):**  
   - If product wants “user picks batch then price,” add batch selection to POS and pass batch_id into recommended-price and into create/add item; then line is created with batch_id and batch-based price from the start.

### 6.3 What must be implemented first

- **PricingService:** Optional batch-aware cost and recommended price (batch_id parameter; when present, cost from that ledger entry).
- **Batch sync:** Use allocated batch’s cost for margin check and for updating `unit_cost_used`. No change to create/add item until/unless you add “batch before pricing.”

### 6.4 What must NOT be touched initially

- **Line total formula** in sales and quotations: leave unchanged.  
- **Document/PDF/KRA generation:** no logic change; they keep reading stored line and totals.  
- **Stock deduction and FEFO allocation:** no change to how we allocate or write SALE ledger entries.  
- **Create invoice / Add item:** can remain as is (no batch_id, same recommended price as today) until you introduce batch-before-pricing.  
- **PATCH line:** no need to add batch-aware logic initially unless you allow “change batch” on a line (not in current design).

---

**End of audit. No code or migrations were generated; this document is for architecture validation only.**
