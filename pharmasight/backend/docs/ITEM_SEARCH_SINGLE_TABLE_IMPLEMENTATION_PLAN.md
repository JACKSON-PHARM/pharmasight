# Item Search: Single-Table Implementation & Cleanup Plan

**Goal:** Item search uses only `item_branch_snapshot`, achieves **&lt; 200 ms** for the dropdown, and removes duplicated logic and old/unused tables for this scope.

---

## Scope

- **In scope:** `/api/items/search` (dropdown and any caller that uses it); removal of dependency on `item_branch_purchase_snapshot` and `item_branch_search_snapshot` for search; ensuring POS snapshot is the single source for search when `branch_id` is provided.
- **Out of scope (unchanged):** `inventory_balances` (remains source of truth for stock); ledger and other write paths except where we stop writing to the deprecated snapshots.

---

## Current State (Brief)

| Component | Current behavior |
|-----------|------------------|
| **Search when `branch_id` + `pos_snapshot_enabled`** | Single SELECT on `item_branch_snapshot` → fast. |
| **Search when no flag or no branch_id** | “Heavy” path: `items` + `inventory_balances` + `item_branch_purchase_snapshot` + `item_branch_search_snapshot` + pricing/ledger → slow (multiple queries, joins). |
| **POS snapshot refresh** | `pos_snapshot_service.refresh_pos_snapshot_for_item` reads `last_purchase_price` from `item_branch_purchase_snapshot`; other data from inventory_balances, ledger, pricing, item. |
| **Purchase snapshot** | Written by: purchases (GRN, supplier invoice), excel import. Read by: search (heavy path), pos_snapshot_service. |
| **Search snapshot** | Written by: purchases (PO), sales, quotations, order_book. Read by: search (heavy path) only. |

---

## Phase 1 — Search Always Uses POS Snapshot When `branch_id` Is Present

**Objective:** For any request with `branch_id`, search reads only from `item_branch_snapshot`. No feature flag, no heavy path for that case.

1. **`app/api/items.py` – `search_items`**
   - When `branch_id` is present:
     - Always run the single SELECT on `item_branch_snapshot` (company_id, branch_id, search_text ILIKE, order by stock/name, limit).
     - Remove the `pos_snapshot_enabled` check; no fallback to heavy path when branch_id is set.
     - On exception (e.g. table missing in old DB), log and return empty or minimal fallback; do not join purchase/search snapshot.
   - When `branch_id` is absent (e.g. company-wide search):
     - Keep a **minimal fallback**: query `items` only (with existing GIN/indexed search), optionally one query to `inventory_balances` if stock is required. Do **not** join `item_branch_purchase_snapshot` or `item_branch_search_snapshot`.
   - Remove all code that queries `ItemBranchPurchaseSnapshot` or `ItemBranchSearchSnapshot` in the search endpoint (raw SQL with `unnest` + LEFT JOIN, and the ORM queries for purchase snapshot / last_order_date). Response for branch-scoped search is built only from the POS snapshot row (id, name, base_unit, sku, vat_*, current_stock, average_cost, last_purchase_price, selling_price, margin_percent, next_expiry_date; map to the same response shape the UI expects).
   - Remove the `fast` path that still used `items` + `inventory_balances` when branch_id was set (so the only path when branch_id is set is POS snapshot).
   - Keep `include_pricing` and `context` for response shape; POS snapshot already has pricing/cost, so no extra queries. For `context == "purchase_order"`, include last_supply_date/last_unit_cost/cheapest_supplier as null or from snapshot if we add them later.
   - Remove or simplify `validate_snapshot` (no “heavy” path to compare to when branch_id is set). Optional: keep a debug header or log timing only.
   - Ensure response shape and fields match what the frontend dropdown expects (id, name, current_stock, sale_price, purchase_price, etc.) so no frontend change is required.

2. **Docs / config**
   - Update `POS_SNAPSHOT_SEARCH.md`: search with `branch_id` always uses POS snapshot; remove or reframe “feature flag” as legacy; document that backfill must be run so the table is populated.
   - Optional: remove `pos_snapshot_enabled` from company settings (or leave as no-op) and document that branch-scoped search is always POS-snapshot-based.

**Outcome:** Dropdown (and any caller that sends `branch_id`) gets &lt; 200 ms from a single table. No reads from purchase or search snapshot in search.

---

## Phase 2 — Stop Using Purchase and Search Snapshots in Search (Cleanup)

**Objective:** No code path in the search endpoint touches `item_branch_purchase_snapshot` or `item_branch_search_snapshot`.

1. **`app/api/items.py`**
   - Remove imports and any remaining references to `ItemBranchPurchaseSnapshot` and `ItemBranchSearchSnapshot` in the search handler.
   - Confirm the “no branch_id” fallback uses only `items` (and optionally `inventory_balances`); no purchase/search snapshot.

2. **Other consumers (if any)**
   - Grep for any other read usage of `item_branch_purchase_snapshot` or `item_branch_search_snapshot` outside search (e.g. reports, exports). If none for search scope, no change. If any, decide: either adapt to use POS snapshot or keep that code path but out of scope for this plan.

**Outcome:** Search is fully decoupled from the two legacy snapshot tables.

---

## Phase 3 — POS Snapshot as Single Source; Optional Date Columns

**Objective:** Ensure the dropdown has everything it needs from `item_branch_snapshot` only. Add optional “last activity” date columns only if the UI needs them.

1. **Response shape**
   - Current POS snapshot columns are enough for the usual dropdown: id, name, pack_size, base_unit, sku, vat_*, current_stock, average_cost, last_purchase_price, selling_price, margin_percent, next_expiry_date. Map these to the existing API response (e.g. `last_supplier`, `last_order_date` can be null for now unless we add them to the table).

2. **Optional: add “last activity” to POS snapshot**
   - If product/UX requires “last order date” or “last sale date” in the dropdown or elsewhere from search, add columns to `item_branch_snapshot`: e.g. `last_order_date`, `last_sale_date`, `last_order_book_date`, `last_quotation_date` (match `item_branch_search_snapshot`).
   - Migration: add columns (nullable), backfill from `item_branch_search_snapshot` or from ledger/PO/sales (one-time). Then in write paths (PO, sales, order book, quotation), when we currently call `SnapshotService.upsert_search_snapshot_*`, also update the corresponding date on `item_branch_snapshot` (or call `SnapshotRefreshService.schedule_snapshot_refresh` for affected items so refresh_pos_snapshot_for_item can set them if we add them to that function). Prefer updating POS snapshot in the same transaction over a separate job when possible.
   - If the dropdown does **not** need these dates, skip this and leave them null in the response.

**Outcome:** Dropdown and search response are 100% from `item_branch_snapshot` when `branch_id` is present; no missing fields for the UI.

---

## Phase 4 — Stop Writing to Search Snapshot (Deprecate Table)

**Objective:** No new writes to `item_branch_search_snapshot` so it can be dropped later.

1. **Call sites that write to search snapshot**
   - `SnapshotService.upsert_search_snapshot_last_order` — called from: purchases (PO), order_book.
   - `SnapshotService.upsert_search_snapshot_last_sale` — called from: sales, quotations.
   - `SnapshotService.upsert_search_snapshot_last_order_book` — called from: order_book_service.
   - Remove or no-op these calls. If Phase 3 added date columns to POS snapshot, ensure those dates are updated in the same write paths (e.g. in the code that posts PO/sale/order book/quotation, after ledger + inventory_balances + POS snapshot refresh, do not call the search snapshot methods).

2. **SnapshotService**
   - Either remove the three `upsert_search_snapshot_*` methods or make them no-ops (or guard with a “deprecated” flag). Ensure no caller relies on them for search.

**Outcome:** `item_branch_search_snapshot` is no longer written to; safe to drop in a later migration.

---

## Phase 5 — Purchase Snapshot: Use Only for POS Refresh, Then Optional Drop

**Objective:** Remove duplication while keeping POS snapshot correct. Today `pos_snapshot_service` reads `last_purchase_price` from `item_branch_purchase_snapshot`.

**Option A (minimal):** Keep `item_branch_purchase_snapshot`. Continue writing to it on GRN/supplier invoice/import. POS snapshot refresh continues to read `last_purchase_price` from it. No use in search. Table remains for “refresh input” only.

**Option B (full cleanup):** Stop using the table entirely.
- In `pos_snapshot_service.refresh_pos_snapshot_for_item`: stop querying `ItemBranchPurchaseSnapshot`. Obtain `last_purchase_price` from ledger (e.g. latest PURCHASE or relevant transaction by item_id, branch_id, company_id) or from existing `CanonicalPricingService` / cost logic if it exposes “last purchase unit cost.”
- Remove all call sites to `SnapshotService.upsert_purchase_snapshot` (purchases, excel import). Optionally keep the method as no-op for a release.
- After one release with no readers and no writers, add a migration to drop `item_branch_purchase_snapshot`.

**Recommendation:** Phase 5 can be Option A first (remove from search only), then Option B in a follow-up when cost source from ledger is verified and backfill is not needed.

---

## Phase 6 — Drop Deprecated Tables (After Safe Period)

**Objective:** Remove old tables to avoid confusion and duplication.

1. **Drop `item_branch_search_snapshot`**
   - After Phase 4 has been in production and no code reads or writes it, add a migration: `DROP TABLE IF EXISTS item_branch_search_snapshot CASCADE;` (and drop any FK or views if present). Remove model `ItemBranchSearchSnapshot` and any remaining references.

2. **Drop `item_branch_purchase_snapshot` (if Option B of Phase 5 is done)**
   - After POS refresh no longer reads from it and no code writes to it, add a migration: `DROP TABLE IF EXISTS item_branch_purchase_snapshot CASCADE;`. Remove model `ItemBranchPurchaseSnapshot` and any remaining references.

3. **Scripts and docs**
   - Update `diagnose_search_schema.py`, `reconcile_snapshots.py`, and any other scripts that reference these tables. Update `POS_SNAPSHOT_SEARCH.md` and `ITEM_SEARCH_OPTIMIZATION.md` to describe the single-table design and note removal of the old snapshots.

---

## Order of Work (Suggested)

| Order | Phase | Delivers |
|-------|--------|----------|
| 1 | Phase 1 | Search with `branch_id` always uses POS snapshot; &lt; 200 ms; no purchase/search snapshot in that path. |
| 2 | Phase 2 | No remaining references to purchase/search snapshot in search code. |
| 3 | Phase 3 | Response shape and optional date columns (if needed) so dropdown is fully served from POS snapshot. |
| 4 | Phase 4 | No writes to search snapshot; table deprecated. |
| 5 | Phase 5 | Purchase snapshot either kept as refresh input only (A) or removed after moving last_purchase to ledger (B). |
| 6 | Phase 6 | Migrations to drop deprecated tables; model and script cleanup. |

---

## Testing & Rollout

- **Backfill:** Before or right after Phase 1, ensure `item_branch_snapshot` is backfilled for all (company_id, branch_id, item_id) so branch-scoped search returns results.
- **Performance:** Run search with `branch_id` and verify Server-Timing / X-Search-Path and latency &lt; 200 ms (ideally &lt; 150 ms).
- **Regression:** Smoke-test dropdown in sales, inventory, quotations, and any other screen that uses item search with a branch selected; confirm results and fields match previous behavior (except possibly last_order_date etc. if not yet added).
- **No branch_id:** Test company-wide or no-branch search and confirm minimal fallback works and does not hit dropped tables.

---

## Summary

- **Search:** When `branch_id` is present → one SELECT on `item_branch_snapshot`; target &lt; 200 ms for the dropdown. When `branch_id` is absent → minimal path (items ± inventory_balances), no purchase/search snapshot.
- **Cleanup:** Remove all use of `item_branch_purchase_snapshot` and `item_branch_search_snapshot` from search; stop writing to search snapshot; optionally migrate POS refresh off purchase snapshot and drop both tables.
- **Single table:** For branch-scoped item search, `item_branch_snapshot` is the only table read; it is updated in the same transaction as inventory ledger and related writes, so the design remains consistent and fast.
