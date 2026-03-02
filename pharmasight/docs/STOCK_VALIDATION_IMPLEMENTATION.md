# Stock Entry Validation — Implementation Summary

## Overview

Centralized batch and expiry validation is implemented across all stock-increasing routes. The system rejects expired product (hard reject), enforces short-expiry rules per company config (OFF | WARN | STRICT), and propagates batch/expiry to ledger where applicable.

---

## Deliverables

### 1. Central validation layer

- **`app/services/stock_validation_service.py`**
  - `StockValidationResult` — Pydantic model (`valid`, `expired`, `short_expiry`, `days_remaining`, `message`)
  - `StockValidationError` — raised for expired product only
  - `validate_stock_entry(...)` — pure function, no DB; rules: track_expiry=False → valid; track_expiry=True → batch/expiry required, expiry &lt; today → raise, short-expiry → invalid unless override
  - `StockValidationConfig` — dataclass `(mode, min_expiry_days)`
  - `get_stock_validation_config(db, company_id)` — one query per request; keys: `stock_validation_mode`, `stock_validation_min_expiry_days` (default STRICT, 90)
  - `validate_stock_entry_with_config(config, ...)` — applies OFF (log only), WARN (allow short, reject expired), STRICT (use request override)

### 2. Config layer

- **Company settings** (existing `company_settings` table):
  - `stock_validation_mode`: `OFF` | `WARN` | `STRICT`
  - `stock_validation_min_expiry_days`: integer (default 90)
- Loaded once per request via `get_stock_validation_config(db, company_id)`. No per-line DB lookup.

### 3. Integrated routes

| Route | File | Change |
|-------|------|--------|
| Create Supplier Invoice | `api/purchases.py` | Preload items (one query); get config once; after existing batch presence check, run `_validate_batches_central` per line. |
| Add/Update Supplier Invoice Item | `api/purchases.py` | Get config; validate batches with central service. |
| Update Supplier Invoice | `api/purchases.py` | Preload items; get config; validate each item’s batches. |
| Batch Supplier Invoice | `api/purchases.py` | Config once; `body.short_expiry_override`; validate each line’s batch_data before creating ledger. |
| Create GRN | `api/purchases.py` | Preload items; get config; for track_expiry validate batches or legacy single batch. |
| Manual Adjust Stock | `api/items.py` | Get config; when direction=add and track_expiry, validate batch/expiry. |
| Batch Quantity Correction | `api/items.py` | When quantity_delta &gt; 0 and track_expiry, validate batch/expiry. |
| Excel Import (authoritative) | `services/excel_import_service.py` | New columns: `Opening_Batch_Number`, `Opening_Expiry_Date`. For track_expiry + opening stock: require and validate; fail row (or skip opening balance in bulk) with clear error. `_create_opening_balance` accepts optional `batch_number`, `expiry_date`. |
| Stock Take Complete | `api/stock_take.py` | Get config once; for variance &gt; 0 and track_expiry require count.batch_number and count.expiry_date; validate; set ledger `batch_number` and `expiry_date` from count. |

### 4. Tests

- **`backend/tests/test_stock_validation_service.py`** — 16 unit tests:
  - track_expiry=False, expired (raise), exact today (short_expiry), short expiry with/without override, exact threshold, missing/empty batch/expiry, config OFF/WARN/STRICT.

---

## Performance guardrails

- **No per-line DB for config**: Config is loaded once per request (e.g. one `CompanySetting` query per invoice/batch/GRN/import run).
- **No N+1 for items**: Supplier invoice create/update and GRN preload items with a single `Item.id.in_(...)` query.
- **No extra commits**: Validation is in-process; no additional transaction commits.
- **No change to FEFO/snapshot**: FEFO allocation and snapshot logic are unchanged.

---

## Breaking changes

- **None.** Existing validation (e.g. `_require_batch_and_expiry_for_track_expiry_item`) remains; central validation runs in addition. Response shapes and success paths are unchanged.
- **New behaviour (intended):**
  - Expired product is rejected (HTTP 400) on all integrated routes.
  - Short-expiry is rejected in STRICT mode unless `short_expiry_override=True` (batch endpoint) or equivalent.
  - Excel: track_expiry items with opening stock require `Opening_Batch_Number` and `Opening_Expiry_Date`; otherwise row fails or opening balance is skipped (with error message).
  - Stock take: completing with positive variance for track_expiry items requires batch number and expiry on the count; otherwise completion returns 400.

---

## Rollback plan

1. **Disable enforcement (no code revert):** Set company setting `stock_validation_mode` = `OFF` so validation is logged only and no rejections.
2. **Revert code (if needed):** Revert commits that added:
   - `stock_validation_service.py` and its imports/usages
   - New Excel columns and `_create_opening_balance` batch/expiry args
   - Stock take ledger `batch_number`/`expiry_date` and validation
   - `BatchSupplierInvoiceBody.short_expiry_override`
   No DB migrations were added; no schema rollback required.

---

## Configuration reference

| Setting key | Values | Default |
|-------------|--------|---------|
| `stock_validation_mode` | `OFF`, `WARN`, `STRICT` | `STRICT` |
| `stock_validation_min_expiry_days` | integer ≥ 0 | 90 |

- **OFF**: No enforcement; log only.
- **WARN**: Reject expired; allow short-expiry (result may have `short_expiry=True` for UI).
- **STRICT**: Reject expired; reject short-expiry unless override is sent.

---

*Implementation completed through Phase 7; all stock-increasing routes use the central validation layer with config and tests.*
