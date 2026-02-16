# Schema Analysis & Search Speed Diagnostic

## Executive Summary

The 2.7s search delay persists likely because:
1. **Migration 024 may not have run** on your tenant DB (no GIN index on `items.name`, possibly no `item_branch_search_snapshot` UNIQUE)
2. **Missing indexes** on the live Supabase DB
3. **Snapshot tables need UNIQUE constraints** for ON CONFLICT to work; schema dump may not show them

---

## 1. Schema Issues (Duplicates, Confusion, Incomplete)

### 1.1 Duplicate / Overlapping Logic

| Issue | Tables | Description |
|-------|--------|-------------|
| **Two payment tables** | `payments` + `invoice_payments` | Both link to `sales_invoices`. `payments` appears legacy (payment_no, payment_date); `invoice_payments` is newer (payment_mode, amount, paid_by). Clear for_reimport deletes both. Consider deprecating `payments` if fully replaced. |
| **Snapshot vs source** | `inventory_balances` vs `inventory_ledger` | Intentional: `inventory_balances` is precomputed from ledger. Not a bug. |
| **Snapshot vs source** | `item_branch_purchase_snapshot` vs `purchase_invoice_items` | Intentional: snapshot avoids slow joins for search. |
| **Snapshot vs source** | `item_branch_search_snapshot` vs PO/Sales/OrderBook | Intentional: consolidates last_order_date, last_sale_date, etc. |

### 1.2 Incomplete / Missing from Schema Dump

Your Supabase schema dump does **not** show:
- **UNIQUE(item_id, branch_id)** on `inventory_balances` – migration 023 adds it; required for ON CONFLICT
- **UNIQUE(item_id, branch_id)** on `item_branch_purchase_snapshot` – migration 023 adds it
- **UNIQUE(item_id, branch_id)** on `item_branch_search_snapshot` – migration 024 adds it
- **idx_items_name_trgm** – GIN index on `items.name` for ILIKE; migration 024 adds it
- **idx_inventory_balances_***, **idx_item_branch_purchase_***, **idx_item_branch_search_*** – added by migrations

If these are missing on your tenant DB, migrations 023/024 may not have been applied.

### 1.3 Table Structure That Helps Search

| Table | Purpose | Speed impact |
|-------|---------|--------------|
| `inventory_balances` | Current stock per (item_id, branch_id) | O(1) lookup vs SUM over ledger |
| `item_branch_purchase_snapshot` | Last purchase price/date/supplier | O(1) vs window over purchase_invoice_items |
| `item_branch_search_snapshot` | Last order/sale/order_book dates | O(1) vs joins to PO, Sales, OrderBook |
| **items** | Base item data | Needs GIN/trgm index for fast ILIKE on name |

---

## 2. Diagnostic Queries (Run on Supabase SQL Editor)

Run these against your **tenant** database (Pharmasight Meds Ltd) to verify:

### 2.1 Check applied migrations
```sql
SELECT version, applied_at FROM schema_migrations ORDER BY version;
```
Expected: `023_search_snapshot_tables` and `024_item_branch_search_snapshot`.

### 2.2 Check UNIQUE constraints on snapshot tables
```sql
SELECT conname, conrelid::regclass, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid IN (
  'inventory_balances'::regclass,
  'item_branch_purchase_snapshot'::regclass,
  'item_branch_search_snapshot'::regclass
)
AND contype = 'u';
```
Expected: one UNIQUE constraint per table on (item_id, branch_id).

### 2.3 Check indexes on items (for ILIKE search)
```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'items'
AND indexname LIKE 'idx_%';
```
Expected: `idx_items_name_trgm` (GIN) for fast ILIKE.

### 2.4 Check snapshot table indexes
```sql
SELECT tablename, indexname
FROM pg_indexes
WHERE tablename IN ('inventory_balances', 'item_branch_purchase_snapshot', 'item_branch_search_snapshot')
ORDER BY tablename;
```
Expected: idx_*_item_branch, idx_*_company, idx_*_branch on each.

### 2.5 Check pg_trgm extension
```sql
SELECT * FROM pg_extension WHERE extname = 'pg_trgm';
```
Expected: one row. Needed for GIN trigram index.

---

## 3. If Migrations 023/024 Have Not Run

1. Restart the backend server – migrations run on startup for all tenants.
2. Or run migrations manually via the migration service.
3. Verify `schema_migrations` includes `023_search_snapshot_tables` and `024_item_branch_search_snapshot`.

---

## 4. If Indexes Exist but Search Is Still Slow

Possible causes:
- **CanonicalPricingService fallback** – items without `item_branch_purchase_snapshot` rows still hit `inventory_ledger`. Migration 024 backfills from OPENING_BALANCE.
- **Network/connection** – Supabase connection latency.
- **Query plan** – run `EXPLAIN (ANALYZE, BUFFERS)` on the search query to find bottlenecks.

---

## 5. Schema Consolidation Opportunities (Future)

- **Merge snapshot tables** – One `item_branch_snapshot` with current_stock + last_purchase_* + last_order_date + last_sale_date, etc. Fewer joins, one write surface.
- **Deprecate `payments`** – If `invoice_payments` fully replaces it.
- **item_units** – If present, ensure it’s not redundant with 3-tier unit fields on items.
