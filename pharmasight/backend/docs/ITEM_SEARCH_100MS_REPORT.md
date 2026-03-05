# Item Search &lt;100 ms — Implementation Report

**Goal:** Item search consistently under 100 ms, including at **~1.5M rows** (200 branches × ~7,500 items per branch).

---

## 1. What was done

### 1.1 Indexes and extension (migration 060)

- **`pg_trgm`**  
  - Verified/installed with:  
    `CREATE EXTENSION IF NOT EXISTS pg_trgm;`  
  - Check:  
    `SELECT extname FROM pg_extension WHERE extname = 'pg_trgm';`  
    → Expect one row.

- **Branch filter index**  
  - `idx_item_branch_snapshot_company_branch` on `(company_id, branch_id)`.  
  - Narrows to one branch (~7.5k rows at 1.5M scale).

- **Trigram GIN index**  
  - `idx_item_branch_snapshot_search_text_gin` on `item_branch_snapshot`  
    `USING gin(search_text gin_trgm_ops)`.  
  - Makes `ILIKE '%term%'` use the index instead of a sequential scan.

- **Statistics**  
  - `ANALYZE item_branch_snapshot;` so the planner uses these indexes.

**File:** `pharmasight/database/migrations/060_ensure_item_search_indexes.sql`

### 1.2 Single-table search, no Item join (migration 061 + code)

- **Snapshot table**  
  - Added to `item_branch_snapshot`:  
    `retail_unit`, `supplier_unit`, `wholesale_unit`, `wholesale_units_per_supplier`.  
  - Backfilled from `items` so search does not need to join `items`.

- **Search query**  
  - Before: `item_branch_snapshot` ⋈ `items` (join for 4 unit columns).  
  - After: single table on `item_branch_snapshot` only (no join).  
  - Same filter: `company_id`, `branch_id`, `search_text ILIKE '%term%'`, same `ORDER BY` and `LIMIT`.

- **Write path**  
  - POS snapshot refresh writes the four unit columns from `items` into `item_branch_snapshot` so new/updated rows stay in sync.

**Files:**  
- `pharmasight/database/migrations/061_snapshot_unit_columns_no_join.sql`  
- `pharmasight/backend/app/models/snapshot.py` (new columns)  
- `pharmasight/backend/app/services/pos_snapshot_service.py` (INSERT/UPDATE with unit columns)  
- `pharmasight/backend/app/services/item_search_service.py` (single-table query, no `Item` import, `_item_like_from_snapshot_row` for display)

### 1.3 Diagnostic script

- **File:** `pharmasight/database/diagnose_item_search_indexes.sql`  
- Steps:  
  1. Check `pg_trgm`.  
  2. List indexes on `item_branch_snapshot`.  
  3. Row count.  
  4. `EXPLAIN (ANALYZE, BUFFERS)` for the search query (single table, no join).

---

## 2. Final query used by the search endpoint

Single table, no join:

```sql
SELECT *  -- in app: db.query(ItemBranchSnapshot)
FROM item_branch_snapshot s
WHERE s.company_id = :company_id
  AND s.branch_id = :branch_id
  AND s.search_text ILIKE :pattern   -- e.g. '%nilacid%'
ORDER BY (s.current_stock <= 0), s.name
LIMIT :limit;
```

- **Pattern:** `search_text ILIKE '%term%'` (term lowercased in app).  
- **Indexes used:**  
  - `idx_item_branch_snapshot_company_branch` for `(company_id, branch_id)`.  
  - `idx_item_branch_snapshot_search_text_gin` for the `ILIKE` on `search_text`.  
- Planner can use both (e.g. BitmapAnd of both index scans).

---

## 3. Expected query plan and execution time

After running **060** and **061**:

- **Plan:**  
  - You should see **Bitmap Index Scan** (or **Index Scan**) involving  
    `idx_item_branch_snapshot_search_text_gin` and/or  
    `idx_item_branch_snapshot_company_branch`.  
  - You must **not** see **Seq Scan on item_branch_snapshot** for this query.

- **Execution time (EXPLAIN ANALYZE):**  
  - Target: **&lt;50 ms** in normal conditions so that end-to-end API stays **&lt;100 ms**.

- **How to check:**  
  Run the `EXPLAIN (ANALYZE, BUFFERS)` block in  
  `pharmasight/database/diagnose_item_search_indexes.sql`  
  in your **tenant** DB (same as used by the API), with your real `company_id`, `branch_id`, and search term.

---

## 4. Indexes used

| Index | Table | Definition | Role |
|-------|--------|------------|------|
| `idx_item_branch_snapshot_company_branch` | `item_branch_snapshot` | `(company_id, branch_id)` | Restrict to one branch (~7.5k rows at 1.5M). |
| `idx_item_branch_snapshot_search_text_gin` | `item_branch_snapshot` | `USING gin(search_text gin_trgm_ops)` | Fast `ILIKE '%term%'` on `search_text`. |

- **Extension:** `pg_trgm` (required for `gin_trgm_ops`).

---

## 5. Scalability: &lt;100 ms at ~1.5M rows

- **Data shape:** ~1.5M rows ≈ 200 branches × ~7,500 items per branch.  
- **Per request:** Filter by one `(company_id, branch_id)` → ~7,500 rows, then `ILIKE '%term%'` with `LIMIT 50`.  
- **Why it stays fast:**  
  1. **(company_id, branch_id)** index cuts the working set to one branch.  
  2. **GIN trigram** on `search_text` resolves `ILIKE '%term%'` by index, not by scanning all 7.5k rows.  
  3. **No join:** single table, so no extra lookups or joins.  
  4. **search_text** is stored in lowercase (from `pos_snapshot_service._search_text_for_item`); query uses `q.lower()`, so matching is consistent and index-friendly.

With these in place, search is designed to stay **under 100 ms** at ~1.5M rows, with EXPLAIN ANALYZE typically **under 50 ms** for the search query itself.

---

## 6. Deployment order

1. **Run in tenant DB (same DB as `/api/items/search`):**  
   - `060_ensure_item_search_indexes.sql`  
   - `061_snapshot_unit_columns_no_join.sql`  
2. **Deploy application** (backend that uses the updated snapshot model and single-table search).  
3. **Optional:** Run `diagnose_item_search_indexes.sql` and confirm plan and execution time.

---

## 7. Summary

| Item | Status |
|------|--------|
| **pg_trgm** | Ensured in 060 (`CREATE EXTENSION IF NOT EXISTS pg_trgm`) |
| **GIN index on search_text** | `idx_item_branch_snapshot_search_text_gin` in 060 |
| **Branch index** | `idx_item_branch_snapshot_company_branch` in 060 |
| **EXPLAIN ANALYZE** | Script in `diagnose_item_search_indexes.sql`; expect Index/Bitmap scan, &lt;50 ms |
| **Seq Scan** | Avoided by using the two indexes above |
| **search_text lowercase** | Already done in `_search_text_for_item` |
| **Unnecessary join** | Removed; unit columns denormalized into snapshot (061 + code) |
| **Columns returned** | Single table; app still returns full POS search response shape |
| **&lt;100 ms at 1.5M rows** | Designed for by indexes + single-table query + no join |

After applying 060 and 061 and deploying, run the diagnostic script and confirm the plan and execution time in your environment.
