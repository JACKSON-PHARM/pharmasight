# PharmaSight Unified Transaction Engine — Implementation Plan

This document is the **step-by-step implementation roadmap** for the Unified Transaction Engine, based on `TRANSACTION_ENGINE_SPEC.md`. It is organized into eight phases. Each phase lists files to modify, services involved, validation rules, rollback safety, and database transaction requirements.

**Reference documents:** `TRANSACTION_ENGINE_SPEC.md`, `TRANSACTION_ENGINE_AUDIT.md`.

---

## Architecture requirement: self-describing ledger

The inventory ledger **must store the document number directly** for auditability and reporting performance. The ledger remains the single source of truth and must be self-describing.

- **Add column:** `document_number` (e.g. `VARCHAR(100)` or `TEXT`, nullable for backward compatibility during transition).
- **Retain:** `reference_type` and `reference_id`; they remain the canonical link to the document. `document_number` is a denormalized copy at write time.
- **Semantics:** At the time each ledger row is created, the human-readable document number (e.g. `SD-BR001-000339`, `CN-0005`, `GRN-2026-001`) is resolved from the document and stored on the row. Reports and audits can read from the ledger without joining to document tables.

---

## Phase 1: Schema updates

**Objective:** Add `document_number` to `inventory_ledger`; backfill existing rows; ensure all future ledger writes populate it.

### 1.1 Schema migration

- **What:** Add nullable column `document_number` to `inventory_ledger`.
- **How:** New migration file in `database/migrations/` with next available version (e.g. `073_inventory_ledger_document_number.sql`).
- **Content:**
  - `ALTER TABLE inventory_ledger ADD COLUMN IF NOT EXISTS document_number VARCHAR(100);`
  - `COMMENT ON COLUMN inventory_ledger.document_number IS 'Human-readable document number at time of write (e.g. INV-1024, CN-0005). Denormalized for audit and reporting.';`
- **Rollback:** Reversible with `ALTER TABLE inventory_ledger DROP COLUMN IF EXISTS document_number;` (only before backfill if desired; after backfill, rollback is optional and may leave historical rows without the column).

**Files to create/modify:**

| File | Action |
|------|--------|
| `database/migrations/073_inventory_ledger_document_number.sql` | Create: ADD COLUMN + comment |

**Services involved:** MigrationService (applies migration on deploy/startup or provisioning). No application code yet.

**Validation rules:** None in this step. Column is nullable so existing rows remain valid.

**Rollback safety:** Migration is additive. If rollback script is provided, it drops the column; application code must not assume column exists until migration is applied everywhere.

**Database transaction requirements:** Migration runs in its own transaction (per MigrationService). No application transaction in this phase.

---

### 1.2 Backfill existing ledger rows

- **What:** For every existing row in `inventory_ledger`, set `document_number` from the referenced document using `(reference_type, reference_id)`.
- **How:** Same migration file or a separate one (e.g. `074_backfill_ledger_document_number.sql`) that runs after 073. Use SQL `UPDATE ... FROM` joining to the appropriate document table per `reference_type`.
- **Mapping:**
  - `reference_type = 'sales_invoice'` → `sales_invoices.invoice_no` (e.g. SD-BR001-000339).
  - `reference_type = 'grn'` → `grns.grn_no`.
  - `reference_type = 'purchase_invoice'` → `supplier_invoices.invoice_number` (system number).
  - `reference_type = 'supplier_return'` → supplier return document number (e.g. from `supplier_returns` if such a column exists; else use a generated label like `SR-{id}` or add a column in Phase 2).
  - `reference_type = 'branch_transfer'` → `branch_transfers.transfer_number`.
  - `reference_type = 'branch_receipt'` → `branch_receipts.receipt_number`.
  - `reference_type = 'STOCK_TAKE'` → `stock_take_sessions.session_code` or equivalent.
  - `MANUAL_ADJUSTMENT`, `BATCH_QUANTITY_CORRECTION`, `BATCH_METADATA_CORRECTION` → e.g. `'ADJ'` or leave NULL (or use a convention like `ADJ-{date}`).
  - `OPENING_BALANCE` → e.g. `'OPENING'` or NULL.
- **Batching:** If the table is large, run backfill in batches (e.g. by `id` or `created_at`) to avoid long locks.
- **Idempotency:** Backfill can be re-run (UPDATE only where document_number IS NULL) so it is safe to run again.

**Files to create/modify:**

| File | Action |
|------|--------|
| `database/migrations/074_backfill_ledger_document_number.sql` | Create: UPDATE statements per reference_type (or single script with CASE/joins) |

**Services involved:** MigrationService. No application service.

**Validation rules:** None. Backfill only sets document_number from existing documents.

**Rollback safety:** No rollback of data needed; column can remain. If column is dropped later, backfill is lost.

**Database transaction requirements:** Backfill can run in one transaction per batch or one large transaction; recommend batched commits for very large tables.

---

### 1.3 Future ledger writes — document_number population

- **What:** Every code path that inserts into `inventory_ledger` must set `document_number` at insert time (when a document exists). For documents without a number (e.g. some adjustments), use a convention (e.g. `'ADJ'`, `'OPENING'`) or leave NULL if business accepts it.
- **How:** Introduce a small helper or convention used by all ledger writers:
  - **Sales (SALE):** Use `invoice.invoice_no` (already available when batching).
  - **Credit note (SALE_RETURN):** Use `credit_note.credit_note_no` (from DocumentService.get_credit_note_number when creating the credit note).
  - **GRN (PURCHASE):** Use `grn.grn_no`.
  - **Supplier invoice (PURCHASE):** Use `invoice.invoice_number` (system number).
  - **Supplier return (PURCHASE_RETURN):** Use supplier return document number (ensure table has a column or derive once).
  - **Branch transfer (TRANSFER_OUT):** Use `transfer.transfer_number`.
  - **Branch receipt (TRANSFER_IN):** Use `receipt.receipt_number`.
  - **Stock take (ADJUSTMENT):** Use `session.session_code`.
  - **Manual / batch corrections (ADJUSTMENT):** Use `'ADJ'` or similar; optional.
  - **Opening balance (OPENING_BALANCE):** Use `'OPENING'` or NULL.
- **Where:** Phase 4 (Ledger integration) will list every insert site and add `document_number` there. Phase 1 only defines the rule and the migration/backfill.

**Summary for Phase 1:**

| Deliverable | Description |
|-------------|-------------|
| Migration 073 | ADD COLUMN document_number |
| Migration 074 | Backfill document_number from documents |
| Convention | All future inserts set document_number (enforced in Phase 4) |

---

## Phase 2: Movement type additions

**Objective:** Support all spec movement types: SALE, SALE_RETURN, PURCHASE, PURCHASE_RETURN, ADJUSTMENT, TRANSFER_IN, TRANSFER_OUT, OPENING_BALANCE. Current code uses TRANSFER for both directions; optionally standardize to TRANSFER_IN / TRANSFER_OUT.

### 2.1 Backend: allow new transaction_type values

- **What:** Ensure the ledger and any validation accept: SALE_RETURN, PURCHASE_RETURN, TRANSFER_IN, TRANSFER_OUT. SALE, PURCHASE, ADJUSTMENT, OPENING_BALANCE already exist. No DB constraint on transaction_type today (string); only application code and reporting need to handle new values.
- **Where:** No schema change required unless a check constraint exists. If there is an enum or check, add the new values.

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/models/inventory.py` | Optional: update comment/docstring to list all 8 movement types. No code change if transaction_type is free string. |
| `backend/app/schemas/inventory.py` | Optional: extend description of transaction_type to include SALE_RETURN, PURCHASE_RETURN, TRANSFER_IN, TRANSFER_OUT. |

### 2.2 Supplier return: switch to PURCHASE_RETURN

- **What:** Today supplier return uses `transaction_type="PURCHASE"` with negative quantity_delta. Per spec, use **PURCHASE_RETURN** with negative quantity_delta.
- **Where:** `backend/app/api/supplier_management.py` (approve_supplier_return). Change the InventoryLedger creation to use `transaction_type="PURCHASE_RETURN"`.
- **Reporting:** Any query that filters by transaction_type for “purchases” must exclude or include PURCHASE_RETURN as appropriate (e.g. COGS from purchases: exclude PURCHASE_RETURN; net purchases: PURCHASE − PURCHASE_RETURN).

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/api/supplier_management.py` | Set transaction_type to `PURCHASE_RETURN` when creating ledger rows on approve. |

### 2.3 Branch transfer: optional TRANSFER_IN / TRANSFER_OUT

- **What:** Spec standardizes on TRANSFER_IN (receipt) and TRANSFER_OUT (send). Current code uses TRANSFER with sign. Options: (A) Keep TRANSFER and document sign in spec only; (B) Add new migration that adds a check or enum and then change branch_inventory.py to write TRANSFER_OUT on send and TRANSFER_IN on receive.
- **Recommendation:** Implement (B) in this phase: when completing a transfer, write `TRANSFER_OUT` for supplying-branch rows and `TRANSFER_IN` for receiving-branch rows. No backfill of historical TRANSFER rows required if reporting treats TRANSFER + negative as OUT and TRANSFER + positive as IN for backward compatibility.

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/api/branch_inventory.py` | In complete_branch_transfer: set transaction_type=`TRANSFER_OUT` for supplying-branch ledger rows. In confirm_branch_receipt: set transaction_type=`TRANSFER_IN` for receiving-branch ledger rows. |

**Services involved:** InventoryService (unchanged), SnapshotService (unchanged). No new service.

**Validation rules:** Per spec, TRANSFER_OUT must have negative quantity_delta and reference_type `branch_transfer`; TRANSFER_IN must have positive quantity_delta and reference_type `branch_receipt`.

**Rollback safety:** Changing transaction_type is backward compatible if reports treat old TRANSFER and new TRANSFER_IN/TRANSFER_OUT consistently.

**Database transaction requirements:** Unchanged; existing transfer and receipt flows already run in one transaction with snapshot.

---

## Phase 3: Customer return backend APIs

**Objective:** Implement create credit note and list credit notes APIs; validate return_qty ≤ sold_qty − already_returned_qty; create SALE_RETURN ledger rows with original batch and cost; run document + ledger + snapshot in one transaction.

### 3.1 API: create credit note (POST)

- **Endpoint:** e.g. `POST /api/sales/credit-notes` (or under existing sales router).
- **Body:** original_invoice_id, reason, credit_note_date, items: [{ item_id, original_sale_item_id, quantity_returned, unit_name or base }]. Optionally idempotency_key.
- **Validation:**
  - Original invoice exists, status in (BATCHED, PAID), same company/branch as current context.
  - For each line: resolve sold_qty from sales_invoice_items (convert to base units). Resolve already_returned_qty = sum(credit_note_items.quantity_returned) over all credit notes that reference the same original_sale_item_id (and are posted). Enforce **return_qty ≤ sold_qty − already_returned_qty**.
  - At least one line with quantity_returned > 0.
- **Workflow (single transaction):** Lock original invoice (FOR UPDATE) if desired. Get credit_note_no from DocumentService.get_credit_note_number. Insert credit_notes row. Insert credit_note_items rows. For each item, get batch/cost from original invoice line or SALE ledger (original batch and unit_cost). Insert inventory_ledger rows: transaction_type=SALE_RETURN, quantity_delta=+quantity_returned (base), reference_type=credit_note, reference_id=credit_note.id, **document_number=credit_note.credit_note_no**, batch_number, expiry_date, unit_cost, total_cost from original sale. Call SnapshotService.upsert_inventory_balance for each row. Commit.
- **Batch integrity:** SALE_RETURN must restore original batch (batch_number, expiry_date) and same unit_cost so COGS reversal is correct.

**Files to create/modify:**

| File | Action |
|------|--------|
| `backend/app/api/sales.py` | Add router for credit notes: POST create, GET list by branch/date. Implement create with validation and ledger + snapshot in one transaction. |
| `backend/app/schemas/sale.py` | Add or extend CreditNoteCreate (items with quantity_returned, original_sale_item_id), CreditNoteResponse. |
| `backend/app/services/document_service.py` | Already has get_credit_note_number; ensure used when creating credit note. |

**Services involved:** DocumentService (credit note number), SnapshotService (upsert_inventory_balance), SnapshotRefreshService (optional post-commit). New or existing sales service layer for “get already_returned_qty” and “get original batch/cost”.

**Validation rules:** return_qty ≤ sold_qty − already_returned_qty per line; invoice BATCHED/PAID; same company/branch; at least one line.

**Rollback safety:** On any exception, roll back entire transaction; no partial credit note or ledger rows.

**Database transaction requirements:** Single transaction: insert credit_notes + credit_note_items, insert all ledger rows, all snapshot updates, then commit. Lock original invoice (FOR UPDATE) before validation if strict concurrency is required.

### 3.2 API: list credit notes (GET)

- **Endpoint:** e.g. `GET /api/sales/branch/{branch_id}/credit-notes` with optional query params (date_from, date_to, limit, offset).
- **Response:** List of credit notes with id, credit_note_no, original_invoice_id, credit_note_date, reason, total_exclusive, items (summary or full). No ledger writes.

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/api/sales.py` | Add GET endpoint; query credit_notes by branch_id and optional date filter. |

---

## Phase 4: Ledger integration (document_number and movement types)

**Objective:** Ensure every ledger write path sets `document_number` and uses the correct `transaction_type` per spec. No new features; consistency and completeness.

### 4.1 Ledger write sites (checklist)

For each site that inserts into `inventory_ledger`, add `document_number` and confirm `transaction_type` / `reference_type`:

| Site | File | transaction_type | reference_type | document_number source |
|------|------|------------------|----------------|------------------------|
| Sales invoice batch | sales.py | SALE | sales_invoice | invoice.invoice_no |
| Quotation → invoice | quotations.py | SALE | sales_invoice | db_invoice.invoice_no (after flush) |
| GRN create | purchases.py | PURCHASE | grn | db_grn.grn_no |
| Supplier invoice batch | purchases.py | PURCHASE | purchase_invoice | invoice.invoice_number |
| Supplier return approve | supplier_management.py | PURCHASE_RETURN | supplier_return | ret.return_number or id-based (add column if needed) |
| Credit note create | sales.py (new) | SALE_RETURN | credit_note | credit_note.credit_note_no |
| Manual adjust | items.py | ADJUSTMENT | MANUAL_ADJUSTMENT | e.g. 'ADJ' or NULL |
| Batch qty correction | items.py | ADJUSTMENT | BATCH_QUANTITY_CORRECTION | e.g. 'ADJ' or NULL |
| Batch metadata correction | items.py | ADJUSTMENT | BATCH_METADATA_CORRECTION | e.g. 'ADJ' or NULL |
| Stock take complete | stock_take.py | ADJUSTMENT | STOCK_TAKE | session.session_code |
| Branch transfer complete | branch_inventory.py | TRANSFER_OUT | branch_transfer | transfer.transfer_number |
| Branch receipt confirm | branch_inventory.py | TRANSFER_IN | branch_receipt | receipt.receipt_number |
| Excel/opening balance | excel_import_service.py | OPENING_BALANCE | OPENING_BALANCE | 'OPENING' or NULL |

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/api/sales.py` | Add document_number=invoice.invoice_no when creating SALE ledger rows. |
| `backend/app/api/quotations.py` | Set document_number on ledger entries from db_invoice.invoice_no after invoice is created. |
| `backend/app/api/purchases.py` | Add document_number=db_grn.grn_no (GRN); document_number=invoice.invoice_number (supplier invoice). |
| `backend/app/api/supplier_management.py` | Add document_number for supplier return (ensure supplier_returns has a number column or use consistent convention). Use PURCHASE_RETURN. |
| `backend/app/api/items.py` | Add document_number='ADJ' or NULL for MANUAL_ADJUSTMENT, BATCH_QUANTITY_CORRECTION, BATCH_METADATA_CORRECTION. |
| `backend/app/api/stock_take.py` | Add document_number=session.session_code (or equivalent) for STOCK_TAKE ledger rows. |
| `backend/app/api/branch_inventory.py` | Add document_number=transfer.transfer_number (TRANSFER_OUT), document_number=receipt.receipt_number (TRANSFER_IN). Use TRANSFER_OUT/TRANSFER_IN. |
| `backend/app/services/excel_import_service.py` | Add document_number='OPENING' or NULL for OPENING_BALANCE. |
| `backend/app/models/inventory.py` | Add `document_number = Column(String(100), nullable=True)` to InventoryLedger model. |

**Services involved:** All existing services that create ledger rows; DocumentService where document number is generated.

**Validation rules:** Per spec: correct sign of quantity_delta and allowed reference_type for each transaction_type.

**Rollback safety:** No change to transaction boundaries; only adding a column value. Rollback = revert code; existing rows keep existing document_number (or NULL if not backfilled).

**Database transaction requirements:** Unchanged; each write path already runs in one transaction with snapshot.

---

## Phase 5: Snapshot updates

**Objective:** Confirm SnapshotService is used correctly for all new movement types and that no code assumes only negative sales.

### 5.1 SnapshotService behavior

- **Current behavior:** `upsert_inventory_balance(db, company_id, branch_id, item_id, quantity_delta)` adds quantity_delta to current_stock. Sign-agnostic.
- **SALE_RETURN:** Pass positive quantity_delta; stock increases. No change to SnapshotService.
- **PURCHASE_RETURN:** Pass negative quantity_delta; stock decreases. No change.

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/services/snapshot_service.py` | No code change. Optional: add a short comment that positive (e.g. SALE_RETURN) and negative (e.g. PURCHASE_RETURN) are both supported. |

### 5.2 Call sites for new flows

- **Credit note (SALE_RETURN):** In the same transaction after inserting ledger rows, call SnapshotService.upsert_inventory_balance for each row with entry.quantity_delta (positive). Implemented in Phase 3.
- **Supplier return (PURCHASE_RETURN):** Already calls SnapshotService with negative delta; no change beyond transaction_type in Phase 2.

**Services involved:** SnapshotService only.

**Validation rules:** None new. Caller must pass the same quantity_delta as written to the ledger.

**Rollback safety:** Same transaction as ledger; rollback undoes snapshot update.

**Database transaction requirements:** Snapshot update must run inside the same transaction as the ledger insert (already required by spec).

---

## Phase 6: Reporting updates

**Objective:** Net sales and COGS by including credit notes and SALE_RETURN; use document_number from ledger where beneficial; support PURCHASE_RETURN in any purchase reporting.

### 6.1 Gross profit / sales report

- **Current:** Sales = sum(sales_invoices.total_exclusive) for BATCHED/PAID in range. COGS = from invoice lines or SALE ledger.
- **Change:** Net sales = sum(sales_invoices.total_exclusive) − sum(credit_notes.total_exclusive) for the same branch and date range (by credit_note_date or created_at). COGS = sum(ledger.total_cost where transaction_type=SALE and reference in range) − sum(ledger.total_cost where transaction_type=SALE_RETURN and reference in range). Alternatively derive COGS from invoice lines minus credit note line costs.
- **Files:** `backend/app/api/sales.py` (get_branch_gross_profit, _compute_cogs_from_invoice_lines or equivalent). Add queries for credit notes and SALE_RETURN ledger rows; subtract from sales and COGS.

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/api/sales.py` | In gross profit endpoint, subtract credit note totals from sales; subtract SALE_RETURN total_cost from COGS (or compute from credit_note_items with cost). |

### 6.2 Item movement report

- **Current:** Resolves (reference_type, reference_id) to document_type and reference string (e.g. invoice_no) via joins.
- **Change:** Prefer ledger.document_number when present for the reference column (faster, no join). Fall back to existing resolution when document_number is NULL (e.g. old rows). Add resolution for reference_type=credit_note (document_type=Credit Note, reference=credit_note_no).

**Files to modify:**

| File | Action |
|------|--------|
| `backend/app/services/item_movement_report_service.py` | When building rows, use row.document_number if not null; else keep existing ref_map resolution. Add credit_note to _resolve_references_batch for legacy rows. Optionally add supplier_return if not present. |

### 6.3 Other reports

- Any report that aggregates by transaction_type (e.g. purchase report) should include PURCHASE_RETURN where “net purchases” or “returns” are shown. No new movement types beyond what Phase 2 and 4 define.

**Services involved:** Sales API, item_movement_report_service.

**Validation rules:** None. Reporting is read-only.

**Rollback safety:** Revert code; reports return to previous behavior.

**Database transaction requirements:** Read-only queries; no transaction requirement beyond normal read consistency.

---

## Phase 7: Frontend UI ✅ Implemented

**Objective:** Returns page (list credit notes, create return from invoice); optional “Return” action on invoice detail.

### 7.1 Sales Returns page

- **What:** When user navigates to Sales → Returns, render a dedicated Returns view (not the invoices list). List credit notes (table: credit note #, date, original invoice, customer, amount, reason). “New return” button opens create flow.
- **Where:** `frontend/js/pages/sales.js`. Add case `'returns'` in loadSalesSubPage; implement renderSalesReturnsPage(), fetch credit notes from GET /api/sales/branch/{id}/credit-notes, render table. New return: modal or page to select invoice, then lines and quantities, reason, date; submit POST /api/sales/credit-notes.
- **Validation:** Frontend can pre-validate quantity ≤ available to return (from already_returned_qty if API exposes it, or from invoice line quantity). Backend remains authority.

**Files to modify:**

| File | Action |
|------|--------|
| `frontend/js/pages/sales.js` | Add case 'returns' in loadSalesSubPage; implement renderSalesReturnsPage, create return modal/flow, call new API. |
| `frontend/js/api.js` | Add sales.creditNotes.create, sales.creditNotes.list (or equivalent). |

### 7.2 Invoice “Return” action (optional)

- **What:** On Sales Invoices list or invoice detail, add “Return” button for BATCHED/PAID invoices. Click opens create-return flow with that invoice pre-selected.
- **Files:** Same as above; create-return flow accepts optional original_invoice_id and pre-fills lines.

**Validation rules:** Same as backend; frontend can disable Return when invoice is not BATCHED/PAID.

**Rollback safety:** N/A (UI only). Failed API returns error; user can correct and retry.

**Database transaction requirements:** N/A.

---

## Phase 8: Testing strategy ✅ Implemented

**Objective:** Automated and manual tests to ensure movement types, validation, document_number, and transaction safety.

### 8.1 Unit / service tests

- **Return validation:** For a given invoice line, compute sold_qty and already_returned_qty; assert return_qty ≤ sold_qty − already_returned_qty rejects over-return and accepts valid return.
- **Batch/cost:** When creating SALE_RETURN, assert ledger rows have same batch_number, expiry_date, unit_cost as original sale (from invoice or SALE ledger).
- **Document number:** For each movement type, assert that new ledger rows have document_number set (where applicable).

**Files to create/modify:**

| File | Action |
|------|--------|
| `backend/tests/` (or project test dir) | Add tests for credit note creation (validation, ledger rows, snapshot). Add tests for document_number on ledger creation (sales, GRN, credit note, etc.). |

### 8.2 Integration tests

- **Customer return flow:** Create invoice, batch it, create credit note for one line with quantity_returned &lt;= sold. Assert credit_notes and credit_note_items exist; assert SALE_RETURN ledger rows with positive quantity_delta; assert inventory_balances increased; assert second return for same line with qty that would exceed sold fails.
- **Transaction atomicity:** Force failure after ledger insert but before snapshot (e.g. mock); assert no ledger row committed (transaction rolled back).

**Services involved:** Test harness, DB fixture or test DB.

### 8.3 Manual test matrix

| Scenario | Steps | Expected |
|----------|--------|----------|
| Create credit note | Select batched invoice, set return qty &lt;= sold, submit | Credit note created; stock up; ledger SALE_RETURN rows; document_number set. |
| Over-return | Set return qty &gt; sold for a line | 400, no credit note. |
| Double return | Return same line twice within limit | Both succeed; total returned ≤ sold. |
| Gross profit | Create sale then return; run gross profit report | Net sales and COGS reflect return. |
| Supplier return | Approve supplier return | Ledger PURCHASE_RETURN; stock down; document_number set. |
| Transfer | Complete transfer, confirm receipt | TRANSFER_OUT and TRANSFER_IN rows; document_number on both. |

**Rollback safety:** Tests should not leave partial data; use transactions or test DB reset.

**Database transaction requirements:** Integration tests should assert that on failure, no partial commit occurs.

---

## Summary: phase order and dependencies

| Phase | Depends on | Delivers |
|-------|------------|----------|
| 1. Schema updates | — | document_number column; backfill; convention for future writes |
| 2. Movement types | — | PURCHASE_RETURN, TRANSFER_IN/OUT; supplier return and branch flows updated |
| 3. Customer return APIs | 1 (column exists) | POST/GET credit notes; validation; SALE_RETURN ledger + snapshot in one tx |
| 4. Ledger integration | 1, 2 | Every ledger write sets document_number and correct transaction_type |
| 5. Snapshot updates | 3 | Confirmed snapshot used for SALE_RETURN/PURCHASE_RETURN; no code change |
| 6. Reporting | 3, 4 | Gross profit nets returns; movement report uses document_number; credit_note resolved |
| 7. Frontend UI | 3 | Returns page; create return; optional invoice Return action |
| 8. Testing | 1–7 | Tests for validation, batch/cost, document_number, atomicity |

**Recommended implementation order:** 1 → 2 → 4 (so all writes have document_number and correct types) → 3 → 5 → 6 → 7 → 8. Phase 4 can be done in parallel with 3 if desired, but 3 depends on 1 for the column.

---

## Special attention checklist

- **Movement types:** SALE, SALE_RETURN, PURCHASE, PURCHASE_RETURN, ADJUSTMENT, TRANSFER_IN, TRANSFER_OUT, OPENING_BALANCE — all covered in Phase 2 and 4.
- **Return validation:** return_qty ≤ sold_qty − already_returned_qty — enforced in Phase 3 (customer return API).
- **Batch integrity:** SALE_RETURN restores original batch and cost — enforced in Phase 3 when building ledger rows from original_sale_item_id / invoice line / SALE ledger.
- **Transaction safety:** Document creation + ledger writes + snapshot updates in one database transaction — required in Phase 3 (credit note) and already present for supplier return, sales batch, transfer, etc.; Phase 4 does not change boundaries.

---

*End of implementation plan. Implementation must follow TRANSACTION_ENGINE_SPEC.md and this plan.*

---

## Engine status: what is covered and what’s next

### Is “add item in the transaction table” handled by the engine?

**Yes.** The “transaction table” is **inventory_ledger**. Every stock movement that the engine cares about now:

1. Inserts one or more rows into **inventory_ledger** with:
   - `transaction_type` (SALE, SALE_RETURN, PURCHASE, PURCHASE_RETURN, ADJUSTMENT, TRANSFER_IN, TRANSFER_OUT, OPENING_BALANCE)
   - `quantity_delta`, `reference_type`, `reference_id`, **document_number**
   - batch/cost where applicable
2. Calls **SnapshotService.upsert_inventory_balance** in the same transaction (with document_number and negative-stock check).

There is no single “add_item_to_transaction” API. Each flow (sales batch, GRN, credit note, adjustment, transfer, receipt, stock take, opening balance) does “create/use document → insert into ledger → snapshot” in one transaction. So **adding items to the transaction table (ledger) is fully aligned with the engine** and uses the same movement types, document numbers, and snapshot rules.

### Is “create document” handled by the engine?

**Partially.**

- **Document number generation** is handled by the engine:
  - **DocumentNumberService** (and **DocumentService** wrappers) generate numbers in the format `DOC_TYPE-BRANCH_CODE-SEQUENCE` (e.g. INV-01-000245, CN-01-000014, GRN-02-000099).
  - Used for: sales invoices, credit notes, GRN, supplier returns, branch transfers/receipts (and optionally adjustments/opening as “ADJ”/“OPENING”).
- **Creating the document row** (e.g. insert into `sales_invoices`, `credit_notes`, `grns`, etc.) is **not** a single engine function. Each module (sales, purchases, supplier_management, branch_inventory, etc.) still has its own “create document” logic; they call DocumentService/DocumentNumberService for the number, then insert the document and ledger rows. So:
  - **Numbering** = engine (DocumentNumberService).
  - **Document row creation** = per-module, but all of them follow the pattern: get number → create document → write ledger with that document_number → update snapshot.

If you want a single “create document” function in the engine, that would be a new layer (e.g. a service that takes document type + payload and dispatches to the right document creation + ledger + snapshot flow). The current design keeps document creation in existing APIs and standardizes numbering and ledger/snapshot behavior.

### What’s next (remaining phases)

| Phase | Status   | What it does |
|-------|----------|--------------|
| **6. Reporting** | Not done | Gross profit nets credit notes and SALE_RETURN; item movement report uses `ledger.document_number`; resolve `credit_note` in reports. |
| **7. Frontend**  | Not done | Sales → Returns page (list credit notes, create return from invoice); optional “Return” on invoice. |
| **8. Testing**   | Not done | Tests for return validation, batch/cost, document_number, transaction atomicity, over-return rejection. |

Recommended order: **Phase 6 (reporting)** next, then **Phase 7 (frontend)**, then **Phase 8 (testing)**.
