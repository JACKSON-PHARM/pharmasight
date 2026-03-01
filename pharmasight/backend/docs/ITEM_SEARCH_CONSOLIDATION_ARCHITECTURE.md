# Item Search: Controlled Consolidation — Architecture Summary

## Objective

Promote the snapshot search path to be the **canonical** implementation for `GET /items/search`. One service entry point; snapshot primary, heavy fallback only when snapshot data does not exist; identical response shape; no new flags/tables/schema; no removal of legacy code yet.

---

## 1. Current Flow (Before Consolidation)

### Controller (`GET /api/items/search`)

- **Query params:** `q`, `company_id`, `branch_id?`, `limit`, `include_pricing`, `fast`, `context?`, `validate_snapshot?`
- **Branching in controller:**
  1. **Snapshot path:** If `branch_id` **and** `pos_snapshot_enabled` (company setting) → run snapshot query in controller; on success return; on exception fall back to heavy.
  2. **Heavy path:** Base query on `items` (GIN index) → then:
     - **Fast sub-path:** If `fast=True` → build a **different** response shape (e.g. `strength`, `pack_size`, `selling_price`, `total_stock`) and return.
     - **Full heavy:** Else → fetch stock (`inventory_balances`), purchase/search snapshots, costs, markup, suppliers, then build full item list with one response shape.
- **Stock formatting:** Called in three places — snapshot path (with `Item` from extra query), heavy fast path, heavy full path — each using `InventoryService.format_quantity_display(...)` (and `_unit_for_display`).
- **Response shape:** Snapshot path and full heavy path are similar but not identical (snapshot has `margin_percent`, `next_expiry_date`; full heavy does not). Fast path has a different shape.

### Data Paths

| Path              | Condition                         | Tables / logic |
|-------------------|-----------------------------------|-----------------|
| Snapshot          | `branch_id` + `pos_snapshot_enabled` | Single SELECT on `item_branch_snapshot`; then Item fetch for retail_unit/stock_display. |
| Heavy (fast)      | `fast=True`                       | Items + `inventory_balances`; minimal DTO. |
| Heavy (full)      | else                              | Items → inventory_balances, item_branch_purchase_snapshot, item_branch_search_snapshot, costs, markup, suppliers → full DTO. |

### Problems (addressed by consolidation)

- Search logic and branching live in the controller.
- Two response shapes (full vs fast) and small differences between snapshot and full heavy (margin_percent, next_expiry_date).
- Stock display formatting duplicated at multiple call sites (same function, multiple places).
- Snapshot is gated by a **flag** (`pos_snapshot_enabled`) instead of “use snapshot when data exists.”

---

## 2. Proposed Consolidated Flow

### Controller

- **Single call:** `GET /items/search` → calls **one** method: `ItemSearchService.search(db, q, company_id, branch_id, limit, include_pricing, context)`.
- **No branching** in the controller: no `pos_snapshot_enabled` check, no `fast` branching, no inline snapshot vs heavy logic. Query params stay the same for backward compatibility; `fast` is only passed through and handled inside the service (see below).
- **Response:** Controller returns whatever the service returns (same shape for both snapshot and heavy).

### Service: `ItemSearchService.search(...)`

- **Single entry point** for all item search behavior.
- **Primary:** Try **snapshot query** when `branch_id` is present:
  - Query `item_branch_snapshot` for (company_id, branch_id, search_text ILIKE).
  - If the query **succeeds** and returns **any rows** (or even zero rows) → use snapshot as the source of truth; build response from snapshot rows (with Item lookup only for retail_unit / stock_display).
  - **Fallback:** Only if snapshot **cannot be used**: e.g. no `branch_id`, or snapshot query fails (exception), or we decide “snapshot data does not exist” (see below) → run **heavy** path.
- **“Snapshot data does not exist”** (when to fall back):
  - **Option A (recommended):** No fallback for “empty result”; only fall back on **exception** or when **branch_id is missing**. So: snapshot is primary whenever we have branch_id and the single SELECT runs successfully (even if it returns 0 rows).
  - **Option B:** Fall back when snapshot returns 0 rows (treat “no rows” as “no data”). This would push more traffic to heavy when backfill is incomplete.
  - **Recommendation:** Option A — use snapshot whenever we have branch_id and the query succeeds; empty result is still “success from snapshot.”
- **Heavy path (fallback):** Existing heavy logic moved into the service (items + inventory_balances + purchase/search snapshots + pricing, etc.). When `fast=True`, the heavy path can still return a reduced shape for backward compatibility, **or** we can drop the `fast` branch and always return the same full shape from heavy (simpler; one shape). *To confirm with you.*
- **Response shape:** One canonical shape for both snapshot and heavy (full) paths. Snapshot already has `margin_percent`, `next_expiry_date`; heavy path will be extended to include these (from snapshots or null) so the contract is identical.
- **Stock formatting:** One shared helper used by both paths (e.g. private method that calls `InventoryService.format_quantity_display` + `_unit_for_display`), so “stock formatting is called from one shared function only” within the service.

### What stays

- All existing tables and schema (no new tables, no schema change).
- All heavy-path code (moved into the service, marked as **fallback** in comments).
- No new flags: `pos_snapshot_enabled` is **not** used for routing; snapshot is used whenever branch_id is set and the snapshot query runs successfully.
- No new endpoints.

### What changes

- **Controller:** No snapshot/heavy/fast branching; single `ItemSearchService.search(...)` call.
- **Routing:** Snapshot is primary when `branch_id` is present and snapshot query succeeds; heavy is fallback (no flag check).
- **Response shape:** Aligned so snapshot and heavy (full) return the same keys; heavy path extended to include `margin_percent` and `next_expiry_date` (or explicit nulls).
- **Stock formatting:** Single call path inside the service to `InventoryService.format_quantity_display` (and unit display) for building `stock_display`.

### Optional (your choice)

- **`fast` param:** Keep in API for backward compatibility but implement inside service: when falling back to heavy, if `fast=True` return the current “fast” shape; otherwise return full shape. Or remove fast path and always return full shape from heavy.
- **`validate_snapshot`:** Can remain as an optional debug flag passed to the service to log snapshot vs heavy values when both could be compared (e.g. in fallback path); no change to client contract.

---

## 3. Summary Diagram

**Current:**

```
GET /items/search
  → if branch_id && pos_snapshot_enabled → snapshot query in controller → return
  → else heavy path:
       → if fast → build fast shape → return
       → else full heavy (items + balances + snapshots + pricing) → return
  (stock_display in 3 places)
```

**Proposed:**

```
GET /items/search
  → ItemSearchService.search(db, q, company_id, branch_id, limit, include_pricing, context, fast?, validate_snapshot?)
       → if branch_id: try snapshot query
            → success → build response from snapshot (shared stock format) → return
       → fallback: heavy path (marked as fallback in code)
            → build same response shape (shared stock format); optionally respect fast for reduced shape
       → return
```

---

## 4. Clarifications Before Implementation

1. **Fallback condition:** **Option A** (fall back only on exception or missing branch_id; treat empty snapshot result as valid snapshot result)?
2. **`fast` param:** Keep and have heavy fallback return the current “fast” shape when `fast=True`, or drop it and always return the full canonical shape from heavy?
3. **`pos_snapshot_enabled`:** Confirm it is no longer used for search routing (snapshot is used whenever branch_id is set and snapshot query succeeds). The setting can remain in DB for other uses or future feature toggles if needed.

Implementation complete: `ItemSearchService.search(...)` added, snapshot + heavy logic in service, unified response shape and stock formatting; controller calls service only. Heavy fallback logs when it runs.
