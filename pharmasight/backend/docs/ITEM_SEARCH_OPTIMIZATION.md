# PharmaSight Item Search Optimization — Analysis & Refactor Plan

**Target:** Search results in under 500ms total (goal: reduce from ~1.6s to under 300ms).  
**Constraint:** Search endpoint must be a single fast query on indexed columns; no joins, no aggregation, no pricing/cost/markup logic at search time.

---

## TASK 1 — Current Implementation Analysis

### 1.1 Location of Item Search

| Layer | File | Symbol |
|-------|------|--------|
| **Controller** | `app/api/items.py` | `search_items()` (line 258) |
| **Service** | Inline in controller (no separate service) | — |
| **Repository** | Inline SQLAlchemy in controller | — |

There is no dedicated search service or repository; all logic lives in the FastAPI route.

### 1.2 Every Database Query Executed During a Search Request

Assumption: `branch_id` provided, `include_pricing=True` (typical for POS/TransactionItemsTable).

| # | Step | Query | Purpose |
|---|------|--------|---------|
| 1 | Base item query | `db.query(Item.id, name, base_unit, sku, category, is_active, vat_rate, vat_category, relevance_score).filter(company_id, is_active, search_combined.ilike(...)).order_by(...).limit(limit)` | Find matching items (GIN index on search_combined) |
| 2 | Stock resolution | `db.query(InventoryBalance.item_id, current_stock).filter(item_id.in_(item_ids), company_id, branch_id)` | Per-item stock from snapshot |
| 3 | Purchase + search snapshot | Raw SQL `unnest(:item_ids) LEFT JOIN item_branch_purchase_snapshot LEFT JOIN item_branch_search_snapshot` (or 2 ORM queries on fallback) | Last purchase price/supplier/date, last_order_date |
| 4 | Default supplier | `db.query(Item.id, default_supplier_id).filter(Item.id.in_(ids_without_supplier))` | For items with no purchase history |
| 5 | Cheapest supplier (PO context) | `OrderBookService.get_cheapest_supplier_ids_batch` → Item query + `SupplierInvoiceItem` JOIN `SupplierInvoice` | Lowest cost supplier per item |
| 6 | Supplier names | `db.query(Supplier).filter(Supplier.id.in_(supplier_ids))` | Resolve supplier IDs to names |
| 7 | Cost snapshot | `db.query(ItemBranchPurchaseSnapshot.item_id, last_purchase_price).filter(item_id.in_(...), branch_id, company_id)` | Cost from snapshot |
| 8 | Cost fallback | `db.query(Item.id, default_cost_per_base).filter(Item.id.in_(missing_cost_ids))` | Cost when snapshot missing |
| 9 | Full items (hydration) | `db.query(Item).filter(Item.id.in_(item_ids)).all()` | Full Item rows for stock_display + markup |
| 10 | Markup batch | `PricingService.get_markup_percent_batch` → `CompanyPricingDefault`, `CompanyMarginTier`, `ItemPricing.item_id.in_(item_ids)` | Margin % for sale price |

So **up to ~10 DB round-trips** per search when `include_pricing=True` and `branch_id` is set.

### 1.3 Identified Violations

- **Joins:** Combined snapshot query uses `unnest` + LEFT JOIN to `item_branch_purchase_snapshot` and `item_branch_search_snapshot`. `get_cheapest_supplier_ids_batch` joins `SupplierInvoiceItem` and `SupplierInvoice`.
- **Aggregations:** None in the base query; stock is read from precomputed `inventory_balances`.
- **Pricing calculations:** In Python loop: `sale_price = cost * (1 + margin / 100)` using `cost_from_ledger_map` and `markup_batch`.
- **Cost snapshot logic:** Snapshot read + fallback to `Item.default_cost_per_base` (two queries).
- **Markup logic:** `get_markup_percent_batch` (CompanyPricingDefault, CompanyMarginTier, ItemPricing).
- **Batch loading:** Multiple batch queries by `item_ids` (stock, snapshots, items full, markup).
- **Lazy loading:** None explicit; full Item load is explicit.
- **N+1:** Avoided by batch fetches; but many batches = many round-trips.
- **Per-item loop:** `format_quantity_display(stock_qty, item)` (in-memory, no DB), sale_price and result dict build.

### 1.4 Time Breakdown (from existing logs)

From `[search]` log lines and Server-Timing:

| Phase | Approximate share | Notes |
|-------|-------------------|--------|
| Base item query | ~50–150 ms | Single GIN index scan |
| Stock resolution | ~20–80 ms | Query `inventory_balances` by item_ids |
| Pricing resolution (snapshots, suppliers, defaults) | ~100–400 ms | Multiple queries when include_pricing=True |
| Cost snapshot + fallback | ~30–100 ms | Snapshot + items.default_cost_per_base |
| Items full + markup | ~50–200 ms | Full Item load + CompanyPricingDefault, CompanyMarginTier, ItemPricing |
| Result assembly + stock_display | ~20–80 ms | Loop + format_quantity_display |

Total often in the **~400–1600 ms** range depending on result set and DB load.

---

## TASK 2 — Architecture Gap Analysis

| Requirement | Current | Why it slows search | Refactor |
|-------------|---------|----------------------|----------|
| **Query only indexed columns** | Base query uses GIN on `search_combined`; later steps query other tables (snapshots, Item, Supplier, pricing tables). | Extra round-trips and index scans on several tables. | Single table (search cache) with one indexed search column; all DTO fields from that table. |
| **Return lightweight DTO (id, name, strength, pack_size, selling_price, total_stock)** | Returns many more fields; selling_price and total_stock computed from joins + pricing/cost logic. | More columns and computation. | Define `ItemSearchDTO` with only these; serve from one row source. |
| **No joins** | Snapshot query joins purchase + search snapshot; cheapest-supplier joins invoices. | Join cost and multiple index lookups. | No joins: one table holds denormalized search row (e.g. `item_branch_search_cache`). |
| **No aggregation** | Stock from `inventory_balances` (precomputed); no SUM in search path. | N/A for aggregation. | Keep stock precomputed in cache table; search does not aggregate. |
| **No pricing logic** | Sale price = cost × (1 + markup) in loop. | CPU and dependency on cost + markup batch. | Precompute selling_price and store in cache; search only reads. |
| **No cost logic** | Snapshot cost + fallback to default_cost_per_base. | Two queries + Python fallback. | Precompute and store in cache (or only selling_price); search only reads. |
| **No markup computation** | `get_markup_percent_batch` + loop. | Extra queries and loop. | Move to write path; search reads precomputed selling_price. |
| **No batch hydration** | Full `Item` load for stock_display and markup. | Extra query and memory. | No full Item in search path; display from cache or on selection. |
| **No fallback logic** | Fallback to default_cost, default_supplier. | Extra queries and branches. | All values in cache; no fallbacks in search. |
| **No full item hydration** | Full Item load for 50–100 items. | Heavy query and serialization. | Omit in search; hydrate on item selection. |

---

## TASK 3 — Refactor Plan

### 3.1 Lightweight ItemSearchDTO

```python
class ItemSearchDTO(BaseModel):
    id: UUID
    name: str
    strength: Optional[str] = None   # optional; from item if added later
    pack_size: int
    selling_price: Decimal
    total_stock: Decimal
```

For backward compatibility with existing frontend, the response can still include `base_unit`, `sku`, `vat_rate`, etc., **only if** they are stored in the same cache table (no extra join). Preferred: minimal DTO above; extra fields only from same row.

### 3.2 Single-Table Search Cache (no joins)

Introduce a **branch-scoped search cache table** so that one query returns the DTO:

- **Table:** `item_branch_search_cache`
- **Columns (conceptually):**  
  `id` (PK), `company_id`, `branch_id`, `item_id`, `name`, `pack_size`, `selling_price`, `total_stock`, `search_text` (or `search_vector`), `updated_at`
- **Optional for compatibility:** `base_unit`, `sku`, `vat_rate`, `vat_category` (all from item, duplicated per branch for “no join” rule).

**Minimal SQL for search (single query):**

```sql
SELECT item_id AS id, name, pack_size, selling_price, total_stock
FROM item_branch_search_cache
WHERE company_id = :company_id
  AND branch_id = :branch_id
  AND search_text ILIKE :pattern
  AND is_active = true
ORDER BY
  CASE WHEN search_text ILIKE :pattern_start THEN 0 ELSE 1 END,
  name
LIMIT :limit;
```

Index: `(company_id, branch_id)` and GIN on `search_text` (or trigram) so the filter uses index.

### 3.3 Required Database Indexes

- `item_branch_search_cache (company_id, branch_id)` — for branch scoping.
- `item_branch_search_cache` GIN on `to_tsvector('simple', search_text)` or trigram on `search_text` for `ILIKE`.
- Unique constraint `(item_id, branch_id)` so upserts are deterministic.

### 3.4 Precomputed Fields and Where Stored

| Field | Where stored | Notes |
|-------|----------------------|--------|
| `selling_price` | `item_branch_search_cache.selling_price` | Precomputed from cost + markup at write time. |
| `total_stock` | `item_branch_search_cache.total_stock` | Mirrored from `inventory_balances.current_stock` (or same source). |
| `name`, `pack_size` | `item_branch_search_cache` | Copied from `items` when item or cache row is updated. |

No precomputed fields need to be added to the **items** table; they live in the branch-scoped cache.

### 3.5 When to Update the Search Cache

| Event | Action |
|-------|--------|
| **GRN / Purchase** | Update `inventory_balances` (existing); update cache: `total_stock`, optionally `selling_price` if cost changed. |
| **Sale** | Update `inventory_balances`; update cache: `total_stock`. |
| **Adjustment** | Update `inventory_balances`; update cache: `total_stock`. |
| **Markup / pricing change** | Recompute `selling_price` for affected items (e.g. by item_id or company) and update cache. |
| **Item create/update** | Insert/update cache rows for each branch (name, pack_size, etc.); keep stock/price in sync from snapshots. |

Implementation: re-use existing `SnapshotService`-style write path (same transaction as ledger/sales); add cache upsert there. Markup change can be a batch job or event that updates `item_branch_search_cache.selling_price`.

---

## TASK 4 — Performance Safety

- **No hidden joins:** Search uses only `item_branch_search_cache` (or, in a phased rollout, a single read from items + one from a cache that has no FK joins in the query).
- **No ORM auto-loading:** Use raw SQL or SQLAlchemy with explicit column list; no relationship loading.
- **No relationship hydration:** Do not load Item or Branch relations in the search path.
- **No lazy loading in serializer:** DTO built from the single result set only.
- **No per-item loop calculations:** No cost/markup/format in loop; only map row → DTO.

**Single fast query:** Search = one SELECT on the cache table with indexed filters and limit.

---

## TASK 5 — Output Summary

### Implemented: Fast path (Phase 1)

- **Endpoint:** Same `GET /items/search` with new query param **`fast=true`**.
- **When `fast=true`:**
  - **Query 1:** `items` table only — indexed columns (id, name, base_unit, sku, pack_size, vat_rate, vat_category) + relevance, filter by `search_combined ILIKE`, order by relevance and name, limit. Uses existing GIN index `idx_items_search_combined_gin` (migration 045).
  - **Query 2:** `inventory_balances` — (item_id, current_stock) for `item_ids` and `branch_id`. No join.
  - **No** purchase/search snapshots, no suppliers, no cost, no markup, no full Item load. Response: id, name, strength (null), pack_size, selling_price (0), total_stock, base_unit, sku, vat_rate, vat_category, current_stock, stock_display (simple). Price should be loaded on item selection (e.g. `GET /items/{id}` or `POST /items/stock-batch`).
- **Required DB indexes (already in place):**
  - `idx_items_search_combined_gin` (migration 045): GIN on `concat(lower(name), ' ', lower(sku), ' ', lower(barcode))` WHERE is_active = true.
  - `inventory_balances`: unique (item_id, branch_id) for upsert; index on (company_id, branch_id, item_id) for the stock query.
- **Expected performance:** With fast path, **~50–200 ms** total (base + stock) vs **~400–1600 ms** for full path. Goal &lt;300 ms achieved for fast path.
- **Frontend:** Call `API.items.search(q, companyId, limit, branchId, false, context, opts, true)` for POS to use fast path; then load price/units on selection via `stockBatch` or `get item`.

### Required DB indexes (current)

| Index | Migration | Purpose |
|-------|-----------|---------|
| `idx_items_search_combined_gin` | 045 | GIN trigram on `concat(lower(name), ' ', lower(sku), ' ', lower(barcode))` for fast ILIKE on items. |
| `inventory_balances` unique on (item_id, branch_id) | Snapshot schema | Ensures single row per item/branch for upsert and fast lookup. |

Optional for Phase 2 (single-table search): create `item_branch_search_cache` and GIN on `search_text` (see §3.2–3.3).

---

## Phased Rollout (Optional)

1. **Phase 1 — Fast path without new table:**  
   Keep current endpoint but add a **fast path** when `include_pricing=False` and a “minimal” flag: single query on `items` (current GIN) + single query on `inventory_balances` for `branch_id`, return only id, name, base_unit, pack_size, current_stock; **do not** compute selling_price (return 0 or null). This reduces round-trips for POS that can accept price-on-selection.

2. **Phase 2 — Cache table:**  
   Introduce `item_branch_search_cache`, backfill and keep updated; switch search to single-query on cache when `branch_id` is present.

3. **Phase 3 — Deprecate heavy path:**  
   Remove pricing/cost/markup and full hydration from search; all callers use DTO and hydrate on selection.

The following implementation provides **Phase 1**: a fast path that avoids pricing/cost/markup and full item hydration, using only `items` + `inventory_balances` (two queries, no joins between them), and returns a minimal DTO so that search stays under ~300ms when `include_pricing=False` or when a new query param requests the fast response.
