# Item Search Latency Investigation (~1s → &lt;100ms)

**Context:** Item search (`GET /api/items/search?q=nilacid&company_id=...&branch_id=...&limit=50&include_pricing=true`) is taking ~1.05s server-side. Goal: &lt;100ms.

---

## 1. Where the search runs

| Layer | File | Symbol |
|-------|------|--------|
| **API** | `app/api/items.py` | `search_items()` (GET `/search`) |
| **Service** | `app/services/item_search_service.py` | `ItemSearchService.search()` → `_search_impl()` |

**Flow:** Request → `get_current_user` (auth; cached after first call) → `ItemSearchService.search()` → single DB query (snapshot + Item join) → JSON response. Server-Timing header reports `item_branch_snapshot;dur=<ms>`.

---

## 2. Exact query used

Search does **not** hit the `items` table for the main filter. It uses **`item_branch_snapshot`** only (one row per item per branch), then joins **`items`** for four display columns.

**Effective logic (from `item_search_service.py`):**

```python
search_term_pattern = f"%{q.lower()}%"   # e.g. "%nilacid%"

rows = (
    db.query(
        ItemBranchSnapshot.item_id, ItemBranchSnapshot.name, ItemBranchSnapshot.pack_size,
        ItemBranchSnapshot.base_unit, ItemBranchSnapshot.sku, ItemBranchSnapshot.vat_rate,
        ItemBranchSnapshot.vat_category, ItemBranchSnapshot.current_stock,
        ItemBranchSnapshot.average_cost, ItemBranchSnapshot.last_purchase_price,
        ItemBranchSnapshot.selling_price, ItemBranchSnapshot.margin_percent,
        ItemBranchSnapshot.next_expiry_date, ItemBranchSnapshot.effective_selling_price,
        ItemBranchSnapshot.price_source, ItemBranchSnapshot.last_purchase_date,
        ItemBranchSnapshot.last_supplier_id, ItemBranchSnapshot.last_order_date,
        Item.retail_unit, Item.supplier_unit, Item.wholesale_unit, Item.wholesale_units_per_supplier,
    )
    .join(Item, Item.id == ItemBranchSnapshot.item_id)
    .filter(
        ItemBranchSnapshot.company_id == company_id,
        ItemBranchSnapshot.branch_id == branch_id,
        ItemBranchSnapshot.search_text.ilike(search_term_pattern),
    )
    .order_by(
        (ItemBranchSnapshot.current_stock <= 0).asc(),
        ItemBranchSnapshot.name.asc(),
    )
    .limit(limit)
    .all()
)
```

So the search condition is:

- **Table:** `item_branch_snapshot` (joined to `items` on `items.id = item_branch_snapshot.item_id`).
- **Filter:** `company_id = ?`, `branch_id = ?`, `search_text ILIKE '%term%'`.
- **Search type:** `ILIKE '%term%'` (leading wildcard → cannot use a plain B-tree index; needs trigram/GIN for speed).

---

## 3. Indexes (from migrations)

Defined in migrations:

| Index | Table | Definition | Purpose |
|-------|--------|------------|---------|
| `idx_item_branch_snapshot_company_branch` | `item_branch_snapshot` | `(company_id, branch_id)` | Narrow by branch |
| `idx_item_branch_snapshot_item_branch` | `item_branch_snapshot` | UNIQUE `(item_id, branch_id)` | Uniqueness / upserts |
| **`idx_item_branch_snapshot_search_text_gin`** | `item_branch_snapshot` | **GIN (`search_text` gin_trgm_ops)** | Fast `ILIKE '%x%'` on `search_text` |

- **046:** created `item_branch_pos_snapshot` with the GIN on `search_text` (and `CREATE EXTENSION IF NOT EXISTS pg_trgm`).
- **049:** renamed table to `item_branch_snapshot` and index to `idx_item_branch_snapshot_search_text_gin`.
- **059:** only adds columns; does **not** drop the GIN index.

So **by design** the search should use:

1. B-tree on `(company_id, branch_id)` and/or  
2. GIN trigram on `search_text`  

and combine them (e.g. BitmapAnd). If the GIN or `pg_trgm` is missing in your DB, Postgres will fall back to a **sequential scan + ILIKE**, which can easily be ~1s on 100k+ rows.

---

## 4. `items` table (not used for the search filter)

The **search filter** is only on `item_branch_snapshot` (`company_id`, `branch_id`, `search_text`). The `items` table is used only for a **join by PK** (`Item.id = ItemBranchSnapshot.item_id`) to pull four columns: `retail_unit`, `supplier_unit`, `wholesale_unit`, `wholesale_units_per_supplier`. Indexes on `items.name`, `items.sku`, `items.barcode`, `items.company_id` do **not** affect this search path.

---

## 5. Joins and `include_pricing`

- **Join:** One join: `item_branch_snapshot` → `items` on `items.id = item_branch_snapshot.item_id` (PK lookup per snapshot row).
- **`include_pricing=true`:** Does **not** add extra queries or joins. Pricing (e.g. `effective_selling_price`, `last_purchase_price`, `margin_percent`) is read from the same snapshot row; the service only chooses which fields to expose. So the ~1s is not from extra pricing queries.

---

## 6. RLS (Row Level Security)

- Auth sets `SET LOCAL` for company scoping on the **full** resolve path; for the **cached** item-search path the code deliberately **skips** `SET LOCAL` to save a round-trip (`dependencies.py`: “Fast path for item search: no SET LOCAL, no user fetch”).
- There is no RLS-specific logic in the code for `item_branch_snapshot` or `items` in this path. If RLS is enabled on these tables in Supabase, each row access will still be checked; that can add cost but is secondary to the main issue: missing or unused GIN index leading to a sequential scan.

---

## 7. Likely cause of ~1s latency

1. **Missing or unused GIN trigram index on `search_text`**  
   - If `idx_item_branch_snapshot_search_text_gin` does not exist, or `pg_trgm` is not installed, Postgres will do a **sequential scan** on `item_branch_snapshot` with `ILIKE '%nilacid%'`.  
   - On tens or hundreds of thousands of rows, that often lands in the ~1s range.

2. **Large `item_branch_snapshot`**  
   - Even with the right index, a very large table and/or bad plan (e.g. not using the GIN or not combining well with `(company_id, branch_id)`) can keep latency high.

3. **First-request auth**  
   - First request after cache expiry does full auth + tenant resolution; this adds 200–500 ms in some setups. The **sustained** ~1s after warm-up strongly points to the query itself.

---

## 8. What to do (to get under 100ms)

### 8.1 Verify indexes and plan (do this first)

Run the diagnostic script (see below) in your **tenant** DB (same DB as item search):

- Confirm `pg_trgm` is enabled.
- Confirm `idx_item_branch_snapshot_search_text_gin` exists on `item_branch_snapshot`.
- Run `EXPLAIN (ANALYZE, BUFFERS)` for the search query (with your real `company_id`, `branch_id`, and a sample `q`).  
  You want to see **Index Scan** or **Bitmap Index Scan** on the GIN (and optionally index usage on `(company_id, branch_id)`), **not** “Seq Scan” on `item_branch_snapshot`.

### 8.2 If the GIN index is missing

- Enable extension: `CREATE EXTENSION IF NOT EXISTS pg_trgm;`
- Create index (same as in 046/049):

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_item_branch_snapshot_search_text_gin
  ON item_branch_snapshot USING gin(search_text gin_trgm_ops);
```

Re-run `EXPLAIN (ANALYZE, BUFFERS)`; the plan should use the GIN and latency should drop sharply (often to well under 100ms for typical data sizes).

### 8.3 Optional: composite index for (company_id, branch_id, search_text)

If the planner still does not combine the branch filter and the GIN well, you can add a composite index so the branch filter is very cheap:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_item_branch_snapshot_company_branch_search_gin
  ON item_branch_snapshot USING gin((company_id, branch_id), search_text gin_trgm_ops);
```

Postgres does not support a single GIN that is “(company_id, branch_id) btree + search_text trigram” in one; in practice, having both:

- `(company_id, branch_id)` B-tree, and  
- GIN on `search_text`  

and letting the planner do a BitmapAnd is usually enough. Add the composite GIN only if you see the plan still doing heavy work on the branch filter.

### 8.4 Reduce work: avoid the Item join (optional)

To save the join to `items` and a bit of latency, you can denormalize the four columns onto `item_branch_snapshot` and backfill them from `items`. Then the search query can read everything from `item_branch_snapshot` only. This is a schema/backfill change; do it only if you still need to squeeze after fixing the GIN.

### 8.5 Use Server-Timing to confirm

Response header: `Server-Timing: item_branch_snapshot;dur=<ms>, ...`  
Check that after adding/fixing the GIN index, `item_branch_snapshot;dur=` drops to well under 100ms. The rest of the ~1s (if any) is auth/connection; that’s separate from the search query.

---

## 9. Summary

| Question | Answer |
|----------|--------|
| Where is the handler? | `app/api/items.py` → `ItemSearchService.search()` in `app/services/item_search_service.py` |
| Which table is searched? | `item_branch_snapshot` (filter: `company_id`, `branch_id`, `search_text ILIKE '%term%'`) |
| Which SQL pattern? | `ILIKE '%term%'` on `search_text` |
| Full-text search? | No; partial match via trigram GIN only |
| Indexes intended? | B-tree `(company_id, branch_id)`; GIN on `search_text` (pg_trgm) |
| Joins? | One: `items` by PK for 4 columns only |
| Does `include_pricing=true` add queries? | No |
| RLS? | No extra RLS in code; if RLS is on in DB, it runs but is not the main cost |
| Most likely cause of ~1s? | Sequential scan on `item_branch_snapshot` because GIN/trigram is missing or unused |
| First fix to try | Ensure `pg_trgm` and `idx_item_branch_snapshot_search_text_gin` exist; run EXPLAIN ANALYZE and re-measure |

After the GIN index is in place and used, item search should be able to reach the &lt;100ms goal for typical data sizes.
