# Item Search Snapshot (Single-Table Search)

## Overview

When enabled per company, **item search** uses a single SELECT on `item_branch_snapshot` instead of the heavy multi-query path. This table powers search across the app: **sales, quotations, inventory, suppliers**, etc. Target: **< 200 ms** backend time.

- **Default:** Off. No behavior change until explicitly enabled.
- **Enable:** Set company setting `pos_snapshot_enabled` = `true` (e.g. PUT `/api/companies/{id}/settings` with `{"key": "pos_snapshot_enabled", "value": "true"}`).
- **Requires:** Migrations 046 and 049 applied (table created and renamed to `item_branch_snapshot`), and snapshot backfilled (and dual-write in place so new writes keep it updated).

## Centralized Snapshot Recalculation

**SnapshotRefreshService** (`app/services/snapshot_refresh_service.py`) is the single entry point:

- **Single-item changes** (GRN one item, sale line, adjustment, item edit, promotion edit, floor price, manual override, Excel import):  
  → Recalculate snapshot **synchronously** in the same transaction via `schedule_snapshot_refresh(db, company_id, branch_id, item_id=...)`. If refresh fails, the transaction **rolls back** (no partial commit).

- **Bulk-impact changes** (company margin update, VAT change, category-level promotion):  
  → Insert into **deduplicated** `snapshot_refresh_queue`; process in **background** in batches.  
  → Use `schedule_snapshot_refresh(db, company_id, branch_id)` (no item_id) to enqueue a branch-wide job, or `enqueue_item_refreshes(db, company_id, branch_id, item_ids)` for a known set.  
  → Company settings update for keys in `BULK_IMPACT_SETTING_KEYS` (e.g. `pricing_settings`, `report_settings`) automatically enqueues one branch refresh per branch.

Scope is detected in `schedule_snapshot_refresh`: one item → sync; multiple items or whole branch → queue.

## Snapshot structure: one table vs many

Today there are **four** precomputed/cache tables involved in search and stock:

| Table | Purpose | Used by | Can we drop it? |
|-------|---------|--------|------------------|
| **inventory_balances** | Source of truth for current stock per (item_id, branch_id). Updated on every ledger write. | Heavy path (stock); item_branch_snapshot **reads from it** when refreshing. | **No.** It’s the ledger-derived balance. item_branch_snapshot only *copies* current_stock from here. |
| **item_branch_purchase_snapshot** | Last purchase price, date, supplier per (item_id, branch_id). | **Heavy path** (pricing/PO context); **pos_snapshot_service** uses it to set last_purchase_price when building POS snapshot. | Only if we move last_purchase_date / last_supplier_id into POS snapshot and stop using it for search. |
| **item_branch_search_snapshot** | Last order / sale / order book / quotation **dates** per (item_id, branch_id). | **Heavy path** only (display “last order date”, etc.). | Only if we add those date columns to POS snapshot and make heavy path read from POS only. |
| **item_branch_snapshot** | **Single-table item search cache**: name, stock, cost, selling price, margin, next expiry, search_text. One row per (item_id, branch_id). Used for search in sales, quotations, inventory, suppliers, etc. | **Search path** (when branch_id + pos_snapshot_enabled). | **No.** This is the “one table” for item search. |

- **Search path** (branch_id + pos_snapshot_enabled): one query on **item_branch_snapshot** only. No joins to purchase or search snapshot.
- **Heavy path**: still joins **items**, **inventory_balances**, **item_branch_purchase_snapshot**, **item_branch_search_snapshot**, plus pricing/ledger. (See implementation plan to migrate to single-table and remove duplication.)

To get **one table for all search** and avoid mix-up:

1. **Extend item_branch_snapshot** with: `last_purchase_date`, `last_supplier_id`, `last_order_date`, `last_sale_date`, etc. (optional).
2. **Make the heavy path read from item_branch_snapshot too** (see `ITEM_SEARCH_SINGLE_TABLE_IMPLEMENTATION_PLAN.md`).
3. **Stop using** item_branch_purchase_snapshot and item_branch_search_snapshot **for search**. Optionally deprecate those tables later.

**inventory_balances** stays: it’s the canonical stock; item_branch_snapshot copies `current_stock` from it when we refresh.

Summary: **item_branch_snapshot** is the single table for item search across the app (sales, quotations, inventory, suppliers). Renamed from `item_branch_pos_snapshot` to reflect app-wide use.

---

## Two snapshot tables (don’t confuse them)

| Table | Purpose | Has stock? | Has cost/price? | Has expiry? | Has batch? |
|-------|---------|------------|-----------------|-------------|------------|
| **item_branch_search_snapshot** | “Last activity” dates only: last order, last sale, last order book, last quotation. Used in heavy search for display. | No | No | No | No |
| **item_branch_snapshot** | Item search cache (app-wide): name, stock, cost, selling price, margin, next expiry, search_text. One row per (item_id, branch_id). | Yes | Yes | Yes (next_expiry_date) | No (aggregate row, not per-batch) |

Stock, last cost, selling price, and next expiry live in **item_branch_snapshot**, not in item_branch_search_snapshot. Floor price is not in the POS snapshot (it’s on Item / item_pricing and applied at read time if needed). Batch-level data (FEFO batches) stays in inventory_ledger; the snapshot only stores the single **next_expiry_date** for display/ordering.

## Table: item_branch_snapshot

- One row per (item_id, branch_id). Used for item search everywhere (sales, quotations, inventory, suppliers).
- Columns: id, company_id, branch_id, item_id, name, pack_size, base_unit, sku, vat_rate, vat_category, current_stock, average_cost, last_purchase_price, selling_price, margin_percent, next_expiry_date, search_text, updated_at.
- Updated in the **same transaction** as: GRN posting, sale posting, stock adjustment, stock take, branch transfer/receipt, quotation convert, item edit, batch quantity correction, Excel import (opening balances).

### Sync contract (critical)

- **Same transaction:** Every write that affects inventory (ledger, balances) or item master data must update `item_branch_snapshot` in the **same transaction**. No eventual consistency: if we commit a sale or GRN without refreshing the snapshot, search and stock go out of sync.
- **Fail closed:** If the snapshot refresh fails, the service **re-raises** so the whole transaction rolls back. We never commit ledger/balance changes without updating the snapshot.
- **Consequences of missing or stale snapshot:**
  - **Item not in search** → User thinks “it’s not in the system” → creates a **duplicate** item → data chaos.
  - **Wrong or zero stock** in search/dropdown → wrong decisions, overselling, or unnecessary reorders.

All write paths that touch inventory or items (sales, purchases/GRN, adjustments, stock take, transfers, quotations, item create/update, Excel import) call `SnapshotRefreshService.refresh_item_sync` (or `schedule_snapshot_refresh` with a single item_id, which uses sync refresh) so the snapshot is updated before commit.

## Backfill

After running migrations 046 and 049:

```bash
cd pharmasight/backend
python -m scripts.backfill_pos_snapshot [--batch-size=200] [--company-id=UUID]
```

Idempotent; safe to re-run.

### Validate backfill completeness (required)

If the backfill is incomplete, some (item, branch) pairs have no snapshot row. Search then omits those items; users may create duplicates or see wrong/zero stock. **Always validate after a backfill:**

```bash
cd pharmasight/backend
python -m scripts.check_snapshot_backfill_expected --strict
```

- **Exit 0:** expected row count equals actual; backfill complete.
- **Exit 1:** gap exists; fix by re-running the backfill or `python -m scripts.refresh_snapshot_for_search <term>` for affected items, then validate again.

To list a sample of missing (company_id, item_id, branch_id) pairs:

```bash
python -m scripts.check_snapshot_backfill_expected --show-missing [--limit=100]
```

## Validation

Before enabling the flag, use search with `validate_snapshot=true` (and `branch_id` + company with snapshot data). Server logs will compare snapshot vs heavy-path values (current_stock, cost) for debugging. Response is still from snapshot only; nothing extra is returned to the client.

## Enabling the flag (step-by-step)

1. **Migrations:** Ensure 046–048 are applied (they run on app startup).
2. **Backfill** the snapshot table (same DB as your app, e.g. from backend dir with env loaded):
   ```bash
   cd pharmasight/backend
   python -m scripts.backfill_pos_snapshot
   ```
   Optional: limit to one company: `--company-id=YOUR-COMPANY-UUID`. Optional: `--batch-size=200` (default).
3. **(Optional)** Test before enabling: call search with `validate_snapshot=true` and `branch_id` set; check server logs for snapshot vs heavy-path comparison.
4. **Enable the flag** for your company (requires a user with settings.edit):
   - **API:** `PUT /api/companies/{company_id}/settings` with body: `{"key": "pos_snapshot_enabled", "value": true}`.
   - **Swagger:** Open http://localhost:8000/docs → **PUT /api/companies/{company_id}/settings** → Authorize if needed → body: `{"key": "pos_snapshot_enabled", "value": true}`.
   - Replace `{company_id}` with your actual company UUID (e.g. from the app or from `GET /api/companies`).
5. **Use the app:** Search from inventory, sales, quotations, or global search **with a branch selected**. Those requests include `branch_id`, so they use the single-SELECT snapshot path (< 150 ms target).

**Check you’re on the snapshot path:** In DevTools → Network → click the **GET** `search?q=...` request (not the OPTIONS one) → **Headers** tab → look for **Response Headers** → `X-Search-Path: item_branch_snapshot` (fast) or `X-Search-Path: heavy` (slow). Alternatively check **Timing** tab: `item_branch_snapshot;dur=XX` = snapshot path; `1_base_query`, `2_stock`, `3_pricing`, etc. = heavy path.

**If you still see heavy path:** Check the backend console/logs when you run a search. You should see: `[search] company_id=... branch_id=... pos_snapshot_enabled=True/False`. If `pos_snapshot_enabled=False`, the flag is not set. Verify with `GET /api/companies/{company_id}/settings?key=pos_snapshot_enabled` (should return `{"key":"pos_snapshot_enabled","value":true}`). If the PUT didn’t persist, set the flag in the DB. In your PostgreSQL client (e.g. Supabase SQL editor), replace `YOUR-COMPANY-UUID` with your company ID (e.g. `9c71915e-3e59-45d5-9719-56d2322ff673`):

```sql
-- Update if row exists
UPDATE company_settings
SET setting_value = 'true', setting_type = 'string'
WHERE company_id = 'YOUR-COMPANY-UUID'::uuid AND setting_key = 'pos_snapshot_enabled';

-- If no row exists, insert (run only if the UPDATE affected 0 rows)
INSERT INTO company_settings (id, company_id, setting_key, setting_value, setting_type)
SELECT uuid_generate_v4(), 'YOUR-COMPANY-UUID'::uuid, 'pos_snapshot_enabled', 'true', 'string'
WHERE NOT EXISTS (SELECT 1 FROM company_settings WHERE company_id = 'YOUR-COMPANY-UUID'::uuid AND setting_key = 'pos_snapshot_enabled');
```

## Dual-write locations

| Event | Location | Action |
|-------|----------|--------|
| GRN posting | `api/purchases.py` | refresh (item_branch_snapshot) per ledger entry |
| Supplier invoice batch | `api/purchases.py` | refresh per ledger entry |
| Sale batch | `api/sales.py` | refresh per ledger entry |
| Stock adjustment | `api/items.py` adjust_stock | refresh for item/branch |
| Batch quantity correction | `api/items.py` post_batch_quantity_correction | refresh for item/branch |
| Stock take complete | `api/stock_take.py` | refresh per count and per zeroed item |
| Branch transfer | `api/branch_inventory.py` | refresh per ledger entry |
| Branch receipt | `api/branch_inventory.py` | refresh per ledger entry |
| Quotation convert | `api/quotations.py` | refresh per ledger entry |
| Item update | `api/items.py` update_item | refresh for item in all branches |
| Excel import (opening balance) | `services/excel_import_service.py` | refresh per item/branch (sync in same transaction) |

Pricing/markup changes (item_pricing or company margin) can be followed by a backfill or a future hook to refresh affected items.

## Snapshot refresh queue (bulk)

- **Table:** `snapshot_refresh_queue` (migrations 047, 048). Columns: id, company_id, branch_id, item_id (nullable), created_at, processed_at, claimed_at, reason.
- **Branch-wide job:** `item_id` IS NULL → processor **claims** the row, then refreshes items **in chunks of 200**; commits after each chunk (no 10k-item transaction). Then marks processed.
- **Item job:** `item_id` set → processor refreshes that (item_id, branch_id) in one transaction. Deduplicated per (company_id, branch_id, item_id).
- **reason:** Optional text (e.g. `company_margin_change`, `promotion_update`, `company_setting_change`) for debugging.
- **Processor:** Run `python -m scripts.process_snapshot_refresh_queue [--batch-size=50] [--once]`. Use cron or a long-lived worker; with `--once` process one batch and exit. **Operational:** If you enqueue bulk jobs but never run the processor, pricing/margin changes will not propagate to the snapshot; run the processor continuously or on a schedule in production.

---

## Audit: Branch-wide refresh behaviour (point 5)

**Q: When a branch-wide job runs, does it (A) load all items into memory and refresh in one transaction, or (B) process in chunks internally?**

**A: B — Process in chunks.**

- The processor **claims** the queue row (`claimed_at = NOW()`) and commits so the lock is released.
- It then fetches item IDs from `items` in chunks of **200** (`LIMIT 200 OFFSET 0`, then `OFFSET 200`, …).
- For each chunk: refresh those 200 items → **commit**.
- Repeat until no more items; then set `processed_at = NOW()` and commit.

So it is **fetch 200 → refresh → commit → repeat**, not “fetch 10,000 and refresh in one transaction.” Long locks, large memory, and slow commits are avoided. Migration 048 adds `claimed_at` (and optional `reason`) for this and for debugging.

---

## Testing: search speed and snapshot updates

### 1. Test that item search returns quickly (target &lt; 1 s, goal &lt; 200 ms)

1. **Enable the snapshot path** for your company (see "Enabling the flag" above). Use API or SQL so `pos_snapshot_enabled` = true.
2. **Call search with a branch in context** so the API gets `branch_id`:
   - From the app: open **Sales** or **Inventory** (or any screen that sets the current branch), then use the item search.
   - Or call the API directly:  
     `GET /api/items/search?q=paracetamol&company_id=YOUR_COMPANY_ID&branch_id=YOUR_BRANCH_ID&limit=15`
3. **Measure response time:**
   - **Browser:** DevTools → Network → select the `search?q=...` **GET** request (not OPTIONS) → **Timing** tab. "Waiting for server response" is the backend time.
   - **Response headers:** Look for `X-Search-Path: item_branch_snapshot` and `Server-Timing: item_branch_snapshot;dur=XX` (XX = milliseconds). If you see `X-Search-Path: heavy`, the snapshot path is not used (check flag and that `branch_id` is sent).
4. **Interpret:** With snapshot path and backfill in place, search should typically be well under 1 second; target is under 200 ms. If it's still slow, confirm you're on the snapshot path (headers above) and that the snapshot table has rows for that company/branch.

### 2. Test that sales and stock adjustments update the snapshot in the same transaction

The app is designed so that when the **inventory ledger** is updated (sale, GRN, adjustment, etc.), the **item_branch_snapshot** row for that (item_id, branch_id) is refreshed in the **same transaction**. You can confirm this as follows.

**A. Snapshot updates when you post a sale**

1. Pick an item and branch that have a snapshot row and non-zero stock (e.g. from a company/branch you use in Sales).
2. In the DB (e.g. Supabase SQL Editor), record current snapshot state:
   ```sql
   SELECT item_id, branch_id, current_stock, updated_at
   FROM item_branch_snapshot
   WHERE item_id = 'SOME_ITEM_UUID' AND branch_id = 'SOME_BRANCH_UUID';
   ```
   Note `current_stock` and `updated_at`.
3. In the app, create and **post** a sale that includes that item at that branch (one line, small quantity).
4. Run the same `SELECT` again. You should see:
   - `current_stock` decreased by the quantity sold.
   - `updated_at` equal to the time of the sale (same transaction as the ledger write).

**B. Snapshot updates when you do a stock adjustment**

1. Again, pick an (item_id, branch_id) that has a snapshot row. Note `current_stock` and `updated_at` with the same `SELECT` as above.
2. In the app, do a **stock adjustment** for that item at that branch (e.g. reduce or increase quantity).
3. Run the `SELECT` again. You should see:
   - `current_stock` reflecting the new balance.
   - `updated_at` equal to the time of the adjustment.

**C. If snapshot did not change**

- Confirm the write path is the one that calls **SnapshotRefreshService** (e.g. sale posting, adjustment endpoint). See "Dual-write locations" above.
- Check backend logs for errors during the sale or adjustment; a failure in the snapshot refresh could be caught and logged without failing the whole request in some code paths.
- In the DB, confirm `inventory_ledger` and `inventory_balances` were updated for that item/branch; if they were but the snapshot was not, the dual-write for that path may be missing or not committed in the same transaction.
