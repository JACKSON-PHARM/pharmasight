# Search Snapshot Implementation Plan

**Objective:** Reduce search latency from ~3.2s to <300ms by introducing precomputed snapshot tables.

**Strategy:**
1. `inventory_balances` table (item_id, branch_id, current_stock) — updated on every ledger write
2. `item_branch_purchase_snapshot` table (item_id, branch_id, last_purchase_price, last_purchase_date, last_supplier_id) — updated on every finalised purchase
3. Optional: `items.last_order_date` — updated when purchase orders are created (company-wide)

---

## 1. Write Points That Modify Stock or Purchase History

| # | Location | Operation | Transaction Type | Reference Type |
|---|----------|-----------|------------------|----------------|
| 1 | `pharmasight/backend/app/api/purchases.py` | `create_grn` (lines 74–220) | PURCHASE | grn |
| 2 | `pharmasight/backend/app/api/purchases.py` | `batch_supplier_invoice` (lines 604–840) | PURCHASE | purchase_invoice |
| 3 | `pharmasight/backend/app/api/sales.py` | `batch_invoice` (lines 704–775) | SALE | sales_invoice |
| 4 | `pharmasight/backend/app/api/quotations.py` | `convert_to_invoice` (lines 405–520) | SALE | sales_invoice |
| 5 | `pharmasight/backend/app/api/items.py` | `adjust_stock` (lines 956–1020) | ADJUSTMENT | MANUAL_ADJUSTMENT |
| 6 | `pharmasight/backend/app/api/stock_take.py` | `complete_branch_stock_take` (lines 1695–1820) | ADJUSTMENT | STOCK_TAKE |
| 7 | `pharmasight/backend/app/services/excel_import_service.py` | `_create_opening_balance` (lines 1185–1225) | OPENING_BALANCE | OPENING_BALANCE |
| 8 | `pharmasight/backend/app/services/excel_import_service.py` | `_process_batch_bulk` (line 1522) | OPENING_BALANCE | OPENING_BALANCE |

**Purchase snapshot updates:** Only #1 (GRN) and #2 (batch_supplier_invoice) — both are PURCHASE transactions.

---

## 2. New Tables and Columns

### 2.1 `inventory_balances`

```sql
CREATE TABLE inventory_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    current_stock NUMERIC(20, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX idx_inventory_balances_branch ON inventory_balances(branch_id);
CREATE INDEX idx_inventory_balances_item_branch ON inventory_balances(item_id, branch_id);
CREATE INDEX idx_inventory_balances_company ON inventory_balances(company_id);
```

### 2.2 `item_branch_purchase_snapshot`

```sql
CREATE TABLE item_branch_purchase_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    last_purchase_price NUMERIC(20, 4),
    last_purchase_date TIMESTAMPTZ,
    last_supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX idx_item_branch_purchase_item_branch ON item_branch_purchase_snapshot(item_id, branch_id);
CREATE INDEX idx_item_branch_purchase_company ON item_branch_purchase_snapshot(company_id);
```

### 2.3 Optional: `items` precomputed columns (company-wide fallback)

```sql
ALTER TABLE items ADD COLUMN IF NOT EXISTS last_purchase_price NUMERIC(20, 4);
ALTER TABLE items ADD COLUMN IF NOT EXISTS last_purchase_date TIMESTAMPTZ;
ALTER TABLE items ADD COLUMN IF NOT EXISTS last_supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL;
```

Search uses branch_id, so `item_branch_purchase_snapshot` is primary. Items columns are optional for non-branch contexts.

---

## 3. Migration SQL

**File:** `pharmasight/database/migrations/023_search_snapshot_tables.sql`

```sql
-- Migration 023: Search snapshot tables for <300ms search latency
-- Rollback: See rollback section at end of this document

-- 1. inventory_balances
CREATE TABLE IF NOT EXISTS inventory_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    current_stock NUMERIC(20, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_balances_branch ON inventory_balances(branch_id);
CREATE INDEX IF NOT EXISTS idx_inventory_balances_item_branch ON inventory_balances(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_inventory_balances_company ON inventory_balances(company_id);

-- 2. item_branch_purchase_snapshot
CREATE TABLE IF NOT EXISTS item_branch_purchase_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    last_purchase_price NUMERIC(20, 4),
    last_purchase_date TIMESTAMPTZ,
    last_supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_item_branch_purchase_item_branch ON item_branch_purchase_snapshot(item_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_item_branch_purchase_company ON item_branch_purchase_snapshot(company_id);

-- 3. Backfill inventory_balances from ledger
INSERT INTO inventory_balances (company_id, branch_id, item_id, current_stock, updated_at)
SELECT 
    company_id,
    branch_id,
    item_id,
    COALESCE(SUM(quantity_delta), 0),
    NOW()
FROM inventory_ledger
GROUP BY company_id, branch_id, item_id
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    current_stock = EXCLUDED.current_stock,
    updated_at = NOW();

-- 4. Backfill item_branch_purchase_snapshot from purchase_invoice_items
-- (Last purchase per item per branch from batched invoices)
WITH last_purchases AS (
    SELECT DISTINCT ON (pi_item.item_id, pi.branch_id)
        pi.company_id,
        pi.branch_id,
        pi_item.item_id,
        pi_item.unit_cost_exclusive AS last_purchase_price,
        pi.created_at AS last_purchase_date,
        pi.supplier_id AS last_supplier_id
    FROM purchase_invoice_items pi_item
    JOIN purchase_invoices pi ON pi_item.purchase_invoice_id = pi.id
    WHERE pi.status = 'BATCHED'
    ORDER BY pi_item.item_id, pi.branch_id, pi.created_at DESC
)
INSERT INTO item_branch_purchase_snapshot (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
SELECT company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, NOW()
FROM last_purchases
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    last_purchase_price = EXCLUDED.last_purchase_price,
    last_purchase_date = EXCLUDED.last_purchase_date,
    last_supplier_id = EXCLUDED.last_supplier_id,
    updated_at = NOW();

-- Also backfill from GRNs (if GRN predates invoice batching in some tenants)
WITH last_grn AS (
    SELECT DISTINCT ON (gi.item_id, g.branch_id)
        g.company_id,
        g.branch_id,
        gi.item_id,
        (gi.unit_cost / NULLIF(
            (SELECT pack_size FROM items WHERE id = gi.item_id) * 
            COALESCE((SELECT wholesale_units_per_supplier FROM items WHERE id = gi.item_id), 1), 1
        ))::NUMERIC(20,4) AS last_purchase_price,
        g.date_received::TIMESTAMPTZ AS last_purchase_date,
        g.supplier_id AS last_supplier_id
    FROM grn_items gi
    JOIN grns g ON gi.grn_id = g.id
    ORDER BY gi.item_id, g.branch_id, g.date_received DESC
)
INSERT INTO item_branch_purchase_snapshot (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
SELECT company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, NOW()
FROM last_grn
ON CONFLICT (item_id, branch_id) DO UPDATE SET
    last_purchase_price = COALESCE(item_branch_purchase_snapshot.last_purchase_price, EXCLUDED.last_purchase_price),
    last_purchase_date = GREATEST(COALESCE(item_branch_purchase_snapshot.last_purchase_date, '1970-01-01'), COALESCE(EXCLUDED.last_purchase_date, '1970-01-01')),
    last_supplier_id = COALESCE(item_branch_purchase_snapshot.last_supplier_id, EXCLUDED.last_supplier_id),
    updated_at = NOW();
```

---

## 4. Snapshot Update Helper Service

**File:** `pharmasight/backend/app/services/snapshot_service.py` (new)

```python
"""
Snapshot service: maintains inventory_balances and item_branch_purchase_snapshot
in sync with inventory_ledger. Called from every write point in the same transaction.
"""
from decimal import Decimal
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models import InventoryLedger  # for reference only; use raw SQL or ORM

class SnapshotService:
    @staticmethod
    def upsert_inventory_balance(db: Session, company_id: UUID, branch_id: UUID, item_id: UUID, quantity_delta: Decimal):
        """Increment/decrement current_stock. Call after every ledger INSERT."""
        db.execute(text("""
            INSERT INTO inventory_balances (company_id, branch_id, item_id, current_stock, updated_at)
            VALUES (:company_id, :branch_id, :item_id, :qty, NOW())
            ON CONFLICT (item_id, branch_id) DO UPDATE SET
                current_stock = inventory_balances.current_stock + :qty,
                updated_at = NOW()
        """), {"company_id": company_id, "branch_id": branch_id, "item_id": item_id, "qty": float(quantity_delta)})

    @staticmethod
    def upsert_inventory_balance_delta(db: Session, company_id: UUID, branch_id: UUID, item_id: UUID, old_qty: Decimal, new_qty: Decimal):
        """For opening balance UPDATE: apply delta = new - old."""
        SnapshotService.upsert_inventory_balance(db, company_id, branch_id, item_id, new_qty - old_qty)

    @staticmethod
    def upsert_purchase_snapshot(db: Session, company_id: UUID, branch_id: UUID, item_id: UUID,
                                 last_purchase_price: Decimal, last_purchase_date, last_supplier_id: UUID):
        """Set last purchase for (item, branch). Call after PURCHASE ledger write."""
        db.execute(text("""
            INSERT INTO item_branch_purchase_snapshot (company_id, branch_id, item_id, last_purchase_price, last_purchase_date, last_supplier_id, updated_at)
            VALUES (:company_id, :branch_id, :item_id, :price, :dt, :supplier_id, NOW())
            ON CONFLICT (item_id, branch_id) DO UPDATE SET
                last_purchase_price = EXCLUDED.last_purchase_price,
                last_purchase_date = EXCLUDED.last_purchase_date,
                last_supplier_id = EXCLUDED.last_supplier_id,
                updated_at = NOW()
        """), {"company_id": company_id, "branch_id": branch_id, "item_id": item_id,
               "price": float(last_purchase_price) if last_purchase_price else None,
               "dt": last_purchase_date, "supplier_id": last_supplier_id})
```

---

## 5. Write Point Modifications

### 5.1 purchases.py — create_grn

**Before:** After `db.add(ledger_entry)` and before `db.commit()`, no snapshot update.

**After:** After each ledger entry is added, before `db.commit()`:

```python
# After: ledger_entries.append(ledger_entry)
# Add snapshot updates for each ledger entry (same transaction)
from app.services.snapshot_service import SnapshotService

for entry in ledger_entries:
    db.add(entry)
db.flush()

for entry in ledger_entries:
    SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)
    SnapshotService.upsert_purchase_snapshot(
        db, entry.company_id, entry.branch_id, entry.item_id,
        entry.unit_cost, entry.created_at or datetime.utcnow(), grn.supplier_id
    )
# Then db.commit()
```

**Location:** `pharmasight/backend/app/api/purchases.py` lines 219–225 (after `for entry in ledger_entries: db.add(entry)`).

### 5.2 purchases.py — batch_supplier_invoice

**Before:** `for entry in ledger_entries: db.add(entry)` then `invoice.status = "BATCHED"` then `db.commit()`.

**After:** After `db.add(entry)` for all entries:

```python
for entry in ledger_entries:
    db.add(entry)
db.flush()

for entry in ledger_entries:
    SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)

# Update purchase snapshot per item (last in batch wins for that item)
seen_items = set()
for inv_item in reversed(invoice.items):  # Reverse so first occurrence = last in batch order
    if inv_item.item_id not in seen_items:
        seen_items.add(inv_item.item_id)
        # Get unit_cost per base from ledger entries for this item
        unit_cost_base = next((e.unit_cost for e in ledger_entries if e.item_id == inv_item.item_id), inv_item.unit_cost_exclusive)
        SnapshotService.upsert_purchase_snapshot(
            db, invoice.company_id, invoice.branch_id, inv_item.item_id,
            unit_cost_base, invoice.created_at, invoice.supplier_id
        )

invoice.status = "BATCHED"
db.commit()
```

**Location:** `pharmasight/backend/app/api/purchases.py` lines 821–826.

### 5.3 sales.py — batch_invoice

**After** `db.add(entry)` for each ledger entry:

```python
for entry in ledger_entries:
    db.add(entry)
    SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)
```

**Location:** `pharmasight/backend/app/api/sales.py` lines 761–763.

### 5.4 quotations.py — convert_to_invoice

**After** each `ledger_entries.append(ledger_entry)` and before commit:

```python
for entry in ledger_entries:
    db.add(entry)
    SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)
```

**Location:** `pharmasight/backend/app/api/quotations.py` after building `ledger_entries`, before `db.add(db_invoice)`.

### 5.5 items.py — adjust_stock

**After** `db.add(ledger_entry)`:

```python
db.add(ledger_entry)
SnapshotService.upsert_inventory_balance(db, item.company_id, body.branch_id, item_id, quantity_delta)
db.commit()
```

**Location:** `pharmasight/backend/app/api/items.py` lines 1007–1009.

### 5.6 stock_take.py — complete_branch_stock_take

**After** each `db.add(ledger_entry)` (variance and zero-out):

```python
db.add(ledger_entry)
SnapshotService.upsert_inventory_balance(db, branch.company_id, branch_id, count.item_id, variance)
# and
SnapshotService.upsert_inventory_balance(db, branch.company_id, branch_id, item_id, -Decimal(str(current_stock)))
```

**Location:** `pharmasight/backend/app/api/stock_take.py` lines 1755 and 1784.

### 5.7 excel_import_service.py — _create_opening_balance

**Case A — UPDATE existing:**
```python
if existing:
    old_qty = existing.quantity_delta
    existing.quantity_delta = quantity
    existing.unit_cost = unit_cost
    existing.total_cost = quantity * unit_cost
    SnapshotService.upsert_inventory_balance_delta(db, company_id, branch_id, item_id, old_qty, Decimal(str(quantity)))
```

**Case B — INSERT new:**
```python
else:
    ledger_entry = InventoryLedger(...)
    db.add(ledger_entry)
    SnapshotService.upsert_inventory_balance(db, company_id, branch_id, item_id, Decimal(str(quantity)))
```

**Location:** `pharmasight/backend/app/services/excel_import_service.py` lines 1201–1225.

### 5.8 excel_import_service.py — _process_batch_bulk (bulk opening balances)

**After** `db.bulk_insert_mappings(InventoryLedger, opening_balances)`:

```python
db.bulk_insert_mappings(InventoryLedger, opening_balances)
db.flush()
for ob in opening_balances:
    SnapshotService.upsert_inventory_balance(db, ob['company_id'], ob['branch_id'], ob['item_id'], Decimal(str(ob['quantity_delta'])))
```

**Location:** `pharmasight/backend/app/services/excel_import_service.py` lines 1518–1526.

---

## 6. Search Endpoint Refactor

**File:** `pharmasight/backend/app/api/items.py`

### Before (current): 
- Stock: `db.query(InventoryLedger.item_id, func.sum(...)).filter(...).group_by(...).all()`
- Last purchase: `SupplierInvoiceItem` + `SupplierInvoice` join with window function
- Cost: `CanonicalPricingService.get_best_available_cost_batch`
- Last order: `PurchaseOrderItem` + `PurchaseOrder` join

### After (Phase 2 — use snapshots):

```python
# 1. Base search query — UNCHANGED
items = base_query.order_by(...).limit(limit).all()
if not items:
    return []
item_ids = [item.id for item in items]

# 2. Stock: FROM inventory_balances instead of ledger aggregation
stock_map = {}
if branch_id:
    from app.models import InventoryBalance  # New model
    stock_rows = db.query(InventoryBalance.item_id, InventoryBalance.current_stock).filter(
        InventoryBalance.item_id.in_(item_ids),
        InventoryBalance.branch_id == branch_id
    ).all()
    stock_map = {r.item_id: float(r.current_stock or 0) for r in stock_rows}
    items = sorted(items, key=lambda r: (0 if stock_map.get(r.id, 0) > 0 else 1, ...))

# 3. Purchase snapshot: FROM item_branch_purchase_snapshot instead of SupplierInvoiceItem
purchase_price_map = {}
last_supplier_map = {}
if include_pricing and branch_id:
    from app.models import ItemBranchPurchaseSnapshot
    snap_rows = db.query(ItemBranchPurchaseSnapshot).filter(
        ItemBranchPurchaseSnapshot.item_id.in_(item_ids),
        ItemBranchPurchaseSnapshot.branch_id == branch_id
    ).all()
    for row in snap_rows:
        purchase_price_map[row.item_id] = float(row.last_purchase_price or 0)
        last_supplier_map[row.item_id] = ...  # Join suppliers for name, or add supplier_name to snapshot
    # Fallback default_supplier_id for items not in snapshot — keep existing logic

# 4. Last order date: Keep existing (PurchaseOrder) — lighter query, or add to snapshot later

# 5. Cost: Use purchase_price_map when available; else CanonicalPricingService.get_best_available_cost_batch (fallback)
```

Add SQLAlchemy models for `InventoryBalance` and `ItemBranchPurchaseSnapshot` in `pharmasight/backend/app/models/`.

---

## 7. Reconciliation Script

**File:** `pharmasight/backend/scripts/reconcile_snapshots.py`

```python
"""
Reconcile inventory_balances and item_branch_purchase_snapshot with ledger.
Run: python -m app.scripts.reconcile_snapshots
"""
import sys
sys.path.insert(0, ".")
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.database import get_db_url  # or env

def reconcile_inventory_balances(db):
    """Find (item_id, branch_id) where SUM(ledger) != inventory_balances.current_stock"""
    rows = db.execute(text("""
        SELECT l.item_id, l.branch_id, l.company_id,
               SUM(l.quantity_delta) AS ledger_stock,
               COALESCE(ib.current_stock, 0) AS snapshot_stock
        FROM inventory_ledger l
        LEFT JOIN inventory_balances ib ON ib.item_id = l.item_id AND ib.branch_id = l.branch_id
        GROUP BY l.item_id, l.branch_id, l.company_id, ib.current_stock
        HAVING ABS(COALESCE(SUM(l.quantity_delta), 0) - COALESCE(ib.current_stock, 0)) > 0.0001
    """)).fetchall()
    return rows

def reconcile_purchase_snapshot(db):
    """Optional: compare last purchase from ledger vs snapshot."""
    # Similar query
    pass

def main():
    engine = create_engine(get_db_url())
    Session = sessionmaker(bind=engine)
    db = Session()
    drift = reconcile_inventory_balances(db)
    if drift:
        print(f"DRIFT: {len(drift)} (item_id, branch_id) pairs")
        for r in drift[:20]:
            print(r)
    else:
        print("OK: inventory_balances in sync with ledger")
```

---

## 8. Frontend: Batch Stock Refresh

**File:** `pharmasight/frontend/js/components/TransactionItemsTable.js`

### Before:
```javascript
TransactionItemsTable.prototype.refreshStockForAllItems = async function() {
    for (let i = 0; i < this.items.length; i++) {
        const item = this.items[i];
        if (item?.item_id) {
            const results = await api.items.search(item.item_name || '', ...);
            // ...
        }
    }
};
```

### After:
Add backend endpoint `POST /api/items/stock-batch`:
```python
@router.post("/stock-batch", response_model=List[dict])
def get_stock_batch(
    item_ids: List[UUID],
    branch_id: UUID,
    company_id: UUID,
    db: Session = Depends(get_tenant_db)
):
    """Return {item_id, current_stock, stock_display} for given item_ids."""
    if not item_ids:
        return []
    rows = db.query(InventoryBalance).filter(
        InventoryBalance.item_id.in_(item_ids),
        InventoryBalance.branch_id == branch_id
    ).all()
    # Build stock_display from items + stock_map
    ...
```

Frontend:
```javascript
TransactionItemsTable.prototype.refreshStockForAllItems = async function() {
    const itemIds = this.items.filter(i => i?.item_id).map(i => i.item_id);
    if (itemIds.length === 0) return;
    const batch = await API.items.getStockBatch(itemIds, config.BRANCH_ID, config.COMPANY_ID);
    const byId = Object.fromEntries(batch.map(b => [b.item_id, b]));
    for (let i = 0; i < this.items.length; i++) {
        const item = this.items[i];
        const b = byId[item.item_id];
        if (b) {
            item.stock_display = b.stock_display;
            item.available_stock = b.current_stock;
            this.updateRowDisplay(i);
        }
    }
};
```

---

## 9. Phased Implementation

| Phase | Description | Verification |
|-------|-------------|--------------|
| **Phase 1** | Create tables, backfill, add SnapshotService | Run migration, run reconciliation script (should be clean after backfill) |
| **Phase 2** | Add snapshot updates to all write points | Create GRN, batch invoice, sale, adjust stock; run reconciliation |
| **Phase 3** | Refactor search to use snapshots | Measure latency: `q=amocure` before/after |
| **Phase 4** | Add batch stock endpoint + frontend | Refresh stock after batching; no per-row search calls |

---

## 10. Rollback

**Phase 1:**
```sql
DROP TABLE IF EXISTS item_branch_purchase_snapshot;
DROP TABLE IF EXISTS inventory_balances;
```

**Phase 2:** Revert commit that adds `SnapshotService` calls to write points.

**Phase 3:** Revert search endpoint to use ledger/supplier queries.

**Phase 4:** Revert batch endpoint and frontend `refreshStockForAllItems`.

---

## 11. Validation

- **After Phase 1:** `SELECT COUNT(*) FROM inventory_balances` ≈ distinct (item_id, branch_id) in ledger.
- **After Phase 2:** Run `reconcile_snapshots.py`; expect 0 drift.
- **After Phase 3:** Measure `GET /api/items/search?q=amocure&company_id=...&branch_id=...&include_pricing=true` — target <300ms.
- **After Phase 4:** Network tab: one `stock-batch` call instead of N search calls.
