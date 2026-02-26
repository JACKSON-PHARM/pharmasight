# Branch-Scoped Item Movement Report — Planning Document

**Status:** PLANNING ONLY — No implementation yet. Await approval before coding.

---

## 1. Current Database Structure Analysis

### 1.1 Tables Involved

| Domain | Table(s) | Purpose |
|--------|----------|---------|
| **Sales** | `sales_invoices`, `sales_invoice_items` | Invoices: `invoice_no`, `invoice_date`, `customer_name`, `payment_mode`, `payment_status`, `branch_id` |
| **Sale items** | `sales_invoice_items` | Line items; link to `inventory_ledger` via `batch_id` (optional) |
| **Purchases / GRN** | `grns`, `grn_items` | GRN: `grn_no`, `date_received`, `branch_id` |
| **Supplier invoices** | `purchase_invoices` (SupplierInvoice), `purchase_invoice_items` | `invoice_number`, `invoice_date`, `branch_id`; ledger uses `reference_type="grn"` or `"purchase_invoice"` |
| **Stock adjustments** | No dedicated table | Adjustments exist only as **inventory_ledger** rows: `transaction_type='ADJUSTMENT'`, `reference_type='MANUAL_ADJUSTMENT'` or `'STOCK_TAKE'`, `reference_id` = session id or NULL |
| **Branch transfers** | `branch_orders`, `branch_order_lines`, `branch_transfers`, `branch_transfer_lines`, `branch_receipts`, `branch_receipt_lines` | Out: ledger `reference_type='branch_transfer'`, `reference_id=transfer.id`. In: `reference_type='branch_receipt'`, `reference_id=receipt.id`. Transfer has `transfer_number`; receipt has `receipt_number`. |
| **Inventory ledger** | `inventory_ledger` | **Single source of truth** for all stock movements. Append-only. |
| **Items** | `items` | `name`, `sku`, `base_unit`, `company_id` |
| **Branches** | `branches` | `name`, `code`, `company_id` |
| **Company** | `companies` | `name` (for report header) |

### 1.2 Inventory Ledger Schema (Relevant Columns)

- `id`, `company_id`, `branch_id`, `item_id`
- `batch_number`, `expiry_date`
- **`transaction_type`**: `PURCHASE` | `SALE` | `ADJUSTMENT` | `TRANSFER` | `OPENING_BALANCE`
- **`reference_type`**: `grn` | `purchase_invoice` | `sales_invoice` | `MANUAL_ADJUSTMENT` | `STOCK_TAKE` | `branch_transfer` | `branch_receipt` (and `OPENING_BALANCE` for opening balance entries)
- **`reference_id`**: UUID of source document (invoice, grn, transfer, receipt, stock take session) or NULL for manual adjustment
- `quantity_delta` (Numeric: + in, − out), `unit_cost`, `total_cost`
- `created_at` (timestamptz), `created_by`, `notes`

### 1.3 Mapping: Ledger → Document Type & Reference Number

| transaction_type | reference_type | reference_id → | Document type (display) | Reference number source |
|------------------|----------------|-----------------|--------------------------|--------------------------|
| PURCHASE | grn | grns.id | GRN | grns.grn_no |
| PURCHASE | purchase_invoice | purchase_invoices.id | Supplier Invoice | purchase_invoices.invoice_number |
| SALE | sales_invoice | sales_invoices.id | Sale | sales_invoices.invoice_no; + payment_mode, customer_name |
| ADJUSTMENT | MANUAL_ADJUSTMENT | NULL | Adjustment | e.g. "Adjustment" + notes/date |
| ADJUSTMENT | STOCK_TAKE | stock_take_sessions.id | Stock Take | Session code or id for reference |
| TRANSFER | branch_transfer | branch_transfers.id | Branch Transfer Out | branch_transfers.transfer_number |
| TRANSFER | branch_receipt | branch_receipts.id | Branch Transfer In | branch_receipts.receipt_number |
| OPENING_BALANCE | (any) | — | Opening Balance | — |

---

## 2. Stock Ledger: Existing vs Compute

### 2.1 Do We Have a Stock Ledger?

**Yes.** The **`inventory_ledger`** table is the stock ledger. It is append-only and already records every movement with `transaction_type`, `reference_type`, `reference_id`, `quantity_delta`, `created_at`, and branch/item.

### 2.2 Do We Need a New Table?

**No.** All movement data for the report can be derived from:

1. **`inventory_ledger`** — filter by `company_id`, `branch_id` (from session), `item_id` (selected item), and `created_at` in date range (and before range for opening balance).
2. **Joins** to resolve document type and reference numbers: `sales_invoices`, `grns`, `purchase_invoices` (SupplierInvoice), `branch_transfers`, `branch_receipts`, `stock_take_sessions` (if we show stock take ref), and `items`/`branches`/`companies` for headers.

No separate `stock_ledger` or materialized view is required for this feature.

---

## 3. Architecture Options

### OPTION A: Build Movement from Raw Transactions (Recommended)

- **Approach:** Single (or minimal) query on `inventory_ledger` for the branch + item + date range; then resolve reference details via joins or follow-up lookups by `reference_type` + `reference_id`.
- **Pros:**
  - No schema change; no new tables or ETL.
  - Uses existing single source of truth; no risk of ledger vs report divergence.
  - Simple to reason about and maintain.
  - Aligns with current system (stock is always SUM(quantity_delta) on ledger).
- **Cons:**
  - Report query may need several joins or batched lookups for reference numbers (sales invoice no, GRN no, etc.); can be optimized with one query + conditional joins or a small service layer that maps ref_type/ref_id → display strings.

### OPTION B: Introduce a Unified stock_ledger Table

- **Approach:** New table (e.g. `stock_ledger` or `item_movement_ledger`) that either duplicates ledger rows with denormalized document_type and reference_number, or is a view/materialized view on top of `inventory_ledger` + joins.
- **Pros:**
  - Report could read one flat table with no runtime joins.
- **Cons:**
  - Duplication or extra ETL: every write path (sales, purchases, adjustments, transfers) would need to maintain this table, or we maintain a view/materialized view and refresh strategy.
  - Risk of drift from `inventory_ledger`; more code and migration surface.
  - Overkill for one report when Option A is straightforward.

### Recommendation

**Choose OPTION A:** Build the Item Movement Report from **`inventory_ledger`** plus resolution of `reference_type`/`reference_id` to document type and reference number. No new tables. Optional: add a composite index on `inventory_ledger (branch_id, item_id, created_at)` (and possibly `company_id`) to speed up the report query.

---

## 4. Backend Endpoint and Query Design

### 4.1 Endpoint (To Be Implemented)

- **Method/Path:** `GET /api/reports/item-movement` (or `POST` if preferred for body-based params).
- **Auth:** Same as rest of app (session/JWT); branch scoped via current user context.
- **Query/body parameters:**
  - `item_id` (required): UUID of the item.
  - `start_date` (required): Start of range (date, inclusive).
  - `end_date` (required): End of range (date, inclusive).
  - Branch: **not** passed in request; taken from **session/context** (current user’s branch or selected branch in CONFIG.BRANCH_ID equivalent). Enforced server-side.
- **Response:** JSON suitable for rendering the report (and later for PDF):
  - Company name, branch name.
  - Report title: "ITEM MOVEMENT REPORT".
  - Date range.
  - Item name + SKU.
  - Opening balance (as of start of day of `start_date`, or as of `created_at < start_date`).
  - List of movements in chronological order, each with:
    - Date/time (from `created_at`),
    - Document type (GRN, Supplier Invoice, Sale, Branch Transfer In/Out, Adjustment, Stock Take, Opening Balance),
    - Reference number (invoice no, GRN no, transfer/receipt number, or label for adjustment),
    - For **Sale**: payment mode and/or customer name (from `sales_invoices`),
    - Quantity delta (signed),
    - Running balance after the line,
    - Optional: batch_number, expiry_date, unit_cost, total_cost.
  - Closing balance = running balance after last movement in range.

### 4.2 Query Structure (Conceptual)

1. **Opening balance**  
   `SUM(quantity_delta)` from `inventory_ledger`  
   WHERE `company_id`, `branch_id`, `item_id` AND `created_at < range_start` (range_start = start_date 00:00:00 in branch TZ or UTC as stored).

2. **Movement rows**  
   SELECT from `inventory_ledger`  
   WHERE `company_id`, `branch_id`, `item_id` AND `created_at >= range_start` AND `created_at <= range_end`  
   ORDER BY `created_at` ASC.

3. **Resolve document type and reference number** (per row or batched):
   - If `reference_type = 'sales_invoice'` and `reference_id` → join or lookup `sales_invoices` → `invoice_no`, `payment_mode`, `customer_name`.
   - If `reference_type = 'grn'` and `reference_id` → `grns.grn_no`.
   - If `reference_type = 'purchase_invoice'` and `reference_id` → `purchase_invoices.invoice_number`.
   - If `reference_type = 'branch_transfer'` and `reference_id` → `branch_transfers.transfer_number`.
   - If `reference_type = 'branch_receipt'` and `reference_id` → `branch_receipts.receipt_number`.
   - If `reference_type = 'MANUAL_ADJUSTMENT'` → "Adjustment" (and optionally `notes`).
   - If `reference_type = 'STOCK_TAKE'` and `reference_id` → e.g. "Stock Take" + session identifier.
   - If `transaction_type = 'OPENING_BALANCE'` → "Opening Balance".

4. **Running balance**  
   Compute in application layer: start with opening balance, then for each row add `quantity_delta` to get running balance after that row.

### 4.3 Performance Considerations

- **Index:** Add composite index on `inventory_ledger (company_id, branch_id, item_id, created_at)` (or at least `(branch_id, item_id, created_at)`) to support the report filter and sort. Current indexes are per-column (item, branch, company, reference, batch); the report query is branch+item+time-range.
- **Volume:** One item, one branch, date-bounded — expected row count is small. No pagination needed for typical ranges; if needed later, support limit/offset or page size.
- **Joins:** Prefer one or two queries (ledger rows + bulk resolve of reference_ids by type) to avoid N+1. E.g. collect distinct (reference_type, reference_id) from the result set, then batch-fetch sales_invoices, grns, purchase_invoices, branch_transfers, branch_receipts and map in code.

---

## 5. Parts of the App Affected

- **New:** Report API module (e.g. `app/api/reports.py` or `app/api/item_movement_report.py`) and registration in `app/main.py`.
- **New:** Optional report service (e.g. in `app/services/`) that builds opening balance, movement list, and reference resolution; keeps API thin.
- **Frontend:** Reports section — new sub-page or section "Item Movement" with filters (date range preset: Today / This Month / Custom; item selector), "Apply" button, and area to render report HTML (PDF-like layout) with Print and Download PDF.
- **PDF:** New path in `document_pdf_generator` (or dedicated report PDF builder) to generate PDF from the same payload the frontend uses for the on-screen report.
- **Config/nav:** Reports sub-navigation may list "Financial", "Item Movement", etc.
- **No changes** to: sales flow, purchase flow, branch transfer/receipt flow, adjustment flow, or existing stock computation (all remain based on `inventory_ledger` only).

---

## 6. Confirmation: No Breaking Changes

The following will **not** be modified for this feature:

- **Sales flow** — No change to how sales create ledger entries (`SALE`, `sales_invoice`, `reference_id`).
- **Purchase flow** — No change to GRN or supplier invoice batching or ledger writes (`PURCHASE`, `grn` / `purchase_invoice`).
- **Branch transfers** — No change to transfer complete (ledger out) or receipt confirm (ledger in).
- **Adjustments** — No change to manual adjustment or stock take ledger entries.
- **Current stock computation** — All existing logic that uses `SUM(quantity_delta)` from `inventory_ledger` (by branch/item or branch/item/batch) remains unchanged.

The report is **read-only** and only adds a new API and UI that query existing data.

---

## 7. Implementation Plan (Step-by-Step)

### Phase 1: Backend

1. **Index (optional but recommended)**  
   Add migration: composite index on `inventory_ledger (company_id, branch_id, item_id, created_at)` (or `(branch_id, item_id, created_at)` if company is always implied).

2. **Schema/response**  
   Define Pydantic schemas for the report response (company name, branch name, item name, SKU, date range, opening balance, list of movement lines with document type, reference number, quantity delta, running balance, etc.).

3. **Service layer**  
   Implement a function that: given `company_id`, `branch_id`, `item_id`, `start_date`, `end_date`:  
   - Computes opening balance (ledger sum before start_date).  
   - Fetches ledger rows in range ordered by `created_at`.  
   - Resolves document type and reference number for each row (batch lookups by reference_type/reference_id).  
   - Computes running balance per line.  
   - Returns structured report data.

4. **API endpoint**  
   Implement `GET /api/reports/item-movement?item_id=...&start_date=...&end_date=...` (or POST with body).  
   - Resolve branch from current user/context; enforce branch scope.  
   - Call service; return JSON.

5. **Permissions**  
   Reuse existing reports or inventory read permission; no new permission required unless product explicitly requires "Item Movement Report" permission.

### Phase 2: Report Rendering (Frontend)

1. **Reports sub-navigation**  
   Add "Item Movement" (or "Inventory" → "Item Movement") so users can open the report screen.

2. **Report screen UI**  
   - Date range: preset (Today, This Month, Custom) + start/end date inputs.  
   - Item: single-item selector (search/autocomplete from company items).  
   - "Apply" button: call backend with branch from session, item_id, start_date, end_date.

3. **Report HTML (PDF-like)**  
   - Render response in a dedicated div with print-friendly CSS (e.g. A4-like width, clear typography, table for movement lines).  
   - Include: Company name, Branch name, "ITEM MOVEMENT REPORT", date range, item name + SKU, opening balance, table of movements (date, document type, reference, quantity, running balance), closing balance.  
   - For Sales rows, show payment mode and/or customer name as specified.

### Phase 3: PDF Generation

1. **Backend PDF endpoint**  
   e.g. `GET /api/reports/item-movement/pdf?item_id=...&start_date=...&end_date=...`  
   - Same auth and branch scoping.  
   - Reuse same report data (service layer).  
   - Generate PDF (e.g. ReportLab) with same layout as the on-screen report.

2. **Frontend "Download PDF"**  
   - Call PDF endpoint (or same endpoint with `Accept: application/pdf` or `?format=pdf`).  
   - Trigger download (blob + filename).

3. **Print**  
   - "Print" button: `window.print()` on the report container (or open report in new window and print).  
   - Use same CSS so print output matches the PDF-like view.

### Phase 4: Testing

1. **Unit tests**  
   - Service: opening balance and running balance correctness for a small fixture of ledger rows; reference resolution for each reference_type.

2. **API tests**  
   - Endpoint returns 403/400 when branch not in context or item not in company; 200 with correct structure when valid.

3. **Integration / manual**  
   - Create movements (purchase, sale, transfer in/out, adjustment) for one item in one branch; run report for that item and date range; confirm all document types and reference numbers appear and running balance matches expectation.

4. **Regression**  
   - Ensure existing flows (sales, purchases, transfers, adjustments) and existing stock displays still work.

---

## 8. Summary

- **Data source:** `inventory_ledger` only; no new ledger table.
- **Architecture:** Option A — build movement from ledger + resolve references.
- **Endpoint:** `GET /api/reports/item-movement` (branch from session; item_id, start_date, end_date in query or body).
- **Impact:** New report API, optional index, new report UI and PDF; no changes to sales, purchases, transfers, adjustments, or stock logic.
- **Implementation order:** Backend (index + service + endpoint) → Frontend (filters + Apply + report HTML + Print) → PDF (backend PDF + Download PDF button) → Testing.

**STOP — Awaiting approval before any implementation.**
