# Branch Inventory Module — Structural Audit Report

**Date:** Post-implementation validation and hardening  
**Scope:** Branch inventory only. Purchase, sales, and costing systems were **not** modified.

---

## PART 1 — Architecture Validation

### 1️⃣ Ledger-Centric Batch Tracking — CONFIRMED

| Check | Status | File / Evidence |
|-------|--------|------------------|
| No `inventory_batches` table created | ✅ | No such table in codebase; grep returns no matches. |
| Batch data from `inventory_ledger` only | ✅ | `app/models/inventory.py`: batch_number, expiry_date, unit_cost on `InventoryLedger`. Branch transfer reads/writes only ledger. |
| FEFO reads from ledger | ✅ | `app/services/inventory_service.py`: `allocate_stock_fefo_with_lock()` queries `InventoryLedger` only. |
| Ledger remains append-only | ✅ | `app/models/inventory.py`: comment "Never update or delete. Always append." Branch module only INSERTs. |
| No parallel stock tables | ✅ | Only `inventory_ledger` and snapshot table `inventory_balances` (updated in same transaction). |

**How available stock per batch is derived**

- Available per batch = **SUM(quantity_delta)** over **all** ledger rows for that (item_id, branch_id, batch_number, expiry_date, unit_cost).
- Positive deltas = additions (PURCHASE, OPENING_BALANCE, returns). Negative = deductions (SALE, TRANSFER).
- After the audit fix, `allocate_stock_fefo_with_lock()` no longer filters by `quantity_delta > 0`; it loads all relevant rows (with expiry filter), then aggregates **SUM(quantity_delta)** per batch and uses only batches with **sum > 0**, so the true available balance is used and already-consumed or partial fragments cannot be allocated.

---

### 2️⃣ Proper Locking Strategy — CONFIRMED

| Check | Status | Evidence |
|-------|--------|----------|
| `allocate_stock_fefo_with_lock()` uses SELECT ... FOR UPDATE | ✅ | `inventory_service.py`: `.with_for_update().all()` on the ledger query. |
| Lock scope = all rows involved in allocation | ✅ | All ledger rows for (item_id, branch_id) with non-expired batches are locked. |
| Entire transfer completion in ONE DB transaction | ✅ | Single `try`/`commit`/`rollback` in `complete_branch_transfer`; no intermediate commit. |
| No partial commits | ✅ | One `db.commit()` at end; on any exception, `db.rollback()`. |

**Row locking (snippet)**

```python
# app/services/inventory_service.py — allocate_stock_fefo_with_lock
rows = (
    q.order_by(
        InventoryLedger.expiry_date.asc().nulls_last(),
        InventoryLedger.batch_number.asc().nulls_last(),
    )
    .with_for_update()
    .all()
)
```

**Transaction wrapper**

- No separate wrapper; the FastAPI dependency `get_tenant_db` yields a session; `complete_branch_transfer` uses that single session and commits once at the end. All steps (lock transfer, allocate, ledger inserts, snapshot, line replacement, receipt create) run in that same transaction.

**Why double allocation cannot occur**

- For each (item_id, branch_id), the ledger rows that determine available stock are locked with `FOR UPDATE` before allocation. A second concurrent transfer for the same item at the same branch will block on that lock until the first transaction commits or rolls back. After commit, the first transfer’s negative ledger entries are visible, so the second transaction sees reduced availability and cannot double-allocate the same stock.

---

### 3️⃣ Cost Integrity — CONFIRMED

| Check | Status | Evidence |
|-------|--------|----------|
| unit_cost from locked ledger rows | ✅ | `allocate_stock_fefo_with_lock` returns `unit_cost` from aggregated batch (from ledger); transfer uses that in ledger entries and transfer/receipt lines. |
| Transfer writes negative ledger with same cost | ✅ | `branch_inventory.py`: `InventoryLedger(..., quantity_delta=-qty, unit_cost=uc, ...)` with `uc` from allocation. |
| Receipt writes positive ledger with same cost | ✅ | Receipt lines are created from transfer lines (batch, qty, unit_cost); `confirm_branch_receipt` uses `line.unit_cost` for ledger. |
| No costing engine / average cost update | ✅ | No call to `CanonicalPricingService` or average-cost logic in branch module. |

**Why valuation remains unchanged**

- Cost is read once from the locked ledger batch at transfer time and written to transfer lines and receipt lines. Receipt creates ledger entries with that same `unit_cost`. No recalculation and no change to company/item valuation logic.

---

### 4️⃣ SnapshotService Integration — CONFIRMED

| Check | Status | Evidence |
|-------|--------|----------|
| `upsert_inventory_balance` after every ledger write | ✅ | After each ledger insert block in transfer complete and receipt confirm: loop over entries and call `SnapshotService.upsert_inventory_balance(...)`. |
| Same DB transaction | ✅ | All in same session; no commit between ledger writes and snapshot calls. |
| Snapshot cannot drift | ✅ | Snapshot is updated in the same transaction that inserts ledger rows; commit is atomic. |

**How snapshot consistency is guaranteed**

- Ledger INSERTs and `SnapshotService.upsert_inventory_balance()` run in one transaction. Either the whole transaction commits (ledger + snapshot) or the whole transaction rolls back, so snapshot and ledger stay in sync.

---

## PART 2 — Critical Validation (Fixes Applied)

### ⚠️ 1️⃣ Ledger aggregation — FIXED

- **Issue:** Allocation previously filtered on `quantity_delta > 0`, so it ignored negative rows and could over-allocate when returns/reversals and deductions coexisted.
- **Fix:** `allocate_stock_fefo_with_lock()` now:
  - Selects **all** ledger rows for (item_id, branch_id) with expiry filter (no filter on sign of quantity_delta).
  - Aggregates **SUM(quantity_delta)** per (batch_number, expiry_date, unit_cost).
  - Uses only batches with **SUM(quantity_delta) > 0** and allocates in FEFO order from that balance.
- **Result:** Allocation uses true available balance per batch; already consumed stock, partial fragments, and zero-balance batches are not used.

---

### ⚠️ 2️⃣ Expiry exclusion — VERIFIED

- **Expired:** Only rows with `expiry_date IS NULL OR expiry_date >= today` are considered; expiry_date &lt; CURRENT_DATE is excluded.
- **Null expiry:** Treated as “no expiry”; included and sorted last in FEFO (`order_by(expiry_date.asc().nulls_last())`).
- **Sorting:** FEFO = expiry_date ASC NULLS LAST; earliest expiry first, nulls last. Expired stock is never allocated.

---

### ⚠️ 3️⃣ Transfer completion line replacement — FIXED

- **Request intent:** Before replacing transfer lines, we store `request_audit` on `branch_transfers`: list of `{item_id, quantity_base}` (migration 034 adds `request_audit` JSONB; model and complete flow set it).
- **Audit trail:** Original requested quantity is recoverable from `branch_transfers.request_audit`; order-linked transfers also have `branch_order_lines.quantity` and `fulfilled_qty`.

---

### ⚠️ 4️⃣ Branch order fulfillment — FIXED

- **Over-fulfillment:** When updating `fulfilled_qty`, we cap: `ol.fulfilled_qty = min(ol.quantity, (ol.fulfilled_qty or 0) + delta)` so it cannot exceed ordered quantity.
- **Multiple transfers:** Each transfer updates only the order lines it links to; cap applies per line so over-fulfillment remains impossible.

---

### ⚠️ 5️⃣ Receipt replay protection — CONFIRMED

- **Status:** Must be PENDING; if RECEIVED, return 400 "Receipt is already received".
- **Lock:** `with_for_update()` on the receipt row.
- **Double process:** Second request either blocks and then sees RECEIVED (400) or runs after commit and gets 400. No duplicate inventory.
- **Idempotent:** Second call returns 400; no second set of ledger or snapshot updates.

---

## PART 3 — Hardening (Implemented)

| Requirement | Implementation |
|-------------|----------------|
| CHECK quantity != 0 | Migration 034: `chk_branch_transfer_lines_quantity_not_zero`, `chk_branch_receipt_lines_quantity_not_zero`. |
| Prevent self-transfer | Migration 034: `chk_branch_orders_no_self_order`, `chk_branch_transfers_no_self_transfer`. API: create order and create transfer validate and return 400 if same branch. |
| Controlled status | Migration 034: `chk_branch_orders_status` (DRAFT, BATCHED), `chk_branch_transfers_status` (DRAFT, COMPLETED), `chk_branch_receipts_status` (PENDING, RECEIVED). |
| Request audit | Migration 034: `branch_transfers.request_audit` (JSONB). Complete flow sets snapshot of requested item_id/quantity_base before replacing lines. |
| Inventory sanity guard | After ledger + snapshot updates in transfer complete, `InventoryService.get_current_stock(db, item_id, supplying_branch_id)` is checked for each affected item; if &lt; 0 we raise and rollback. |

---

## PART 4 — Summary

- **Verified and confirmed:** Ledger-only batch tracking, FOR UPDATE locking, single transaction, cost from ledger only, SnapshotService in same transaction, expiry and null-expiry behaviour, receipt replay protection.
- **Missing and fixed:** Ledger aggregation (SUM over all rows per batch, HAVING sum &gt; 0); fulfilled_qty cap; request_audit and sanity check; DB constraints and self-transfer/status hardening in migration 034.
- **Purchase, sales, costing:** Untouched; only branch inventory module and one shared helper (`allocate_stock_fefo_with_lock`) were audited and hardened.

**Files changed in this audit**

- `app/services/inventory_service.py`: FEFO aggregation and locking behaviour.
- `app/api/branch_inventory.py`: Self-transfer checks, request_audit, fulfilled_qty cap, snapshot sanity check.
- `app/models/branch_inventory.py`: `request_audit` column (JSONB).
- `database/migrations/034_branch_inventory_hardening.sql`: New constraints and `request_audit` column.

**Production safety**

- FEFO and batch accuracy: allocation from true ledger balance per batch; expiry and null handling defined and compliant.
- Race safety: FOR UPDATE and single-transaction completion prevent double allocation and partial commits.
- Cost safety: no costing engine or average-cost update; transfer and receipt use same unit_cost from ledger.
- Replay safety: receipt confirmed once, row lock and status check.
- Over-fulfillment: prevented by capping fulfilled_qty.
- Self-transfer: prevented by DB and API.
- Snapshot: updated in same transaction as ledger; sanity check after transfer ensures non-negative balance before commit.
