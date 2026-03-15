# Customer Return Engine — Analysis

This document analyzes how **customer returns** (reversing a batched, paid sales invoice) fit into the PharmaSight model and what needs to change to support them. The goal: when drugs are faulty, the customer declines, or any other reason, we can reverse the transaction so that **stock counts**, **daily sales**, and **margins** stay correct.

---

## 1. Current model (how a sale works today)

### 1.1 Sales invoice lifecycle

1. **DRAFT** — Invoice created, items added. No stock impact.
2. **BATCHED** — User allocates batches (FEFO) and submits. This:
   - Creates **InventoryLedger** rows per allocation: `transaction_type="SALE"`, `reference_type="sales_invoice"`, `reference_id=invoice.id`, **negative** `quantity_delta` (and batch_number, expiry_date, unit_cost, total_cost).
   - Calls **SnapshotService.upsert_inventory_balance** for each ledger row (reduces `inventory_balances.current_stock`).
   - Updates search snapshot “last sale” etc.
3. **PAID** — Payment recorded (cash can auto-mark PAID at batching).

Only **DRAFT** invoices can be deleted. **BATCHED/PAID** cannot be deleted.

### 1.2 Where data lives

| Concern | Source |
|--------|--------|
| Stock quantity | `inventory_ledger` (append-only) + `inventory_balances` (snapshot). Sale = negative `quantity_delta` per (item, branch, batch). |
| Sales value | `sales_invoices.total_exclusive` (and line-level `sales_invoice_items`). |
| COGS | `sales_invoice_items.unit_cost_used` × quantity (retail units), and mirrored in `inventory_ledger.total_cost` for SALE entries. |
| Daily sales / gross profit | **Sales:** Sum of `SalesInvoice.total_exclusive` for branch + date range (status BATCHED/PAID). **COGS:** From invoice lines (or ledger) for same invoices. **Gross profit = sales − COGS.** |

So: **reversing a sale** must (1) put stock back, (2) reduce “sales” for reporting, (3) reduce COGS for reporting, and (4) optionally handle refund/credit.

---

## 2. What a customer return means

- **Trigger:** A sales invoice has been **batched and payment collected**, but we need to reverse it (faulty goods, customer declined, etc.).
- **Effects we need:**
  1. **Stock** — Return the quantities to the branch (same batches if possible), so `inventory_balances` and ledger are correct.
  2. **Sales** — Net sales for the day/period should decrease by the returned amount (so “daily sales” is net of returns).
  3. **COGS / margins** — The cost of the returned quantity should no longer count as COGS; margins and gross profit should reflect the reversal.
  4. **Audit / compliance** — A proper **credit note** (KRA document) linking to the original invoice, with reason and items.

We do **not** delete or modify the original invoice or its ledger rows (append-only ledger). We **add** a credit note and **new** ledger entries that reverse the effect.

---

## 3. What already exists in the codebase

### 3.1 Data model (backend)

- **CreditNote** and **CreditNoteItem** (in `app/models/sale.py`):
  - `original_invoice_id` → link to `SalesInvoice`
  - `reason`, `credit_note_date`, `total_exclusive`, `vat_*`, `total_inclusive`
  - Items: `quantity_returned`, `unit_price_exclusive`, `line_total_*`, `original_sale_item_id`, `batch_id` (optional)
- **Document numbering:** `DocumentService.get_credit_note_number` and CREDIT_NOTE in document sequences (startup) are already in place.
- **Schemas:** `CreditNoteCreate`, `CreditNoteResponse`, `CreditNoteItemCreate` in `app/schemas/sale.py`.

So the **tables and numbering** for a “return document” are there.

### 3.2 Inventory ledger

- **transaction_type** today: `PURCHASE`, `SALE`, `ADJUSTMENT`, `TRANSFER`, `OPENING_BALANCE` (see `app/models/inventory.py`).
- There is **no** `SALE_RETURN` or `RETURN` type yet. Reversal can be done in either of two ways:
  - **Option A:** New type `SALE_RETURN` with **positive** `quantity_delta`, `reference_type="credit_note"`, `reference_id=credit_note.id`. SnapshotService already uses `quantity_delta` (adds it to balance), so positive delta = stock back.
  - **Option B:** Reuse `ADJUSTMENT` with positive quantity and reference to credit note. Less explicit for reporting.

Recommendation: **Option A** — add `SALE_RETURN` (or `RETURN`) so reports can easily “exclude returns from COGS” or “net sales = sales − credit notes” and “COGS = COGS from SALE − COGS from SALE_RETURN”.

### 3.3 Frontend

- **Returns** in the Sales sidebar is a **placeholder**: the nav item points to `sales-returns` → `loadPage('sales-returns')` → `mainPage='sales'`, `subPage='returns'`. In `loadSalesSubPage(subPage)` (sales.js) there is **no** `case 'returns'`, so it falls through to **default** and shows the **Sales Invoices** list. So “Returns” does not show a dedicated returns/credit-notes UI.
- There are **no** sales credit note API endpoints (create/list credit notes for a branch, or “create return from invoice”) in the sales API. Purchases has supplier returns/credit notes (different flow).

### 3.4 Reports (gross profit / daily sales)

- **Gross profit** (`get_branch_gross_profit` in `app/api/sales.py`): uses only **SalesInvoice** (status BATCHED/PAID) for `sales_exclusive` and for COGS (invoice lines or ledger). **Credit notes are not subtracted.** So if we add returns without changing this, net sales and COGS would be overstated.

---

## 4. What needs to change

### 4.1 Backend

| Area | Change |
|------|--------|
| **Ledger** | Add a new `transaction_type` (e.g. **SALE_RETURN**) and use it for return entries. Each return line: **positive** `quantity_delta`, same `item_id`, `branch_id`, `batch_number`, `expiry_date`, `unit_cost` as the original sale (or from CreditNoteItem); `reference_type="credit_note"`, `reference_id=credit_note.id`. |
| **Snapshot** | Reuse existing `SnapshotService.upsert_inventory_balance(db, ..., quantity_delta)` — pass **positive** delta so stock increases. No schema change. |
| **Sales API** | Add endpoints, e.g.: (1) **POST /sales/credit-notes** — create credit note (body: original_invoice_id, reason, date, items with item_id, quantity_returned, unit_price, optional batch ref). Logic: create CreditNote + CreditNoteItem rows; for each line, create one or more InventoryLedger rows (SALE_RETURN, positive qty); call SnapshotService per ledger row; optionally update invoice status or a “returned” flag if needed. (2) **GET /sales/branch/{branch_id}/credit-notes** — list credit notes (filter by branch, date range) for the Returns UI. |
| **Validation** | Ensure `quantity_returned` ≤ quantity sold per line (and per batch if batch-level return). Ensure original invoice is BATCHED or PAID and belongs to the same branch/company. |
| **Document number** | Already in place (CREDIT_NOTE). Use it when creating the credit note. |

### 4.2 Frontend

| Area | Change |
|------|--------|
| **Returns page** | Add `case 'returns'` in `loadSalesSubPage` (sales.js) and implement **renderSalesReturnsPage()**: list credit notes (table: credit note #, date, original invoice, customer, amount, reason). “New return” → select a **batched/paid** invoice, then optionally prefill lines from that invoice and let user adjust quantities (and reason). Submit → call POST credit-notes API. |
| **From invoice** | Optional: on Sales Invoices list or invoice detail, add “Return” action for BATCHED/PAID invoices that opens the “create return” flow with that invoice pre-selected. |
| **API client** | In `api.js` (or equivalent), add methods for listing and creating sales credit notes. |

### 4.3 Reports (daily sales, margins)

| Area | Change |
|------|--------|
| **Gross profit / daily sales** | **Net sales:** Sum of `SalesInvoice.total_exclusive` for BATCHED/PAID in range **minus** sum of `CreditNote.total_exclusive` for credit notes in same branch/date range (use `credit_note_date` or `created_at`). **COGS:** Either (a) compute from invoice lines and subtract COGS for credit note lines (using stored cost at return), or (b) use ledger: COGS = sum(total_cost) for SALE entries in range minus sum(total_cost) for SALE_RETURN entries in range. Either way, ensure **gross profit = net sales − COGS** so that returns reduce both sales and COGS and margins stay correct. |
| **Per-day breakdown** | If the report has per-day breakdown, apply the same net sales and COGS logic per day (credit notes by date, ledger by date). |

---

## 5. End-to-end flow (target)

1. User goes to **Sales → Returns** and clicks “New return”, or clicks “Return” on a specific invoice.
2. User selects the **original invoice** (only BATCHED/PAID), enters **reason** and **credit note date**. System loads invoice lines; user can reduce quantities per line (and optionally select batch to return to).
3. On submit:
   - Backend creates **CreditNote** + **CreditNoteItem** rows.
   - For each credit note line, backend creates **InventoryLedger** rows with **SALE_RETURN**, **positive** quantity, same item/branch/batch/cost, `reference_type="credit_note"`, `reference_id=credit_note.id`.
   - **SnapshotService.upsert_inventory_balance** is called for each ledger row (stock goes back up).
   - Snapshot/search refresh can be triggered similarly to batching.
4. **Stock:** Increased by returned quantities; balances and ledger stay consistent.
5. **Daily sales / margins:** Reports use net sales (invoices − credit notes) and COGS net of SALE_RETURN (or credit note line cost), so the day’s sales and margins reflect the return.

---

## 6. Summary

| Topic | Current state | Change needed |
|-------|----------------|---------------|
| **Data model** | CreditNote + CreditNoteItem exist; document numbering ready | None |
| **Ledger** | Only SALE (negative qty) for sales | Add SALE_RETURN (positive qty), reference credit_note |
| **Snapshot** | Uses quantity_delta | Use same; pass positive delta on return |
| **Sales API** | No credit note endpoints | Add create + list credit notes; create ledger + snapshot on create |
| **Returns UI** | Placeholder (shows invoices) | Implement Returns page + “New return” from invoice |
| **Gross profit / daily sales** | Uses only invoices | Net sales = sales − credit notes; COGS net of SALE_RETURN (or credit note lines) |

This keeps the existing “append-only” ledger and invoice model, adds a clear path for reversing a sale via credit note and SALE_RETURN ledger entries, and ensures **affected stock counts**, **daily sales**, and **margins** all stay correct when a customer return is processed.
