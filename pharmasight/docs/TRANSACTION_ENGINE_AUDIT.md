# PharmaSight Transaction Engine — Full Architectural Audit

This document is a **technical audit** of the current inventory and transaction system to assess readiness for a **unified transaction engine** supporting:

- Sales invoices  
- Customer returns (credit notes)  
- Purchases / goods receipts  
- Supplier returns  
- Inventory adjustments  

**Scope:** Study only. No implementation. All findings are from tracing the live codebase.

---

## 1. TRACE CURRENT INVENTORY FLOW

### 1.1 Sales invoice creation → batching → ledger → snapshot → balances

End-to-end flow for a **sales invoice** from creation to stock deduction:

#### Step 1: Sales invoice creation (DRAFT)

- **Location:** `app/api/sales.py` — `add_sales_invoice_item`, `create_sales_invoice`, etc.
- **Effect:** Rows in `sales_invoices` and `sales_invoice_items`. **No ledger or snapshot.** Status = DRAFT.
- **Stock:** Unchanged.

#### Step 2: Batching (DRAFT → BATCHED)

- **Location:** `app/api/sales.py` — `batch_sales_invoice()` (POST `/invoice/{invoice_id}/batch`).
- **Locking:** Invoice row is locked with `.with_for_update()` to prevent double-batch and races.
- **Validation:** Invoice must be DRAFT; must have items. For each line:
  - `InventoryService.convert_to_base_units()` converts requested quantity to base (retail) units.
  - `InventoryService.check_stock_availability()` ensures sufficient stock.
  - `InventoryService.allocate_stock_fefo()` returns a **list of allocations** (one per batch consumed: batch_number, expiry_date, quantity, unit_cost, ledger_entry_id).
- **Ledger creation:** For **each allocation** (each batch consumed), one `InventoryLedger` row is created:
  - `transaction_type="SALE"`
  - `reference_type="sales_invoice"`
  - `reference_id=invoice.id`
  - `quantity_delta=-qty` (negative)
  - `unit_cost`, `total_cost=uc*qty`, `batch_number`, `expiry_date` from allocation
  - `company_id`, `branch_id`, `item_id`, `created_by`
- **Invoice update:** `invoice_item.unit_cost_used = batch_cost` (per base unit); `invoice_item.batch_id = allocations[0]["ledger_entry_id"]` (first allocation’s ledger id). Invoice set to `batched=True`, `status="BATCHED"` (or `"PAID"` if cash).
- **Persistence:** All ledger rows are `db.add(entry)` then `db.flush()`.

#### Step 3: SnapshotService after ledger flush

- **Location:** Same `batch_sales_invoice()` block, after `db.flush()`.
- **Per ledger entry:**  
  `SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)`  
  So **negative** `quantity_delta` is passed; snapshot **decrements** current_stock.
- **Search snapshot:** For each invoice item, `SnapshotService.upsert_search_snapshot_last_sale(db, company_id, branch_id, item_id, invoice.invoice_date)`.
- **Refresh:** `SnapshotRefreshService.schedule_snapshot_refresh(db, ...)` per item (async refresh of item_branch_snapshot).

#### Step 4: Commit

- **Location:** `db.commit()` in the same endpoint. Ledger, invoice, and snapshot updates are in **one transaction**.
- **Post-commit:** Order book processing (`OrderBookService.process_sale_for_order_book`) runs in a separate try/except (no transaction link).

#### Step 5: Inventory balances table

- **Location:** `app/services/snapshot_service.py` — `upsert_inventory_balance()`.
- **SQL:**  
  `INSERT INTO inventory_balances (company_id, branch_id, item_id, current_stock, updated_at) VALUES (...qty...) ON CONFLICT (item_id, branch_id) DO UPDATE SET current_stock = inventory_balances.current_stock + EXCLUDED.current_stock`.
- **Semantics:** The passed `quantity_delta` is **added** to `current_stock`. So for a sale, a **negative** value is passed and stock decreases. **The snapshot is sign-agnostic:** it just adds the delta.

### 1.2 Where ledger entries are created (all flows)

| Flow | File | Function / trigger | transaction_type | reference_type | quantity_delta sign |
|------|------|--------------------|------------------|----------------|----------------------|
| Sales invoice batch | sales.py | batch_sales_invoice | SALE | sales_invoice | Negative |
| Quotation → invoice | quotations.py | convert_quotation_to_invoice | SALE | sales_invoice | Negative |
| GRN | purchases.py | create_grn (POST grn) | PURCHASE | grn | Positive |
| Supplier invoice batch | purchases.py | batch_supplier_invoice | PURCHASE | purchase_invoice | Positive |
| Supplier return approve | supplier_management.py | approve_supplier_return | PURCHASE | supplier_return | Negative |
| Manual stock adjust | items.py | adjust_stock | ADJUSTMENT | MANUAL_ADJUSTMENT | + or − |
| Batch quantity correction | items.py | post_batch_quantity_correction | ADJUSTMENT | BATCH_QUANTITY_CORRECTION | + or − |
| Batch metadata correction | items.py | post_batch_metadata_correction | ADJUSTMENT | BATCH_METADATA_CORRECTION | − then + (pair) |
| Stock take complete | stock_take.py | complete_stock_take_session | ADJUSTMENT | STOCK_TAKE | + or − |
| Branch transfer (send) | branch_inventory.py | complete_branch_transfer | TRANSFER | branch_transfer | Negative (supplying branch) |
| Branch receipt (receive) | branch_inventory.py | confirm_branch_receipt | TRANSFER | branch_receipt | Positive (receiving branch) |
| Excel import opening balance | excel_import_service.py | opening balance creation | OPENING_BALANCE | OPENING_BALANCE | Positive |

### 1.3 Batch allocation (sales) — how quantity_delta is written

- **allocate_stock_fefo** (`app/services/inventory_service.py`):  
  Groups ledger by `(batch_number, expiry_date, unit_cost, id)` and sums `quantity_delta` per group; filters to positive balance; orders by FEFO (expiry asc, batch_number asc). Then iterates and allocates “take = min(remaining_needed, available)” per batch until need is met. Returns a list of `{ batch_number, expiry_date, quantity, unit_cost, ledger_entry_id }`.
- **So:** One **allocation** per (batch_number, expiry_date, unit_cost) consumed. Each allocation becomes **one** SALE ledger row with `quantity_delta = -allocation.quantity`.  
- **Example:** Panadol 3 tablets: Batch A 2, Batch B 1 → two allocations → two ledger rows: SALE −2 (batch A), SALE −1 (batch B). So **one ledger entry per batch consumed** as required.

### 1.4 SnapshotService update pattern

- After **every** ledger INSERT in the same transaction: `SnapshotService.upsert_inventory_balance(db, company_id, branch_id, item_id, quantity_delta)`.
- No branching on transaction_type: the **same** `quantity_delta` from the ledger row is passed. So negative (sale, transfer out, supplier return) decreases stock; positive (purchase, adjustment in, transfer in) increases it.

---

## 2. ANALYZE THE INVENTORY LEDGER

### 2.1 Model and table

**Source:** `app/models/inventory.py` — `InventoryLedger`, table `inventory_ledger`.

### 2.2 Fields

| Field | Type | Nullable | Purpose |
|-------|------|----------|---------|
| id | UUID | PK | Unique row id |
| company_id | UUID | NOT NULL, FK companies | Tenant/company |
| branch_id | UUID | NOT NULL, FK branches | Branch |
| item_id | UUID | NOT NULL, FK items | Product |
| batch_number | String(200) | YES | Batch/lot |
| expiry_date | Date | YES | Expiry |
| transaction_type | String(50) | NOT NULL | Movement type (see below) |
| reference_type | String(50) | YES | Document type (e.g. sales_invoice, grn) |
| reference_id | UUID | YES | FK to document (e.g. invoice id) |
| quantity_delta | Numeric(20,4) | NOT NULL | Positive = in, negative = out (base units). Constraint: != 0 |
| unit_cost | Numeric(20,4) | NOT NULL | Cost per base unit |
| total_cost | Numeric(20,4) | NOT NULL | quantity_delta * unit_cost (can be negative in metadata correction) |
| created_by | UUID | NOT NULL | User |
| created_at | TIMESTAMP TZ | server default | When |
| notes | String(2000) | YES | Optional (e.g. adjustment reason) |
| batch_cost | Numeric(20,4) | YES | Batch-specific cost (FIFO/LIFO) |
| remaining_quantity | Integer | YES | Legacy/tracking |
| is_batch_tracked | Boolean | default True | Batch tracked flag |
| parent_batch_id | UUID FK ledger | YES | Batch splits |
| split_sequence | Integer | default 0 | Split ordering |

**Not present on ledger:** `document_number`. Document numbers (e.g. invoice_no, grn_no) live on the **document** tables; reports resolve `(reference_type, reference_id)` to document and then show that document’s number.

### 2.3 Movement types in use

- **PURCHASE** — GRN, supplier invoice batch. Positive delta. Supplier return uses **PURCHASE** with **negative** delta and `reference_type="supplier_return"`.
- **SALE** — Sales invoice batch, quotation convert. Negative delta.
- **ADJUSTMENT** — Manual adjust, batch quantity correction, batch metadata correction, stock take. + or −.
- **TRANSFER** — Branch transfer out (negative), branch receipt (positive). Same type for both directions; direction is from sign of quantity_delta.
- **OPENING_BALANCE** — Excel import / opening balance. Positive.

### 2.4 Reference fields

- **reference_type** values observed: `sales_invoice`, `grn`, `purchase_invoice`, `supplier_return`, `MANUAL_ADJUSTMENT`, `BATCH_QUANTITY_CORRECTION`, `BATCH_METADATA_CORRECTION`, `STOCK_TAKE`, `branch_transfer`, `branch_receipt`, `OPENING_BALANCE`.
- **reference_id:** UUID of the source document (invoice, GRN, transfer, receipt, stock take session, etc.). Null for some adjustments (MANUAL_ADJUSTMENT, BATCH_* have reference_id=None).

### 2.5 Batch tracking

- batch_number, expiry_date, unit_cost (and optionally batch_cost, remaining_quantity, is_batch_tracked, parent_batch_id, split_sequence) support batch-level tracking.
- FEFO uses (batch_number, expiry_date, unit_cost) and sum(quantity_delta) per batch to compute available and allocate.

### 2.6 Cost fields

- **unit_cost:** Always stored; cost per base unit for this row.
- **total_cost:** quantity_delta * unit_cost. Used for COGS (e.g. SALE rows sum to COGS). In BATCH_METADATA_CORRECTION the “out” row uses negative total_cost.

### 2.7 Support for required concepts

| Concept | Ledger support |
|---------|----------------|
| item_id | Yes, NOT NULL |
| batch_id | No separate FK. Batch identity is (batch_number, expiry_date) (and in practice unit_cost). Ledger row id can be used as “batch ledger id” where needed (e.g. sales_invoice_items.batch_id). |
| quantity_delta | Yes, NOT NULL, != 0 |
| cost_price | Yes as unit_cost (and total_cost) |
| reference_type | Yes |
| reference_id | Yes |
| document_number | No — resolved from document table via reference_id |
| branch_id | Yes, NOT NULL |

### 2.8 SALE_RETURN and PURCHASE_RETURN without structural change

- **Structure:** The ledger already supports arbitrary transaction_type strings, positive/negative quantity_delta, reference_type, reference_id, and cost. No new columns are required.
- **SALE_RETURN:** Could be added as a new transaction_type with **positive** quantity_delta, same batch/cost semantics as the original SALE, and `reference_type="credit_note"`, `reference_id=credit_note.id`. SnapshotService would add this delta and **increase** stock. No schema change.
- **PURCHASE_RETURN:** Today supplier returns use **PURCHASE** with **negative** delta and `reference_type="supplier_return"`. Alternatively, a dedicated **PURCHASE_RETURN** with **negative** quantity_delta would also work and would make reporting (e.g. “purchases vs returns”) clearer. Again no schema change.
- **Conclusion:** Both SALE_RETURN and PURCHASE_RETURN can be supported with **no structural change** to the ledger; only new transaction_type (and possibly reference_type) values and business logic.

---

## 3. ANALYZE BATCH INTEGRITY

### 3.1 One ledger entry per batch consumed (sales)

- **allocate_stock_fefo** returns a list of allocations. Each element is one (batch_number, expiry_date, unit_cost) with a quantity to take.
- In **batch_sales_invoice**, the code does:
  ```python
  for allocation in allocations:
      ledger_entry = InventoryLedger(..., quantity_delta=-qty, ...)
      ledger_entries.append(ledger_entry)
  ```
- So for each batch consumed there is **exactly one** SALE ledger row with negative quantity.
- **Example:** Panadol 3, Batch A 2 + Batch B 1 → two allocations → two ledger rows: SALE −2 (batch A), SALE −1 (batch B). Pattern matches the intended design.

### 3.2 How batch consumption is recorded

- By **batch**: (batch_number, expiry_date, unit_cost). Multiple ledger rows can share the same logical batch (e.g. two purchases of same batch → two PURCHASE rows; FEFO then returns two allocations that sum to the requested quantity).
- Sales (and branch transfer out) create one **negative** row per allocation, so one row per “batch slice” consumed. No single “batch consumption” table; the ledger itself is the record.

---

## 4. ANALYZE COST TRACKING

### 4.1 Cost at time of sale

- **Sales:** At batching, FEFO returns allocations with `unit_cost` from the ledger (purchase/adjustment that added that batch). This is written to:
  - **Ledger:** Each SALE row: `unit_cost`, `total_cost = unit_cost * qty`.
  - **Invoice line:** `invoice_item.unit_cost_used = batch_cost` (cost per base unit from first allocation); `invoice_item.batch_id = allocations[0]["ledger_entry_id"]`.
- So cost **is** captured at sale and stored both on the invoice item and on each SALE ledger row.

### 4.2 Invoice items and ledger

- **sales_invoice_items.unit_cost_used** — cost per base (retail) unit used for that line (from FEFO at batch time).
- **inventory_ledger** (SALE): `unit_cost`, `total_cost` per row. Sum of total_cost over SALE rows for an invoice = COGS for that invoice (modulo any multi-batch rounding).

### 4.3 Margins today

- **Per line:** Margin is derived from (unit_price_exclusive - cost_per_sale_unit) / unit_price_exclusive; cost_per_sale_unit comes from unit_cost_used and unit multiplier. Enrichment in `_get_sales_invoice_response` computes margin_percent from item’s unit_cost_used and unit_price_exclusive.
- **Gross profit report:** `get_branch_gross_profit` uses:
  - **Sales:** Sum of `SalesInvoice.total_exclusive` for BATCHED/PAID in date range.
  - **COGS:** From `_compute_cogs_from_invoice_lines` — either from ledger (sum of SALE total_cost for those invoices) or from invoice lines (quantity in retail units × unit_cost_used). Comment in code prefers invoice-line COGS for correct unit conversion.
- So margins and COGS are driven by **unit_cost_used** and ledger **total_cost**, both set at batching.

### 4.4 Reversing COGS for customer returns

- **Today:** No customer return (credit note) flow that creates ledger rows. So no reversal yet.
- **If we add SALE_RETURN:** Each return line could create ledger rows with `transaction_type="SALE_RETURN"`, **positive** quantity_delta, same unit_cost as the original sale (from invoice line or ledger). Then:
  - **Stock:** SnapshotService would add the delta → stock increases; correct.
  - **COGS:** Reports would need to treat SALE_RETURN total_cost as a **reduction** of COGS (e.g. COGS = sum(SALE total_cost) − sum(SALE_RETURN total_cost) for the period). Current gross profit logic does not do this; it would need to be extended.
- **Conclusion:** Cost is captured and stored correctly for sales. Reversing COGS for returns is **not** implemented but is **possible** once SALE_RETURN exists and reporting is updated to net SALE and SALE_RETURN.

---

## 5. ANALYZE DOCUMENT REFERENCES

### 5.1 What the ledger stores

- **reference_type** — string (e.g. `sales_invoice`, `grn`, `purchase_invoice`, `supplier_return`, `branch_transfer`, `branch_receipt`, `STOCK_TAKE`, `MANUAL_ADJUSTMENT`, `BATCH_QUANTITY_CORRECTION`, `BATCH_METADATA_CORRECTION`, `OPENING_BALANCE`).
- **reference_id** — UUID. Points to the document (e.g. sales_invoices.id, credit_notes.id, grn.id, branch_transfers.id). Null for some adjustments.
- **document_number** — **not** on the ledger. Document numbers (invoice_no, grn_no, credit_note_no, transfer_number, etc.) live on their respective tables.

### 5.2 How document numbers are resolved

- **Item movement report** (`item_movement_report_service.py`): `_resolve_references_batch()` loads documents by (reference_type, reference_id) and builds a map to document_type and reference string (e.g. invoice_no, grn_no). So for display, reference_id is enough; document_number is fetched from the document.
- **Known resolutions:** sales_invoice → Sale + invoice_no; grn → GRN + grn_no; purchase_invoice → Supplier Invoice + invoice_number; branch_transfer → Branch Transfer Out + transfer_number; branch_receipt → Branch Transfer In + receipt_number; STOCK_TAKE → Stock Take + session_code. MANUAL_ADJUSTMENT, OPENING_BALANCE, BATCH_QUANTITY_CORRECTION are handled inline (no reference_id). **supplier_return** is not yet in the resolver (would show as reference_type or blank reference).

### 5.3 Sufficiency for target document types

| Document | reference_type (current or proposed) | reference_id | document_number |
|----------|--------------------------------------|--------------|------------------|
| Sales invoice | sales_invoice | invoice id | On sales_invoices.invoice_no — resolved in report |
| Credit note (customer return) | credit_note (new) | credit_note id | On credit_notes.credit_note_no — add resolver |
| Purchase / GRN | grn | grn id | On grn.grn_no — resolved |
| Supplier invoice | purchase_invoice | invoice id | On supplier_invoices — resolved |
| Supplier return | supplier_return | return id | On supplier_returns — add resolver if needed |
| Adjustments | MANUAL_ADJUSTMENT, BATCH_*, STOCK_TAKE | session/id or null | N/A or from session/document |
| Transfer out/in | branch_transfer, branch_receipt | transfer/receipt id | Resolved |

So **reference_type + reference_id** is sufficient for all these; document_number is available from the referenced document. Adding credit_note (and optionally clarifying supplier_return) in the resolver is enough for a unified engine.

---

## 6. ANALYZE RETURN READINESS

### 6.1 Current support for returns

- **Supplier returns:** Implemented. On approve, ledger rows are created with `transaction_type="PURCHASE"`, `reference_type="supplier_return"`, `reference_id=ret.id`, **negative** quantity_delta. SnapshotService receives negative delta → stock decreases. No new movement type.
- **Customer returns:** CreditNote and CreditNoteItem models exist. **No** API that creates credit notes and ledger rows. No SALE_RETURN type. Returns UI is a placeholder (shows invoices).

### 6.2 Adding SALE_RETURN and PURCHASE_RETURN

- **Ledger:** No redesign. Add new transaction_type values and use existing columns.
- **SALE_RETURN:** Create rows with transaction_type=`"SALE_RETURN"`, **positive** quantity_delta, same item/batch/cost, reference_type=`"credit_note"`, reference_id=credit_note.id. SnapshotService already adds delta → stock increases. Reporting must subtract SALE_RETURN total_cost from COGS and credit note total from sales.
- **PURCHASE_RETURN:** Option A: keep current pattern (PURCHASE + negative qty + supplier_return). Option B: introduce transaction_type=`"PURCHASE_RETURN"` with negative quantity_delta for clearer reporting. Both work without schema change.

### 6.3 What already works

- Ledger supports any transaction_type and sign of quantity_delta.
- SnapshotService is sign-agnostic; returns (positive delta) would increase stock correctly.
- reference_type/reference_id can point to credit_note and supplier_return.
- Batch and cost fields exist; return rows can mirror original batch/cost.
- Credit note tables and numbering exist; only creation and ledger posting are missing.

### 6.4 What is missing

- **Customer returns:** Credit note creation API; creation of SALE_RETURN ledger rows; SnapshotService calls; gross profit / sales reporting that nets sales and credit notes and COGS vs SALE_RETURN.
- **Unified reporting:** Gross profit and COGS do not yet account for credit notes or SALE_RETURN.
- **Item movement report:** credit_note and optionally supplier_return in `_resolve_references_batch` for document_type and reference string.
- **Duplicate return prevention:** No explicit “returned quantity per invoice line” or idempotency; would need business rules (e.g. sum of return qty ≤ sold qty per line/invoice).

### 6.5 What needs modification

- **Sales / COGS reporting:** Include credit notes (net sales) and SALE_RETURN (net COGS) in date-range logic.
- **APIs:** Implement create credit note + ledger + snapshot in one transaction; optional list credit notes by branch/date.
- **Frontend:** Returns page and “create return from invoice” flow.
- **Validation:** Ensure return qty ≤ sold qty; optional idempotency or “already returned” checks.

---

## 7. ANALYZE SNAPSHOT SERVICE

### 7.1 How inventory balances are updated

- **Method:** `SnapshotService.upsert_inventory_balance(db, company_id, branch_id, item_id, quantity_delta)`.
- **SQL:**  
  `INSERT INTO inventory_balances (..., current_stock, ...) VALUES (..., :qty, ...) ON CONFLICT (item_id, branch_id) DO UPDATE SET current_stock = current_stock + EXCLUDED.current_stock`.
- So the **same** quantity_delta passed in (positive or negative) is **added** to current_stock. No logic based on transaction_type or sign.

### 7.2 Assumption on sales vs returns

- **Sales:** Callers pass **negative** quantity_delta (e.g. from SALE rows). Stock goes down. Snapshot does not “assume” negative; it just adds the value.
- **Returns:** If we pass **positive** quantity_delta (e.g. from SALE_RETURN rows), current_stock would **increase**. So the same API supports both without change.

### 7.3 Support for positive return movements

- Yes. Any positive delta increases current_stock. No change needed in SnapshotService for customer or supplier returns (supplier return already uses negative delta and is supported).

### 7.4 Would returns break snapshot logic?

- No. Returns would post **positive** deltas; snapshot would add them. No structural or sign assumption would be violated.

---

## 8. ANALYZE CONCURRENCY SAFETY

### 8.1 Database transactions

- **Sales batch:** Single transaction: load invoice with `with_for_update()`, create ledger rows, flush, run SnapshotService for each row, commit. On exception, rollback.
- **Supplier invoice batch:** Same pattern: invoice locked with `with_for_update()`, ledger + snapshot in same transaction, commit.
- **Supplier return approve:** Return record locked with `with_for_update()`, ledger + snapshot in same transaction, commit.
- **Branch transfer:** Transfer locked with `with_for_update()`, FEFO uses `allocate_stock_fefo_with_lock` (ledger rows for item/branch locked with `with_for_update()`), then ledger + snapshot, commit.
- **Branch receipt:** Receipt confirmed in a transaction; ledger + snapshot, commit.
- **Manual adjustment:** Ledger + snapshot in one transaction; duplicate check by time window (2 sec) + same user/quantity/reference_type.
- **Stock take complete:** Session locked with `with_for_update()`, multiple ADJUSTMENT rows + snapshot, single commit.

So **stock mutations run inside a single database transaction** with commit or rollback.

### 8.2 Preventing return_qty > sold_qty

- **Today:** No customer return flow, so no check.
- **If we add returns:** Not enforced by DB. Must be enforced in application logic when creating credit note lines (e.g. sum of quantity_returned per original_sale_item_id ≤ original line quantity). Optional: store “returned so far” on invoice line or in a summary table and validate against it.

### 8.3 Preventing duplicate returns

- **Today:** Supplier return is approved once; status moves to “credited”; approve is guarded by `with_for_update()` and status check. So duplicate approve is prevented.
- **Customer returns:** No idempotency yet. Options: idempotency key on create credit note, or “already returned” checks per invoice/line. Not present today.

### 8.4 Summary

- Concurrency: Key operations use row-level locks and single transactions; snapshot and ledger stay consistent.
- return_qty vs sold_qty and duplicate customer returns require **new** application-level validation and/or idempotency when implementing the return engine.

---

## 9. FINAL ARCHITECTURE ASSESSMENT

### PharmaSight Transaction Engine Readiness

| Area | Score (1–10) | Notes |
|------|--------------|--------|
| **Ledger structure** | 9 | Append-only; item, branch, batch, cost, reference_type, reference_id. No document_number on ledger (resolved from document). SALE_RETURN/PURCHASE_RETURN need no schema change. Minor: schema allows total_cost ge=0 but BATCH_METADATA_CORRECTION uses negative total_cost. |
| **Batch tracking** | 9 | One ledger row per batch consumed for sales; FEFO allocation; batch_number, expiry_date, unit_cost stored. batch_id as “first allocation” stored on invoice line. |
| **Cost tracking** | 9 | unit_cost/total_cost on ledger; unit_cost_used on invoice line at batch time. COGS and margins derived correctly. Return reversal of COGS not yet in reports. |
| **Document references** | 8 | reference_type + reference_id cover all doc types. document_number resolved in reports. credit_note (and optionally supplier_return) need to be added to resolver. |
| **Snapshot engine** | 9 | Sign-agnostic; add delta to current_stock. Supports positive (returns) and negative (sales) without change. |
| **Return support** | 5 | Supplier return implemented (PURCHASE negative). Customer return: models and numbering exist; no API, no SALE_RETURN, no report netting. Logic and reporting extensions needed. |

**Overall:** The ledger and snapshot design are **ready** for a unified transaction engine. The main gaps are **customer return** implementation (API + SALE_RETURN + reporting) and **validation/idempotency** for returns.

---

## 10. RECOMMENDED ARCHITECTURE

### 10.1 Movement types

Recommended set for the unified engine:

| Type | Meaning | quantity_delta | Stock effect | COGS / value |
|------|---------|----------------|--------------|--------------|
| **SALE** | Customer sale (invoice batch) | Negative | Decrease | Increase COGS (cost of sale) |
| **SALE_RETURN** | Customer return (credit note) | Positive | Increase | Decrease COGS (reversal) |
| **PURCHASE** | Goods receipt (GRN / supplier invoice) | Positive | Increase | N/A (purchase cost recorded) |
| **PURCHASE_RETURN** | Supplier return | Negative | Decrease | N/A (or reduce purchase cost in supplier ledger) |
| **ADJUSTMENT** | Manual, batch correction, stock take | + or − | Per delta | Only if used for cost/quantity correction |
| **TRANSFER_IN** | Branch receipt | Positive | Increase (receiving branch) | N/A |
| **TRANSFER_OUT** | Branch transfer send | Negative | Decrease (sending branch) | N/A |

**Note:** Current code uses **TRANSFER** for both in and out (direction from sign). Keeping TRANSFER with sign is fine; renaming to TRANSFER_IN/TRANSFER_OUT would be for clarity only.

### 10.2 Effect summary

- **quantity_delta:** Positive = stock in, negative = stock out. Snapshot: `current_stock += quantity_delta`.
- **Stock levels:** Sum of quantity_delta per (item_id, branch_id) = theoretical balance; snapshot table holds the same logically and is updated in the same transaction.
- **COGS:** For a period, COGS = sum(total_cost) where transaction_type = SALE and reference in period **minus** sum(total_cost) where transaction_type = SALE_RETURN and reference in period. Sales value = invoice totals **minus** credit note totals for the period.

### 10.3 reference_type alignment

- **SALE** → reference_type `sales_invoice`, reference_id = invoice id.
- **SALE_RETURN** → reference_type `credit_note`, reference_id = credit_note id.
- **PURCHASE** → reference_type `grn` or `purchase_invoice`, reference_id = document id.
- **PURCHASE_RETURN** → reference_type `supplier_return`, reference_id = supplier_return id (or introduce PURCHASE_RETURN and keep same reference).
- **ADJUSTMENT** → reference_type MANUAL_ADJUSTMENT, BATCH_QUANTITY_CORRECTION, BATCH_METADATA_CORRECTION, STOCK_TAKE as today; reference_id where applicable.
- **TRANSFER** → branch_transfer (out), branch_receipt (in); reference_id = transfer or receipt id.

This aligns with current usage and adds only the credit_note (and optional PURCHASE_RETURN) semantics needed for a unified transaction engine.

---

*End of audit. No code was modified; findings are from codebase inspection only.*
