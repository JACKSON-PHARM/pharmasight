# Supplier Management – Architecture Map (Phase 1 Audit)

## 1. Current Supplier Model

| Location | Details |
|----------|---------|
| **Table** | `suppliers` (migration 001) |
| **Model** | `app/models/supplier.py` – `Supplier` |
| **Columns** | id, company_id, name, pin, contact_person, phone, email, address, credit_terms (Integer), is_active, created_at, updated_at |
| **Relations** | Company (back_populates suppliers); referenced by GRN, SupplierInvoice, PurchaseOrder, Item.default_supplier_id, ItemBranchPurchaseSnapshot.last_supplier_id, OrderBook |
| **API** | `app/api/suppliers.py`: GET /search (q, company_id), GET /company/{company_id}, POST /, GET /{id}, PUT /{id}. **Note:** company_id is taken from path/query/body; new supplier management must resolve from session only. |

**Gaps for extension:** default_payment_terms_days, credit_limit, allow_over_credit, opening_balance (all to be added in Phase 2).

---

## 2. Purchase Logic (Existing)

| Component | Details |
|-----------|---------|
| **Supplier Invoice** | Table `purchase_invoices` (model `SupplierInvoice` in `app/models/purchase.py`). Columns: company_id, branch_id, supplier_id, invoice_number, pin_number, reference, invoice_date, linked_grn_id, total_exclusive, vat_rate, vat_amount, total_inclusive, status (DRAFT \| BATCHED), payment_status (UNPAID \| PARTIAL \| PAID), amount_paid, balance, created_by, created_at, updated_at. |
| **Lines** | `purchase_invoice_items` (SupplierInvoiceItem): purchase_invoice_id, item_id, unit_name, quantity, unit_cost_exclusive, vat_rate, vat_amount, line_total_exclusive, line_total_inclusive, batch_data (JSON). |
| **Flow** | Create invoice → DRAFT (no stock). Batch via `POST /invoice/{id}/batch` → status BATCHED: writes to inventory_ledger (PURCHASE, reference_type purchase_invoice), SnapshotService.upsert_inventory_balance, SnapshotService.upsert_purchase_snapshot, SnapshotRefreshService.schedule_snapshot_refresh. |
| **GRN** | Separate path: GRN + GRNItem → ledger (reference_type grn), same snapshot/refresh pattern. |

**No supplier ledger today.** Balances are on the invoice (amount_paid, balance). No single “supplier balance” or ledger entries for invoices/payments/returns.

---

## 3. Stock Movement Logic

| Component | Details |
|-----------|---------|
| **Source of truth** | `inventory_ledger` (append-only). transaction_type: PURCHASE, SALE, ADJUSTMENT, TRANSFER, OPENING_BALANCE. reference_type: grn, purchase_invoice, sales_invoice, adjustment, etc. |
| **Snapshot** | `inventory_balances` (item_id, branch_id, current_stock) updated in same transaction via `SnapshotService.upsert_inventory_balance(db, company_id, branch_id, item_id, quantity_delta)`. |
| **Write path (purchases)** | `app/api/purchases.py`: batch_supplier_invoice creates InventoryLedger rows (positive quantity_delta), then SnapshotService.upsert_inventory_balance, SnapshotService.upsert_purchase_snapshot, SnapshotRefreshService.schedule_snapshot_refresh. |
| **Item movement** | `item_movements` table: audit for cost/batch corrections only (COST_ADJUSTMENT, BATCH_QUANTITY_CORRECTION, BATCH_METADATA_CORRECTION). Not used for purchase/sale documents. |

**Rule:** All stock changes must go through InventoryLedger + SnapshotService; no direct stock manipulation. Supplier returns will add negative PURCHASE (or a dedicated REFUND/SUPPLIER_RETURN type) and same snapshot update.

---

## 4. Snapshot Refresh Service

| Component | Details |
|-----------|---------|
| **Entry point** | `SnapshotRefreshService.schedule_snapshot_refresh(db, company_id, branch_id, item_id=...)` in `app/services/snapshot_refresh_service.py`. |
| **Behaviour** | Single item → sync refresh in same transaction (`refresh_pos_snapshot_for_item`). Whole branch or many items → enqueue to `snapshot_refresh_queue`; background processor in `scripts/process_snapshot_refresh_queue.py`. |
| **POS snapshot** | `item_branch_snapshot` (ItemBranchSnapshot) populated by `pos_snapshot_service.refresh_pos_snapshot_for_item` (reads inventory_balances, ledger, item_branch_purchase_snapshot, pricing). |

**Rule:** Any write that affects stock or item-level data must call SnapshotRefreshService (or SnapshotService for balances/purchase snapshot); do not duplicate or bypass.

---

## 5. Transaction Patterns

| Pattern | Where | Notes |
|---------|--------|--------|
| **Sync in same transaction** | GRN create, batch_supplier_invoice, sales invoice post, cost/quantity adjustments | Ledger + inventory_balances + purchase_snapshot + SnapshotRefreshService.schedule_snapshot_refresh in one transaction. |
| **Async** | Bulk company/branch snapshot refresh | Via snapshot_refresh_queue and process_snapshot_refresh_queue. |
| **Identity** | get_current_user → request.state.effective_company_id (and branch from body/path where needed). | New supplier APIs must use session company_id only; never trust company_id from body for security. |

---

## 6. What Must Not Be Duplicated

- **Stock updates:** Only via InventoryLedger + SnapshotService.upsert_inventory_balance + SnapshotRefreshService.
- **Snapshot refresh:** Only via SnapshotRefreshService (sync or queue).
- **Ledger-style movements:** Today there is no supplier ledger; we add one (supplier_ledger_entries) as the single place for supplier-side debits/credits. Invoice/payment/return logic will write there only, not to a second “balance” store.

---

## 7. Internal Architecture Map (Pre-Implementation)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Multi-tenant: company_id from session (effective_company_id); branch_id    │
│ from path/body where relevant. Never accept company_id from request body.  │
└─────────────────────────────────────────────────────────────────────────────┘

  SUPPLIERS (existing)
       │
       ├── Supplier profile (extend: default_payment_terms_days, credit_limit,
       │   allow_over_credit, opening_balance)
       │
       ├── Supplier Invoices = purchase_invoices (existing)
       │   • Add: due_date, internal_reference
       │   • Status: DRAFT → BATCHED (post) → payment_status UNPAID/PARTIAL/PAID
       │   • On POST (batch): InventoryLedger (PURCHASE) + inventory_balances
       │     + purchase_snapshot + snapshot_refresh + supplier_ledger_entries (NEW)
       │
       ├── supplier_payments (NEW)
       │   • supplier_id, branch_id, payment_date, method, reference, amount, is_allocated
       │
       ├── supplier_payment_allocations (NEW)
       │   • supplier_payment_id, supplier_invoice_id (= purchase_invoice_id), allocated_amount
       │   • On create: reduce invoice balance, update invoice status, ledger credit
       │
       ├── supplier_returns (NEW)
       │   • supplier_id, linked_invoice_id, return_date, reason, total_value, status
       │   • On APPROVED: InventoryLedger (negative / SUPPLIER_RETURN), ledger credit
       │
       └── supplier_ledger_entries (NEW)
           • Single source of truth: supplier_id, branch_id, date, entry_type,
             reference_id, debit, credit (running_balance optional/computed)

  STOCK (unchanged)
       • inventory_ledger ← all movements (purchase, sale, adjustment, transfer, returns)
       • inventory_balances ← SnapshotService.upsert_inventory_balance
       • SnapshotRefreshService ← after any stock-affecting write
```

---

## 8. Safety and Security Checklist

- **company_id:** Resolved from session (get_current_user → effective_company_id); never from request body for new endpoints.
- **branch_id:** Required where the operation is branch-scoped (e.g. payment, ledger).
- **Posting invoice:** Must have at least one line; must run in one DB transaction with ledger + snapshot.
- **Payments:** Prevent over-allocation (sum of allocations ≤ invoice balance and ≤ payment amount).
- **Returns:** Prevent negative stock (validate before creating negative ledger entries).
- **No deletion of posted financial records:** Soft delete only (e.g. is_void or status CANCELLED).

This document is the basis for Phase 2 (data model) and Phase 3 (business logic) without duplicating stock or snapshot logic.
