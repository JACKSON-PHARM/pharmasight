# Model B — Batch-Based Selling Price: Design & Decision Document

**Status:** Design and decision only — no code, no file modifications  
**Date:** 2025-02-26  
**Prerequisite:** BATCH_BASED_SELLING_PRICE_MODEL_B_AUDIT.md  

**Target:** Selling price depends on allocated batch cost; margin validated against batch cost; user override within capped rules; COGS reflects batch cost used.

---

## SECTION 1 — Pricing Timing Model: Option A vs Option B

### 1.1 Option A — Batch Before Pricing

**Behaviour:** User selects batch (or system pre-allocates FEFO) at line creation. Recommended price uses that batch’s cost. Line is created with `batch_id` and batch-based price.

| Criterion | Assessment |
|----------|------------|
| **Breaking changes** | **High.** Requires: (1) POS/API to support batch selection or pre-allocation at add-item; (2) create/add-item to accept and pass `batch_id` into pricing; (3) reservation or soft-allocate so the chosen batch is still available at batch sync; (4) frontend and API contract changes. Create-invoice and add-invoice-item flows change; batch sync may need to “confirm” pre-allocated batch instead of full FEFO. |
| **Invoice totals stability** | **High.** Totals are fixed at line creation because price is already batch-based. No recalculation at batch time. |
| **Alignment with current FEFO** | **Low.** Current flow is “no batch until batch sync.” Option A inverts order: batch first, then price. FEFO would need to run at add-item (or user picks batch), which may conflict with “single FEFO at batch” and can cause double-handling (reserve vs confirm). |
| **POS simplicity** | **Low.** User may need to see/select batch per line; or system must pre-allocate and expose “reserved” batch. More steps and UI surface. |

### 1.2 Option B — Batch At Sync (Minimal Disruption)

**Behaviour:** Line is created without batch (as today). At batch sync: allocate batch (FEFO); use allocated batch cost for margin validation; update `unit_cost_used`; optionally adjust price only when policy requires it (see Section 2).

| Criterion | Assessment |
|----------|------------|
| **Breaking changes** | **Low.** Create-invoice and add-invoice-item stay as today (no batch_id, same recommended price from FEFO-first). Only batch_sales_invoice changes: add margin check against allocated cost, update `unit_cost_used`, and (by policy) optionally reject or adjust price. No new API parameters for line creation; no reservation flow. |
| **Invoice totals stability** | **Controlled.** If we **do not** auto-adjust price at batch (recommended in Section 4), totals are unchanged at batch. Only `unit_cost_used` and validation outcome change. If we ever allow optional auto-adjust, we will have defined that as an explicit policy with refresh expectations. |
| **Alignment with current FEFO** | **High.** FEFO runs once, at batch sync, as today. No pre-allocation, no reserve. Same `allocate_stock_fefo` call; we only add post-allocation validation and cost update. |
| **POS simplicity** | **High.** No change for cashier: add item → get recommended price → optionally override → batch. Batch and cost alignment happen in the backend at batch time. |

### 1.3 Recommendation: **Option B — Batch At Sync**

**Reasoning:**

- **Fewer breaking changes:** Option B limits changes to batch sync and PricingService (optional batch_id for future use). Create/add item and POS flows remain unchanged.
- **Safer for invoice totals:** With Option B we can enforce “no automatic price change at batch” (Section 4): only validate and update `unit_cost_used`. Totals stay stable; no frontend refresh required for totals.
- **Best alignment with current FEFO:** One FEFO allocation at batch sync; no reservation or pre-allocation. Simpler and less risk of stock inconsistency.
- **POS simplicity:** No batch selection UI, no new steps. Model B is achieved by correct accounting (COGS = batch cost) and margin validation at batch, not by changing when the user does things.

**Option A** remains a possible future enhancement (e.g. “pick batch” for specific workflows) once Option B is live and stable.

---

## SECTION 2 — Margin Policy Design

### 2.1 Inputs

- Company (and item) **minimum margin %**.
- Permission **sales.sell_below_min_margin** (user can sell below min margin).
- At batch sync we have: **allocated batch cost** (from FEFO), **current line** `unit_price_exclusive`, `unit_cost_used` (cost at pricing time).

### 2.2 When Allocated Batch Cost Is Higher Than Cost Used at Pricing

**Scenario:** Line was priced using cost C1 (FEFO at add time). At batch, allocated batch has cost C2 > C1. So current selling price may now be below min margin when measured against C2.

| If current price vs C2 is below min margin | Action |
|-------------------------------------------|--------|
| User has **sales.sell_below_min_margin** | **Allow** batch. Update `unit_cost_used` to C2. Do not change price. Log override for audit if desired. |
| User does **not** have permission | **Reject** batch with clear error (e.g. “Price below minimum margin for allocated batch. Required: X%; current: Y%. Contact admin or increase price.”). Do not update line; do not allocate. User must increase price and retry batch, or get permission. |
| **Auto-adjust price upward?** | **No.** Auto-adjust would change invoice totals at batch and surprise the user. Reject or allow with permission keeps totals predictable. |

### 2.3 When Allocated Batch Cost Is Lower Than Cost Used at Pricing

**Scenario:** Line was priced using cost C1; allocated batch has cost C2 < C1. Margin vs C2 is higher than at pricing.

| Question | Decision |
|----------|----------|
| Keep selling price unchanged? | **Yes.** Keep `unit_price_exclusive` unchanged. No auto-adjust downward. |
| Preserve “margin consistency”? | We do **not** auto-reduce price. True pharmacy accounting requires COGS = batch cost; we achieve that by updating `unit_cost_used` to C2. Margin reports will show higher margin for that line (correct). No need to lower price. |

### 2.4 Where Is Margin Validated?

| When | Validate? | Cost used |
|------|------------|-----------|
| **At line creation (create invoice / add item)** | **Yes** (keep current behaviour). Validate against FEFO-first cost (or fallback). Ensures we don’t accept obviously bad prices early. |
| **At batch sync** | **Yes** (new). Validate against **allocated batch cost**. This is the authoritative check for Model B: the batch we actually use determines whether margin is acceptable. |

So: **Validate at both** line creation and batch. Line creation uses “best guess” cost (FEFO first); batch uses **actual** batch cost. If batch cost is higher and margin fails, batch is rejected (or allowed only with permission).

### 2.5 Decision Tree (Batch Sync)

```
After allocate_stock_fefo for a line:
  batch_cost = allocations[0]["unit_cost"]  (per base unit; convert to sale unit for comparison)

  1. cost_per_sale_unit = batch_cost * unit_multiplier
  2. margin_percent = (unit_price_exclusive - cost_per_sale_unit) / cost_per_sale_unit * 100
  3. min_margin = get_min_margin_percent(item_id, company_id)

  IF margin_percent >= min_margin:
    → Allow: set unit_cost_used = batch_cost (from first allocation), set batch_id, proceed.
  ELSE:
    IF user has sales.sell_below_min_margin:
      → Allow: set unit_cost_used = batch_cost, set batch_id, proceed. (Optionally log override.)
    ELSE:
      → Reject: HTTP 400, do not allocate, do not update line. Message: price below min margin for allocated batch.
```

**No auto-adjust of price at batch.** Reject or allow with permission only.

---

## SECTION 3 — unit_cost_used Semantics

### 3.1 Options

| Option | Meaning of unit_cost_used | Pros | Cons |
|--------|----------------------------|------|------|
| **A) Cost at pricing time** | Snapshot of cost when line was created (FEFO first or fallback). | Preserves “what we used to set price.” | COGS and margin reports wrong after batch (we deduct a different batch cost). Fails Model B accounting. |
| **B) Cost of allocated batch** | After batch: overwrite with allocated batch cost. | COGS correct; margin reports correct; one field, one meaning. | We lose “cost at pricing” for that line unless we store it elsewhere. |
| **C) Both (two fields)** | e.g. `unit_cost_used` = batch cost; new `unit_cost_at_pricing` = cost when price was set. | Full audit trail; can explain margin at pricing vs at batch. | Schema change; more fields to maintain and document; reports must decide which to use. |

### 3.2 Accounting and Compliance

- **COGS:** Must reflect **batch cost used** (the cost we actually deduct from inventory). So the cost we store for COGS must be the allocated batch cost. That implies `unit_cost_used` (or whatever feeds COGS) should be **batch cost** after batch.
- **KRA:** Documents use stored line data. If COGS and margin are derived from `unit_cost_used`, then `unit_cost_used` = batch cost keeps KRA and reports consistent.
- **Audit:** “Why did margin change?” — If we only keep batch cost, we can still infer “pricing was based on FEFO at add time; batch allocated had cost X.” Storing “cost at pricing” is optional for deep audit, not required for compliance.

### 3.3 Recommendation: **Option B — unit_cost_used = Cost of Allocated Batch**

- **After batch:** Set `unit_cost_used` to the allocated batch cost (from first allocation; same unit semantics as today — per base unit). Before batch, keep current behaviour (cost at line creation).
- **COGS reports:** Use `unit_cost_used` as today; they automatically reflect batch cost once we update it at batch.
- **Margin reports:** Same; margin = (price - unit_cost_used) / unit_cost_used, correct after batch.
- **KRA:** No change to document logic; stored values remain authoritative.
- **Audit:** If needed later, we can add optional `unit_cost_at_pricing` in a later phase. For go-live, one field is simpler and sufficient for true pharmacy accounting.

**Summary:** Before batch, `unit_cost_used` = cost at line creation (unchanged). At batch sync, **overwrite** `unit_cost_used` with allocated batch cost. No second field required for initial Model B.

---

## SECTION 4 — Invoice Totals Stability

### 4.1 Policy: No Automatic Price Change at Batch

- **Do not** recalculate or auto-adjust `unit_price_exclusive` at batch based on allocated batch cost.
- **Do** validate margin against allocated batch cost; **reject** batch (or allow with permission) if below min margin; **do** update `unit_cost_used` to batch cost.
- **Effect:** Invoice totals do not change at batch. Frontend does not need to refresh for totals; printed/draft documents stay consistent with final invoice.

### 4.2 If We Ever Allow Optional Price Adjustment

- If product later wants “suggested price from batch cost” when margin fails: treat as **explicit user action** (e.g. “Apply suggested price and batch” button), not silent auto-adjust.
- Then: recalc line total and invoice totals; require frontend refresh before payment/print so user sees new totals. Do not change totals silently.

### 4.3 Recommendation

- **Safest accounting-consistent approach:** Reject or allow with permission; update only `unit_cost_used` at batch; **never** auto-update price at batch in the initial design. Invoice totals remain stable; no “batch blocked if totals would change” needed because we never change totals at batch.

---

## SECTION 5 — Implementation Order (Strict Phases)

### Phase 1 — Backend Additive Changes Only

**Goal:** PricingService can resolve cost (and optionally recommended price) by batch when batch is known; no change to sales behaviour yet.

**Files affected:**
- `pharmasight/backend/app/services/pricing_service.py` — add optional `batch_id` (or `ledger_entry_id`) to `get_item_cost` and `calculate_recommended_price`; when provided, resolve cost from that ledger entry; when not provided, behaviour unchanged.
- `pharmasight/backend/app/services/inventory_service.py` — only if we need a small helper to get cost by ledger id; otherwise none.
- Tests (new or existing) for batch-scoped cost and recommended price.

**Risk level:** Low. Additive; no callers pass batch_id yet.

**Rollback:** Remove optional parameters and batch branch; no schema or API contract change.

---

### Phase 2 — Batch Validation and unit_cost_used Update

**Goal:** At batch sync, validate margin against allocated batch cost; update `unit_cost_used` to allocated batch cost; reject (or allow with permission) when below min margin.

**Files affected:**
- `pharmasight/backend/app/api/sales.py` — inside `batch_sales_invoice`: after `allocate_stock_fefo`, for each line compute margin using `allocations[0]["unit_cost"]` (and unit multiplier); compare to `get_min_margin_percent`; if below and user lacks `sales.sell_below_min_margin`, reject with HTTP 400; else set `invoice_item.unit_cost_used` from first allocation’s cost (same unit as current: per base). Remove or narrow the existing margin check that uses `get_item_cost` without batch when body.items is present (Section 2: validate against allocated cost, not pre-batch cost).
- No change to create-invoice or add-invoice-item logic (they keep current margin check at line creation).
- No change to stock deduction or FEFO allocation logic.

**Risk level:** Medium. Batch can now fail with new error; `unit_cost_used` changes at batch. Mitigate with clear error messages and tests (multi-batch scenarios).

**Rollback:** Revert batch_sales_invoice to previous behaviour (no post-allocation margin check; do not update unit_cost_used from allocation). Deploy previous version.

---

### Phase 3 — Permission and Override Enforcement

**Goal:** Enforce `sales.sell_below_min_margin` in batch margin check; optional override logging when batch is allowed below margin.

**Files affected:**
- `pharmasight/backend/app/api/sales.py` — ensure batch_sales_invoice uses `_user_has_sell_below_min_margin(db, batched_by, invoice.branch_id)` when margin vs allocated batch is below min; allow batch only if true. Optionally log to an audit table when batch is allowed below margin (e.g. invoice_id, line, batch_cost, selling_price, margin%, user).
- No new permissions; use existing `sales.sell_below_min_margin`.

**Risk level:** Low. Clarifies existing permission in new batch context.

**Rollback:** Allow batch regardless of margin (temporary) or revert to Phase 2 without override logging.

---

### Phase 4 — Optional UI / Reporting

**Goal:** Surface batch cost and margin in UI; optional “cost at batch” in reports; no mandatory POS flow change.

**Files affected:**
- Frontend (e.g. sales receipt or invoice view): optionally show batch number and/or “cost at batch” where useful.
- Reports that show COGS/margin: already correct if they use `unit_cost_used` (now batch cost after batch).
- Optional: admin message when batch is rejected (e.g. “Price below min margin for allocated batch”) so support can guide users.

**Risk level:** Low. Optional; no change to core batch or pricing logic.

**Rollback:** Remove UI/report additions only.

---

## SECTION 6 — Risk Matrix

| Risk area | Mitigation |
|-----------|------------|
| **Stock deduction** | No change to `allocate_stock_fefo` or SALE ledger creation. Deduction still uses allocated batch and its cost. Risk: **None** if we don’t touch allocation. |
| **Margin validation** | Validate at line creation (current) and at batch (against allocated cost). Reject or allow with permission only; no auto-adjust. Reduces incorrect margin approval. Risk: **Low** with clear errors. |
| **Multi-branch pricing** | All cost and allocation remain branch-scoped. No change to branch_id usage. Risk: **None**. |
| **Backdated invoices** | Batch uses “today” FEFO; invoice_date is separate. No change to backdating behaviour. Risk: **None** for Model B itself. |
| **Draft invoices** | Drafts stay as today; no batch_id, unit_cost_used = cost at creation. Only at batch do we update unit_cost_used and set batch_id. Risk: **Low**. |
| **Concurrency** | Batch already uses row lock on invoice (`with_for_update()`). FEFO allocation runs inside same transaction. No new concurrency surface. Risk: **Low**. |
| **Invoice totals change** | We do **not** change price at batch; only unit_cost_used. Totals stable. Risk: **None** per design. |
| **KRA / document generation** | Documents read stored line and totals. No logic change; unit_cost_used after batch is batch cost (correct for COGS). Risk: **None**. |

---

## FINAL OUTPUT

### Recommended Architecture

**Option B — Batch At Sync (Minimal Disruption).**

- Line created without batch; price from current FEFO-first cost as today.
- At batch sync: allocate FEFO → validate margin against allocated batch cost → update `unit_cost_used` to allocated batch cost → set `batch_id`. Reject batch if margin below min and user lacks permission; else allow.
- No automatic price change at batch. No batch selection at POS in initial design.

### Final Margin Policy

- **Line creation:** Keep current margin check (vs FEFO-first or fallback cost).
- **Batch sync:** Validate margin vs **allocated batch cost**. If below min margin: **reject** batch unless user has **sales.sell_below_min_margin**; if allowed, update `unit_cost_used` and proceed (optional audit log). No auto-adjust of price upward or downward at batch.

### Final Cost Semantics

- **unit_cost_used:** Before batch = cost at line creation (unchanged). **After batch = overwritten with allocated batch cost** (per base unit). Single field; COGS and margin reports use it. No second “cost at pricing” field for initial Model B.

### Migration Roadmap

1. **Phase 1:** PricingService optional batch_id; no behaviour change in sales.
2. **Phase 2:** Batch sync: margin validation vs allocated cost; set unit_cost_used from allocation; reject or allow with permission.
3. **Phase 3:** Enforce permission in batch margin check; optional override logging.
4. **Phase 4:** Optional UI/reporting for batch cost and rejection messaging.

### Risks Summary

- Stock deduction: no change.
- Margin: validated at creation and at batch (batch = authoritative); reject or allow with permission.
- Multi-branch / backdated / draft: no new risk.
- Concurrency: unchanged (invoice lock + same transaction).
- Invoice totals: stable (no price change at batch).
- KRA/docs: no change; stored values remain correct after batch.

### What We Absolutely Must NOT Break

- **Line total formula:** Unchanged (unit_price × qty − discount, then VAT).
- **Stock deduction and FEFO:** Same allocation and SALE ledger creation; no change to allocate_stock_fefo or ledger writes for quantity/cost.
- **Create invoice / Add item:** No required change to API contract or flow; no mandatory batch_id in request.
- **Document/PDF/KRA generation:** No change to how documents read invoice and line data.
- **Invoice totals at batch:** Do not change unless we explicitly design an optional “user-confirmed price adjustment” flow later.
- **Existing permission semantics:** `sales.sell_below_min_margin` continues to mean “may sell below min margin”; we only apply it at batch against allocated batch cost.

---

**End of design document. No code or file modifications; decisions only.**
