# Supplier Management – Implementation Summary

## Schema Migration Summary (052_supplier_management.sql)

| Change | Description |
|--------|-------------|
| **suppliers** | Added: `default_payment_terms_days` (INTEGER), `credit_limit` (NUMERIC), `allow_over_credit` (BOOLEAN, default FALSE), `opening_balance` (NUMERIC, default 0). Existing rows unaffected (nullable/defaults). |
| **purchase_invoices** | Added: `due_date` (DATE), `internal_reference` (VARCHAR(255)). |
| **supplier_payments** | New table: id, company_id, branch_id, supplier_id, payment_date, method, reference, amount, is_allocated, created_by, created_at, updated_at. Indexes: company_id, branch_id, supplier_id, payment_date. |
| **supplier_payment_allocations** | New table: id, supplier_payment_id, supplier_invoice_id, allocated_amount. Indexes: supplier_payment_id, supplier_invoice_id. |
| **supplier_returns** | New table: id, company_id, branch_id, supplier_id, linked_invoice_id, return_date, reason, total_value, status, created_by, created_at, updated_at. status IN ('pending','approved','rejected','credited'). Indexes: company_id, branch_id, supplier_id, return_date. |
| **supplier_return_lines** | New table: id, supplier_return_id, item_id, batch_number, expiry_date, quantity, unit_cost, line_total. Indexes: supplier_return_id, item_id. |
| **supplier_ledger_entries** | New table: id, company_id, branch_id, supplier_id, date, entry_type, reference_id, debit, credit, running_balance, created_at. entry_type IN ('invoice','payment','return','adjustment','opening_balance'). Indexes: company_id, branch_id, supplier_id, date, (entry_type, reference_id). |

---

## Service-Layer Summary

| Service | Location | Responsibility |
|---------|----------|----------------|
| **SupplierLedgerService** | `app/services/supplier_ledger_service.py` | `create_entry(...)` appends debit/credit rows; `get_outstanding_balance(supplier_id, company_id, branch_id?, as_of_date?)` returns sum(debit)-sum(credit). All within caller’s transaction. |
| **SnapshotRefreshService** | Existing | Used after stock changes (e.g. return approval). No duplication. |
| **SnapshotService** | Existing | `upsert_inventory_balance` used when reducing stock on return. No duplication. |
| **InventoryService** | Existing | `get_current_stock` used to validate stock before approving returns. |

---

## API Endpoints List

### Existing (unchanged)

- `GET /api/suppliers/search?q=&company_id=&limit=`
- `GET /api/suppliers/company/{company_id}`
- `POST /api/suppliers/`
- `GET /api/suppliers/{supplier_id}`
- `PUT /api/suppliers/{supplier_id}`
- `GET /api/purchases/invoice?company_id=&branch_id=&supplier_id=&date_from=&date_to=`
- `POST /api/purchases/invoice` (create draft)
- `GET /api/purchases/invoice/{id}`, `PUT`, `PATCH` items, `POST /api/purchases/invoice/{id}/batch` (post = add stock + ledger debit)

### New – Supplier Management (company_id from session only)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/suppliers/payments` | Create payment; optional allocations; ledger credit = payment amount; invoice balances updated. |
| GET | `/api/suppliers/payments?supplier_id=&branch_id=&date_from=&date_to=` | List payments (session company). |
| POST | `/api/suppliers/returns` | Create return (pending). |
| PATCH | `/api/suppliers/returns/{return_id}/approve` | Approve return: reduce stock (ledger + snapshot), ledger credit, status → credited. |
| GET | `/api/suppliers/returns?supplier_id=&branch_id=&status=` | List returns. |
| GET | `/api/suppliers/ledger?supplier_id=&branch_id=&date_from=&date_to=` | List ledger entries for supplier. |
| GET | `/api/suppliers/reports/aging?branch_id=&as_of_date=` | Aging buckets (0–30, 31–60, 61–90, 90+) by due_date and balance. |
| GET | `/api/suppliers/reports/metrics?month=YYYY-MM&branch_id=` | Monthly: total purchases, payments, returns, net outstanding, overdue, top suppliers, avg payment days. |
| GET | `/api/suppliers/statement?supplier_id=&branch_id=&from_date=&to_date=` | Statement lines with running balance (printable). |

---

## Logic Flow Diagrams (Text)

### Invoice posting (existing batch flow, extended)

```
POST /api/purchases/invoice/{id}/batch
  → Lock invoice (DRAFT only)
  → Validate lines and batch data
  → For each line: create InventoryLedger (PURCHASE, +qty), reference_type=purchase_invoice
  → SnapshotService.upsert_inventory_balance (per entry)
  → SnapshotService.upsert_purchase_snapshot (per item)
  → SnapshotRefreshService.schedule_snapshot_refresh (per item)
  → SupplierLedgerService.create_entry(entry_type=invoice, debit=total_inclusive, reference_id=invoice.id)
  → invoice.status = BATCHED
  → commit
```

### Payment with allocations

```
POST /api/suppliers/payments (body: branch_id, supplier_id, payment_date, method, reference, amount, allocations[])
  → company_id = request.state.effective_company_id
  → Validate supplier, branch
  → For each allocation: validate invoice (BATCHED, same supplier), balance >= allocated_amount; sum per invoice
  → total_allocated <= amount
  → INSERT supplier_payments
  → For each (invoice, total_alloc): INSERT supplier_payment_allocations; update invoice amount_paid, balance, payment_status
  → SupplierLedgerService.create_entry(entry_type=payment, credit=amount, reference_id=payment.id)
  → commit
```

### Return approval

```
PATCH /api/suppliers/returns/{id}/approve
  → company_id = request.state.effective_company_id
  → Load return (pending only)
  → For each line: InventoryService.get_current_stock >= line.quantity (prevent negative stock)
  → For each line: INSERT InventoryLedger (PURCHASE reversal: quantity_delta=-qty, reference_type=supplier_return)
  → SnapshotService.upsert_inventory_balance (negative delta)
  → SnapshotRefreshService.schedule_snapshot_refresh (per item)
  → SupplierLedgerService.create_entry(entry_type=return, credit=total_value, reference_id=return.id)
  → return.status = credited
  → commit
```

---

## Performance Risks

| Risk | Mitigation |
|------|------------|
| Aging report aggregates over all BATCHED invoices with balance | Filter by branch_id when possible; index (company_id, branch_id, status, due_date, balance). |
| Monthly metrics: multiple SUMs over invoices/payments/returns | Indexes on (company_id, branch_id, date columns); consider caching for dashboard if needed. |
| Statement: ledger scan + opening balance subquery | Index (company_id, supplier_id, branch_id?, date). |
| List payments/returns without limit | Add optional limit/offset for large tenants. |

---

## Indexing Strategy

- **supplier_payments**: (company_id), (branch_id), (supplier_id), (payment_date) — already in migration.
- **supplier_payment_allocations**: (supplier_payment_id), (supplier_invoice_id) — already in migration.
- **supplier_returns**: (company_id), (branch_id), (supplier_id), (return_date) — already in migration.
- **supplier_return_lines**: (supplier_return_id), (item_id) — already in migration.
- **supplier_ledger_entries**: (company_id), (branch_id), (supplier_id), (date), (entry_type, reference_id) — already in migration.
- **purchase_invoices**: Add composite for aging/metrics: `CREATE INDEX IF NOT EXISTS idx_purchase_invoices_aging ON purchase_invoices(company_id, branch_id, status) WHERE status = 'BATCHED';` and ensure (due_date) is used in aging (index on due_date optional if filtered by company_id first).

---

## Safety Checks Implemented

- **Negative stock on return**: Check `InventoryService.get_current_stock` before creating negative ledger entries; reject with 400 if insufficient.
- **Payment over-allocation**: Sum allocations per invoice and validate sum ≤ invoice balance; total allocations ≤ payment amount.
- **Posting invoice without lines**: Existing check in batch: `if not invoice.items` → 400.
- **Posted financial records**: No hard delete of supplier_payments, allocations, or ledger; returns use status (pending → credited). Soft delete can be added later if needed.
- **company_id**: All new endpoints use `_effective_company_id(request)` from session; never from body.

---

## UI Structure (Reference)

Under **Suppliers** tab:

- **All Suppliers** – existing list (company from session/path).
- **Supplier detail** – Profile (existing GET/PUT), Invoices (existing purchases list filtered by supplier_id), Payments (new list), Returns (new list), Ledger (new), Statement (new, printable), Aging Report (new), Supplier Metrics (new).
- Reuse existing item/inventory components; do not duplicate item movement UI.

---

## Files Touched / Added

| File | Change |
|------|--------|
| `docs/SUPPLIER_MANAGEMENT_ARCHITECTURE.md` | New – Phase 1 audit and architecture map. |
| `docs/SUPPLIER_MANAGEMENT_IMPLEMENTATION_SUMMARY.md` | New – this summary. |
| `database/migrations/052_supplier_management.sql` | New – supplier + invoice columns, new tables. |
| `app/models/supplier.py` | Extended: default_payment_terms_days, credit_limit, allow_over_credit, opening_balance. |
| `app/models/purchase.py` | Extended: due_date, internal_reference on SupplierInvoice. |
| `app/models/supplier_financial.py` | New – SupplierPayment, SupplierPaymentAllocation, SupplierReturn, SupplierReturnLine, SupplierLedgerEntry. |
| `app/models/__init__.py` | Export new models. |
| `app/services/supplier_ledger_service.py` | New – create_entry, get_outstanding_balance. |
| `app/schemas/supplier_management.py` | New – payment, return, ledger, aging, metrics, statement schemas. |
| `app/schemas/purchase.py` | Added due_date, internal_reference to SupplierInvoiceBase. |
| `app/api/supplier_management.py` | New – payments, returns, ledger, aging, metrics, statement. |
| `app/api/purchases.py` | Ledger debit on batch; due_date/internal_reference on create/update. |
| `app/main.py` | Include supplier_management_router under /api/suppliers. |
