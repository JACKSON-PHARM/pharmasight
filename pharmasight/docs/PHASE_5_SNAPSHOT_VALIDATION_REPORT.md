# Phase 5 — Snapshot Service Validation Report

**Unified Transaction Engine — Snapshot layer verification and hardening**

---

## 1. SnapshotService audited

- **`SnapshotService.upsert_inventory_balance`**  
  - Accepts `quantity_delta` and applies it only.  
  - No use of `transaction_type`; stock math is `current_stock + quantity_delta`.  
  - All movement types (SALE, SALE_RETURN, PURCHASE, PURCHASE_RETURN, TRANSFER_IN, TRANSFER_OUT, ADJUSTMENT, OPENING_BALANCE) are supported by sign of `quantity_delta` only.

- **Atomic update**  
  - Uses the caller’s `db` session only; no `db.commit()` inside the service.  
  - Snapshot updates always run in the same transaction as the ledger insert.

- **Snapshot row locking**  
  - When reading `current_stock` for the negative-stock check, the query uses **`SELECT ... FOR UPDATE`** so the snapshot row (if it exists) is locked for the duration of the transaction.  
  - This prevents a race where two transactions read the same balance, both pass the `new_stock >= 0` check, and then both apply their deltas, which could result in negative stock.  
  - If no row exists yet, the SELECT returns nothing (no row to lock); the subsequent `INSERT ... ON CONFLICT DO UPDATE` then creates or updates the row.

- **Batch integrity**  
  - Snapshot key is `(item_id, branch_id)` only.  
  - No batch-level balances in the snapshot table; batch detail stays in the ledger.

- **Module docstring**  
  - Clarifies that stock math is delta-only and movement type is not used.

---

## 2. Negative stock protection implemented

- Before applying the delta, the service:
  1. Reads `current_stock` for `(item_id, branch_id)` in the same transaction.
  2. Computes `new_balance = current_stock + quantity_delta`.
  3. If `new_balance < 0`, raises:
     - `ValueError("Insufficient stock for movement: item_id=... branch_id=... current_stock=... quantity_delta=... would give new_stock=...")`.

- **`upsert_inventory_balance_bulk`**  
  - Unchanged. Used only for opening balance import (positive deltas). Docstring states it does not perform per-row negative-stock check.

---

## 3. Movement types verified

| Movement type     | quantity_delta | Stock effect   | Snapshot logic      |
|-------------------|----------------|----------------|---------------------|
| SALE              | negative       | reduce         | `current + delta`   |
| SALE_RETURN       | positive       | increase       | same                |
| PURCHASE          | positive       | increase       | same                |
| PURCHASE_RETURN   | negative       | reduce         | same                |
| TRANSFER_OUT      | negative       | reduce         | same                |
| TRANSFER_IN       | positive       | increase       | same                |
| ADJUSTMENT        | ±              | adjust         | same                |
| OPENING_BALANCE   | positive       | initial stock  | same                |

No movement-type branching in snapshot logic; only `quantity_delta` is used.

---

## 4. All ledger insert points call SnapshotService

Verified that every path that inserts into `inventory_ledger` calls `SnapshotService.upsert_inventory_balance` (or `upsert_inventory_balance_delta` / `upsert_inventory_balance_bulk` where applicable) in the same transaction:

| Module                  | Flow                         | Snapshot call                                      |
|-------------------------|-----------------------------|----------------------------------------------------|
| **sales.py**            | Credit note create          | `upsert_inventory_balance` per entry (doc_number) |
| **sales.py**            | Invoice batch               | `upsert_inventory_balance` per entry (doc_number) |
| **quotations.py**       | Quotation → invoice         | `upsert_inventory_balance` per entry (invoice_no) |
| **purchases.py**        | GRN create                  | `upsert_inventory_balance` per entry (grn_no)     |
| **purchases.py**        | Supplier invoice batch      | `upsert_inventory_balance` per entry (invoice_number) |
| **supplier_management.py** | Supplier return approve  | `upsert_inventory_balance` per line (doc_num)     |
| **branch_inventory.py** | Transfer complete           | `upsert_inventory_balance` per entry (transfer_number) |
| **branch_inventory.py** | Receipt confirm             | `upsert_inventory_balance` per entry (receipt_number) |
| **items.py**            | Manual adjustment           | `upsert_inventory_balance` (document_number="ADJ") |
| **items.py**            | Batch quantity correction   | `upsert_inventory_balance` (document_number="ADJ") |
| **items.py**            | Batch metadata correction   | `upsert_inventory_balance` (document_number="ADJ", delta=0) |
| **stock_take.py**       | Count adjustment + zero-out | `upsert_inventory_balance` (session.session_code) |
| **excel_import_service.py** | Opening balance (new)    | `upsert_inventory_balance` (document_number="OPENING") |
| **excel_import_service.py** | Opening balance (update) | `upsert_inventory_balance_delta` → `upsert_inventory_balance` ("OPENING") |
| **excel_import_service.py** | Bulk opening balance     | `upsert_inventory_balance_bulk` (same transaction) |

No stock movement path bypasses the snapshot layer.

---

## 5. No snapshot updates outside transactions

- `SnapshotService` never calls `db.commit()` or `db.rollback()`.
- All callers run snapshot updates after ledger insert and before their own `commit()`.
- If a transaction fails and rolls back, both ledger rows and snapshot changes are rolled back.

---

## Additional changes (Phase 5)

- **Document number requirement**  
  `upsert_inventory_balance` now requires a non-empty `document_number` so every movement is traceable. All single-row call sites pass a document number (invoice_no, credit_note_no, grn_no, "ADJ", session_code, "OPENING", etc.).

- **Debug logging**  
  On each snapshot update, debug log:
  - `item_id`, `branch_id`, `delta`, `new_balance`, `document_number`.

- **`upsert_inventory_balance_delta`**  
  Accepts optional `document_number` (default `"OPENING"`) and forwards it to `upsert_inventory_balance`.

---

## Architecture (unchanged)

```
Document (invoice, GRN, credit note, etc.)
    ↓
Ledger (immutable history; document_number on each row)
    ↓
Snapshot (current_stock per item_id, branch_id only)
```

Phase 5 keeps this flow, adds negative-stock checks and document-number enforcement on the single-row path, and confirms all movement types and call sites are correct. Safe to deploy independently.
