# PharmaSight Stock Entry Audit Report

**Date:** March 2, 2025  
**Scope:** All stock-increasing routes, schema, expiry behavior, risk identification, and refactor design  
**Status:** Analysis Only — No Code Modifications

---

## Executive Summary

This audit identifies **7 stock-increasing routes** across the PharmaSight ERP. Validation for batch and expiry is **inconsistent and incomplete**:

- **Supplier Invoice (GRN path)** and **Manual Adjustments** enforce batch+expiry for `track_expiry` items, but **none** reject expired products.
- **GRN (direct)**, **Excel Import**, **Stock Take Complete**, and **Branch Receipt** can add stock without batch/expiry validation.
- **short_expiry** logic does not exist anywhere in the codebase.
- There is **no centralized validation service**; logic is duplicated across `purchases.py` and `schemas/item.py`.

**Estimated Refactor Complexity:** **Medium–High**

---

## Phase 1 — Structural Audit: Stock-Increasing Routes

### Summary Table

| Route | File | Controller Path | Batch Required? | Expiry Required? | Expiry Validation? | Centralized? | Risk Level |
|-------|------|------------------|-----------------|------------------|-------------------|--------------|------------|
| GRN Create | purchases.py | POST /api/purchases/grn | No (optional) | No (optional) | None | No | **High** |
| Supplier Invoice Create | purchases.py | POST /api/purchases/invoice | Yes (track_expiry only) | Yes (track_expiry only) | None | No | **Medium** |
| Supplier Invoice Batch | purchases.py | POST /api/purchases/invoice/{id}/batch | Yes (track_expiry only) | Yes (track_expiry only) | None | No | **Medium** |
| Manual Adjust Stock | items.py | POST /api/items/{id}/adjust-stock | Yes (add only) | Yes (add only) | None | No | **Medium** |
| Branch Receipt Receive | branch_inventory.py | POST /api/branch-inventory/receipts/{id}/receive | N/A (inherited) | N/A (inherited) | None | No | **Low** |
| Stock Take Complete | stock_take.py | POST /api/stock-take/branch/{id}/complete | No | No | None | No | **High** |
| Excel Import (Opening Balance) | excel_import_service.py | POST /api/excel/import | No | No | None | No | **High** |
| Batch Quantity Correction | items.py | POST /api/items/{id}/corrections/batch-quantity-correction | Yes | Optional (track_expiry) | None | No | **Medium** |

### Detailed Findings

#### 1. GRN Create (`POST /api/purchases/grn`)

- **File:** `pharmasight/backend/app/api/purchases.py` (lines 85–274)
- **Service:** Inline logic; `InventoryService`, `SnapshotService`
- **Batch/Expiry:**
  - Supports `batches` array or legacy single `batch_number`/`expiry_date`
  - **No** enforcement for `track_expiry` items
  - Legacy path accepts `batch_number=None`, `expiry_date=None`
- **Expiry Validation:** None (expired or short-expiry not checked)
- **Logic Location:** Controller
- **Duplication:** Yes (differs from supplier invoice validation)

#### 2. Supplier Invoice (Create, Add Item, Update, Batch)

- **Files:** `purchases.py` — create (336), add item (465), update (608), batch (717)
- **Validation:** `_require_batch_and_expiry_for_track_expiry_item()` (lines 41–83)
  - For `track_expiry=True` items:
    - Requires at least one batch
    - Each batch: non-empty `batch_number`, non-null `expiry_date`
  - **Does not** reject expired or short-expiry dates
- **Logic Location:** Controller
- **Duplication:** Yes (same helper used in 5 places)

#### 3. Manual Adjust Stock (`POST /api/items/{id}/adjust-stock`)

- **File:** `pharmasight/backend/app/api/items.py` (lines 635–724)
- **Validation:** `AdjustStockRequest.validate_direction_and_batch_expiry()` in `schemas/item.py` (259–268)
  - For `direction='add'`: batch_number and expiry_date required
  - **Does not** check expired or short-expiry
- **Logic Location:** Schema (Pydantic)
- **Duplication:** Different implementation from purchases

#### 4. Branch Receipt Receive (`POST /api/branch-inventory/receipts/{id}/receive`)

- **File:** `pharmasight/backend/app/api/branch_inventory.py` (lines 506–550)
- **Behavior:** Copies batch_number, expiry_date from `BranchReceiptLine` (populated by transfer completion)
- **Transfer completion:** Uses `allocate_stock_fefo_with_lock(..., exclude_expired=True)` — expired batches are excluded at source
- **Validation on receive:** None (trusts upstream transfer)
- **Risk:** Low if transfer logic is correct; no explicit receive-side validation

#### 5. Stock Take Complete (`POST /api/stock-take/branch/{id}/complete`)

- **File:** `pharmasight/backend/app/api/stock_take.py` (lines 1700–1869)
- **Behavior:** Creates `InventoryLedger` entries with `transaction_type='ADJUSTMENT'`, `reference_type='STOCK_TAKE'`
- **Batch/Expiry:** Ledger entries are created **without** `batch_number` or `expiry_date` (lines 1784–1796, 1815–1827)
- **Stock take counts** have `batch_number` and `expiry_date`, but completion logic does **not** pass them to ledger
- **Risk:** High — stock can increase without batch/expiry for track_expiry items

#### 6. Excel Import (Opening Balance)

- **File:** `pharmasight/backend/app/services/excel_import_service.py`
- **Method:** `_create_opening_balance()` (lines 1255–1305)
- **Behavior:** Creates `InventoryLedger` with `transaction_type='OPENING_BALANCE'`
- **Batch/Expiry:** No batch_number, no expiry_date passed to ledger
- **Risk:** High — track_expiry items can get stock without batch/expiry

#### 7. Batch Quantity Correction

- **File:** `pharmasight/backend/app/api/items.py` (lines 1079–1185)
- **Schema:** `BatchQuantityCorrectionRequest` — `expiry_date` optional
- **Behavior:** Can add stock (positive `quantity_delta`) with batch_number; expiry optional for track_expiry items
- **Validation:** None for expired/short-expiry
- **Risk:** Medium

---

## Phase 2 — Schema Audit

### inventory_ledger

| Column | Type | Nullable? | Constraints |
|--------|------|-----------|-------------|
| batch_number | VARCHAR(200) | Yes | None |
| expiry_date | DATE | Yes | None |

- **Expiry index:** `idx_inventory_ledger_expiry` on `expiry_date`
- **Batch index:** `idx_inventory_ledger_batch` on `(item_id, batch_number, expiry_date)`
- **Expiry storage:** Line-level (each ledger row)
- **DB constraints:** `quantity_delta != 0`; no NOT NULL on batch/expiry

### grn_items

| Column | Type | Nullable? |
|--------|------|-----------|
| batch_number | VARCHAR(200) | Yes |
| expiry_date | DATE | Yes |

No NOT NULL or CHECK constraints on batch/expiry.

### purchase_invoice_items

| Column | Type | Nullable? |
|--------|------|-----------|
| batch_data | TEXT (JSON) | Yes |

Batch distribution stored as JSON; no DB-level validation.

### branch_transfer_lines / branch_receipt_lines

- Both have `batch_number` and `expiry_date` (nullable)
- No NOT NULL or CHECK constraints

### stock_take_counts

- `batch_number`, `expiry_date` both nullable
- Completion logic does not propagate these to ledger

### Summary

- **Expiry nullable:** Yes (all relevant tables)
- **Batch nullable:** Yes
- **DB constraints:** None enforcing batch/expiry
- **Expiry index:** Yes on `inventory_ledger`
- **Expiry level:** Line-level (ledger rows, grn_items, transfer/receipt lines)

---

## Phase 3 — Expiry Behavior Mapping

### Search Results

| Term | Locations |
|------|-----------|
| expiry | inventory_service, inventory.py, purchases.py, schemas, models, stock_take |
| expiration | No direct matches |
| batch | Same as above; FEFO, batch_data, batch_number |
| validate | schemas/item.py, purchases.py, users.py, onboarding.py |
| short_expiry | **No matches** |

### Existing Logic

1. **`_require_batch_and_expiry_for_track_expiry_item()`** (purchases.py)
   - Checks presence of batches, batch_number, expiry_date for track_expiry items
   - No date validation (expired, short-expiry)

2. **`AdjustStockRequest.validate_direction_and_batch_expiry()`** (schemas/item.py)
   - Requires batch_number and expiry_date when direction=add
   - No date validation

3. **`allocate_stock_fefo` / `allocate_stock_fefo_with_lock`** (inventory_service.py)
   - `exclude_expired=True` filters `expiry_date IS NULL OR expiry_date >= today`
   - Used for sales and transfer-out; does not apply to stock-in routes

4. **`BatchDistribution`** (schemas/purchase.py)
   - `expiry_date: Optional[date]` — required only by business logic, not schema

### Inconsistencies

- GRN: No batch/expiry validation for track_expiry
- Supplier Invoice: Batch/expiry required for track_expiry only
- Adjust Stock: Always requires batch+expiry for add (not conditional on track_expiry)
- Excel Import: No batch/expiry
- Stock Take: No batch/expiry
- Batch corrections: Expiry optional

### Frontend-Only Validation

- No evidence of frontend-only expiry validation; reliance is on backend.
- Frontend may show “Manage Batches” but does not replace backend checks.

---

## Phase 4 — Risk Identification

### Routes That Can Silently Accept Expired Products

1. **GRN Create** — No expiry validation; expired dates accepted
2. **Supplier Invoice (create, add, update, batch)** — Presence checked only; expired dates accepted
3. **Manual Adjust Stock** — Presence checked only; expired dates accepted
4. **Excel Import** — No batch/expiry; track_expiry items can receive stock without dates
5. **Batch Quantity Correction** — No expiry validation
6. **Stock Take Complete** — No batch/expiry; not applicable to expiry but bypasses batch tracking

### Routes That Can Silently Accept Short-Expiry Products

- **All stock-in routes** — No `short_expiry` or minimum-days logic anywhere.

### Routes That Bypass Validation Service

- **All routes** — No shared validation service; each uses local logic or none.

### Performance Considerations

- `_require_batch_and_expiry_for_track_expiry_item` is pure (no DB)
- Item lookup for `track_expiry` requires DB; already done for other validations
- FEFO allocation uses `exclude_expired` filter — efficient index use
- No obvious N+1 or heavy joins in stock-in paths

---

## Phase 5 — Refactor Design Plan

### A. Central StockValidationService

**Requirements:**

- Pure function where possible (no DB per line)
- Inputs: `expiry_date`, `batch_number`, `track_expiry`, `min_expiry_days`, `override: bool`
- Output: Structured result `{valid: bool, expired: bool, short_expiry: bool, message: str}`
- Raise only for expired products (hard rule)
- Short-expiry: flag or require override (configurable)

**Proposed signature:**

```python
def validate_stock_entry(
    *,
    batch_number: Optional[str],
    expiry_date: Optional[date],
    track_expiry: bool,
    min_expiry_days: int = 90,
    override: bool = False,
    reference_date: Optional[date] = None,
) -> StockValidationResult:
    """
    Returns validation result. Raises StockValidationError only for expired products.
    Short-expiry returns warning/flag unless override=True.
    """
```

### B. Integration Strategy

1. **Introduce service** — Add `stock_validation_service.py` with no changes to existing routes.
2. **Feature flag** — Optional `STRICT_STOCK_VALIDATION` to gate new behavior.
3. **Gradual migration:**
   - Phase 1: GRN, Supplier Invoice, Adjust Stock
   - Phase 2: Stock Take, Excel Import
   - Phase 3: Batch corrections
4. **Backward compatibility:** Keep existing validation until new service is proven; use flag to switch.

### C. Performance Considerations

- No extra DB per line: pass `track_expiry` from already-loaded item.
- Config: load `min_expiry_days` once per request (or from company/branch settings).
- Validation before any inventory write.
- No new joins; validation is in-memory.

### D. Database Safety Plan

| Action | Recommendation |
|--------|----------------|
| NOT NULL on batch_number | Defer; migration phase after application validation is in place |
| NOT NULL on expiry_date | Same as above |
| CHECK (expiry_date >= today) | Do not add; would block historical and adjustment scenarios |
| Historical expired records | Audit first; many may exist; NOT NULL would fail |
| Migration order | 1) Application validation 2) Data cleanup 3) Optional NOT NULL in later migration |

### E. Testing Plan

| Test Case | Description |
|-----------|-------------|
| Expired product | Expiry &lt; today → reject |
| Short expiry | Expiry &lt; today + min_days → flag or reject (configurable) |
| Exact threshold | Expiry = today + min_days → accept |
| Override | Short-expiry with override=True → accept |
| Bulk invoice | Multi-line invoice; each line validated; no regression |
| Concurrent posting | Existing row lock retained; no new locks |

---

## Final Deliverables Summary

### Audit Report

- 7 stock-increasing routes identified
- Validation documented per route
- Schema and indexes documented

### Risk Summary

| Risk | Severity | Routes Affected |
|------|----------|-----------------|
| Expired products accepted | High | GRN, Supplier Invoice, Adjust Stock, Excel, Batch Correction |
| Short-expiry not flagged | Medium | All |
| Batch/expiry bypass | High | GRN, Excel, Stock Take |
| No centralized validation | Medium | All |

### Refactor Plan (Step-by-Step)

1. Create `StockValidationService` with `validate_stock_entry()`.
2. Add config: `min_expiry_days`, `reject_short_expiry`, `allow_override`.
3. Integrate into Supplier Invoice (create, add, update, batch).
4. Integrate into GRN Create.
5. Integrate into Manual Adjust Stock.
6. Add batch/expiry to Stock Take Complete ledger entries; integrate validation.
7. Add batch/expiry to Excel Import opening balance for track_expiry items; integrate validation.
8. Integrate into Batch Quantity Correction.
9. Add feature flag and rollout.
10. Plan optional DB constraints after data cleanup.

### Performance Analysis

- Validation adds negligible cost (in-memory, no extra DB).
- Config load: one lookup per request.
- No impact on FEFO allocation or snapshot refresh.

### Migration Strategy

- Backward compatible: existing behavior preserved until flag enabled.
- Gradual rollout by route.
- Data cleanup before any NOT NULL migrations.

### Test Strategy

- Unit tests for `StockValidationService`.
- Integration tests for each stock-in route.
- Regression tests for bulk and concurrent posting.

### Estimated Complexity

**Medium–High**

- Logic is spread across 5+ files.
- GRN and Excel Import need structural changes.
- Stock Take completion must pass batch/expiry from counts to ledger.
- Coordination with existing validation patterns required.

---

*End of Audit Report*
