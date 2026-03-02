# Item Branch Snapshot Sync Fix

## Problem
Stock adjustments (and some other write paths) were updating `inventory_ledger` and `inventory_balances` but not `item_branch_snapshot`. Item search reads from `item_branch_snapshot`, so it showed stale or no stock for affected items. New items were not loaded into the snapshot, so they did not appear in search.

## Changes Made

### 1. Complete Branch Transfer (Missing Snapshot Update)
**File:** `backend/app/api/branch_inventory.py`
- When completing a branch transfer, inventory is deducted from the **supplying branch** but the snapshot was never updated there.
- **Fix:** Added `SnapshotRefreshService.schedule_snapshot_refresh` for each affected item at the supplying branch, in the same transaction.

### 2. Batch Metadata Correction (Missing Snapshot Update)
**File:** `backend/app/api/items.py`
- Correcting batch expiry_date changes `next_expiry_date` in the snapshot; the refresh was missing.
- **Fix:** Added `SnapshotRefreshService.schedule_snapshot_refresh` before commit.

### 3. New Item Creation (Missing Snapshot)
**File:** `backend/app/api/items.py`
- New items were never loaded into `item_branch_snapshot`, so they did not appear in item search.
- **Fix:** Added `SnapshotRefreshService.schedule_snapshot_refresh_for_item_all_branches` before commit in both `create_item` and `bulk_create_items`.

### 4. Cost Adjustment (Missing Snapshot)
**File:** `backend/app/api/items.py`
- Adjusting batch cost affects `average_cost` and `selling_price` in the snapshot but was not refreshing.
- **Fix:** Added `SnapshotRefreshService.schedule_snapshot_refresh` before commit in `post_cost_adjustment`.

### 5. Item Update (Snapshot After Commit)
**File:** `backend/app/api/items.py`
- Item update (e.g. floor_price_retail) was committing first, then refreshing snapshot. If refresh failed, item was persisted but snapshot stale.
- **Fix:** Moved `schedule_snapshot_refresh_for_item_all_branches` to run before commit, in the same transaction.

### 6. Floor Price Enforcement
**Files:** `backend/app/api/sales.py`, `backend/app/services/pos_snapshot_service.py`
- Sales batch did not validate `floor_price_retail`; selling below floor was allowed.
- Snapshot `selling_price` ignored floor, so recommended price could be below minimum.
- **Fix:** Added `validate_line_price` to `batch_sales_invoice`; snapshot now applies `max(computed, floor_price_retail)` when floor is set.

### 7. Snapshot Refresh Must Not Silently Skip
**File:** `backend/app/services/pos_snapshot_service.py`
- `refresh_pos_snapshot_for_item` previously returned silently when the item was not found, allowing partial commits (ledger updated, snapshot not).
- **Fix:** Now raises `ValueError` when item is not found, so the transaction rolls back and no partial commit occurs.

### 8. Write Paths Audit (Inventory / Stock / Pricing)
All endpoints that affect inventory ledger, stocks, or prices now update `item_branch_snapshot` in the same transaction:
- **Item create** ✓ (added)
- **Item bulk create** ✓ (added)
- **Item update** ✓ (moved before commit)
- **Stock adjustment** (`adjust-stock`) ✓
- **Batch quantity correction** ✓
- **Batch metadata correction** ✓
- **Cost adjustment** ✓ (added)
- GRN posting ✓
- Purchase invoice batching ✓
- Sales posting ✓
- Quotation convert ✓
- Stock take complete ✓
- Branch transfer complete ✓
- Branch receipt confirm ✓
- Excel import (single and bulk) ✓

### 5. Backfill for Skipped Items

**Option A: SQL migration (Supabase)**
```bash
# Run 051_backfill_item_branch_snapshot_inventory_only.sql in Supabase SQL Editor
# Targets only (item_id, branch_id) with inventory_balances (fast, fixes skipped items)
```

**Option B: Python script**
```bash
cd pharmasight/backend
# Fast: only items with stock
python -m scripts.backfill_pos_snapshot --inventory-only

# Full: all items × all branches
python -m scripts.backfill_pos_snapshot --batch-size=200
```

## Transaction Guarantee
If `item_branch_snapshot` refresh fails for any reason (e.g. item not found, DB error), the whole transaction rolls back. No partial commit: either ledger + snapshot both update, or neither does.
