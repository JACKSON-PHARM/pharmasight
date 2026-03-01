# Inventory Ledger Base-Unit Audit Report

**System:** PharmaSight multi-branch pharmacy ERP  
**Scope:** How inventory quantities are handled, converted, and stored in `inventory_ledger`  
**Rule under verification:** Ledger must store quantities **only in base units** (retail = smallest unit, e.g. tablet).  
**Audit type:** Analysis and reporting only — no code or schema changes.

---

## 1. CURRENT BEHAVIOR SUMMARY

**Is ledger base-unit enforced?** **PARTIAL**

- **Intent (post–migration 016):** `quantity_delta` is in **base (retail) units** everywhere.
- **Reality:** Most insert paths convert to base before insert; a few paths use manual conversion with `int()` truncation, one path has no conversion (Excel opening balance assumes column is in base), and one path updates an existing ledger row (violates append-only).

---

## 2. SCHEMA AND UNIT MODEL

### 2.1 `inventory_ledger` schema

- **quantity_delta:** Application model uses `Numeric(20, 4)`; migrations 015/016 set DB to NUMERIC. Root `schema.sql` still shows `INTEGER` — **schema file is out of date** with applied migrations.
- **unit_cost:** Cost per base unit at transaction time.
- **total_cost:** quantity_delta × unit_cost.
- **No** `transaction_unit` or `conversion_factor` column; unit is implied to be base only.

### 2.2 Three-tier unit model (items)

- **Level 1 (base/retail):** `retail_unit` (e.g. Tablet). Multiplier to base = **1**.
- **Level 2 (wholesale):** `wholesale_unit` (e.g. Strip). 1 wholesale = `pack_size` retail. Multiplier = **pack_size**.
- **Level 3 (supplier):** `supplier_unit` (e.g. Carton). 1 supplier = `pack_size * wholesale_units_per_supplier` retail.

Defined in:

- `items`: `pack_size`, `wholesale_units_per_supplier`, `retail_unit`, `wholesale_unit`, `supplier_unit`, `base_unit` (= wholesale for display).
- `item_units_helper.get_unit_multiplier_from_item()`: single place that returns multiplier to base (retail) for a unit name.

Conversion is centralized in:

- `InventoryService.convert_to_base_units(db, item_id, quantity, unit_name)` → `quantity * get_unit_multiplier_from_item(...)`.

**pack_size editability:** In `items.py` `update_item`, when the item has “real” transactions (any ledger except only OPENING_BALANCE), `pack_size`, `wholesale_units_per_supplier`, and `can_break_bulk` are **locked**. So conversion factors cannot be changed after meaningful transactions.

---

## 3. STEP 1 — INSERT PATHS INTO `inventory_ledger`

### 3.1 Sales (invoice batching)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/sales.py` |
| **UI unit** | User selects unit per line (`invoice_item.unit_name`) and quantity in that unit. |
| **Backend** | `quantity_base = InventoryService.convert_to_base_units(db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name)`. |
| **Ledger** | One or more rows: `quantity_delta = -qty` where `qty` is from FEFO allocation (already in base). |
| **Stored in base?** | **YES.** Conversion before allocation; allocation and ledger use base. |

### 3.2 Purchases — GRN (single line)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/purchases.py` (GRN create) |
| **UI unit** | `item_data.unit_name`, `item_data.quantity`. |
| **Backend** | `quantity_base = InventoryService.convert_to_base_units(db, item_data.item_id, float(item_data.quantity), item_data.unit_name)`. |
| **Ledger** | `quantity_delta=quantity_base`. |
| **Stored in base?** | **YES.** |

### 3.3 Purchases — GRN (multi-batch)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/purchases.py` (GRN create, `item_data.batches`) |
| **UI unit** | Batch quantities are in same unit as line (`item_data.unit_name`). |
| **Backend** | `quantity_base = int(float(batch.quantity) * float(multiplier))` — manual conversion, **no** `convert_to_base_units`. |
| **Ledger** | `quantity_delta=quantity_base`, `remaining_quantity=quantity_base`. |
| **Stored in base?** | **YES** (logic correct). **Risk:** `int()` truncates (e.g. 1.7 strips × 10 → 17.0 OK; 1.3 × 10 → 13.0; 0.33 × 10 → 3, losing 0.3). |

### 3.4 Purchases — Supplier invoice (batch)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/purchases.py` (purchase invoice batching) |
| **UI unit** | `invoice_item.unit_name`, batch quantities in same unit. |
| **Backend** | Empty batch list or no batch_data: `convert_to_base_units` used. With batch_data: `quantity_base = int(float(batch["quantity"]) * float(multiplier))`. |
| **Ledger** | `quantity_delta=quantity_base`, `remaining_quantity=quantity_base`. |
| **Stored in base?** | **YES**. **Risk:** Same `int()` truncation as GRN multi-batch. |

### 3.5 Manual stock adjustment (add/reduce)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/items.py` (e.g. adjust-stock endpoint) |
| **UI unit** | Body: `quantity`, `unit_name`, `direction`. |
| **Backend** | `base_quantity = InventoryService.convert_to_base_units(db, item_id, float(body.quantity), body.unit_name.strip())`, then `quantity_delta = base_quantity or -base_quantity`. |
| **Ledger** | `quantity_delta=quantity_delta`. |
| **Stored in base?** | **YES.** |

### 3.6 Stock take (variance and zero-out)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/stock_take.py` |
| **UI unit** | Count: `quantity_in_unit` + `unit_name` → converted to base; fallback `counted_quantity` assumed base. |
| **Backend** | `counted_quantity = InventoryService.convert_to_base_units(...)` or `int(count_data.get('counted_quantity', 0))`. Variance = counted_quantity − system_quantity (both base). On complete: `quantity_delta=variance` and zero-out `quantity_delta=-current_stock`. |
| **Ledger** | Variance and zero-out deltas in base. |
| **Stored in base?** | **YES.** **Note:** `StockTakeCount.counted_quantity` and `variance` are **Integer**; float from `convert_to_base_units` is coerced on save (possible rounding/truncation). |

### 3.7 Batch quantity correction (physical count)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/items.py` (batch quantity correction) |
| **UI unit** | `physical_count` — API expects **base units** (compared to `_batch_current_quantity` which is SUM(quantity_delta)). |
| **Backend** | `difference = physical - current_qty`, `quantity_delta = Decimal(str(difference))`. No conversion. |
| **Ledger** | `quantity_delta=difference`. |
| **Stored in base?** | **YES** if UI sends physical count in base. |

### 3.8 Branch transfer (send)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/branch_inventory.py` |
| **UI unit** | Line: `line.quantity`, `line.unit_name`. |
| **Backend** | `qty_base = InventoryService.convert_to_base_units(db, line.item_id, float(line.quantity), line.unit_name)`, then FEFO allocates by base. Ledger: `quantity_delta=-qty` from allocation (base). |
| **Ledger** | Negative delta in base. |
| **Stored in base?** | **YES.** |

### 3.9 Branch transfer (receive)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/branch_inventory.py` (confirm receipt) |
| **UI unit** | N/A — lines come from transfer, populated from FEFO at send. |
| **Backend** | `qty = Decimal(str(line.quantity))` from receipt line; that line was created at send with allocation quantity (base). |
| **Ledger** | `quantity_delta=qty` (positive). |
| **Stored in base?** | **YES** (quantity on receipt line is already base from send). |

### 3.10 Quotation → invoice (stock deduction)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/api/quotations.py` |
| **UI unit** | Quotation line: `q_item.quantity`, `q_item.unit_name`. |
| **Backend** | `quantity_base_units = InventoryService.convert_to_base_units(db, q_item.item_id, q_item.quantity, q_item.unit_name)`, FEFO allocation in base, then `quantity_delta=-allocation["quantity"]`. |
| **Ledger** | Negative delta in base. |
| **Stored in base?** | **YES.** |

### 3.11 Opening balance — Excel import (row-by-row)

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/services/excel_import_service.py` |
| **UI unit** | Column “Current Stock Quantity” — **no unit column**; documented as base/retail (e.g. tablets). |
| **Backend** | `stock_qty = _parse_quantity(stock_qty_raw)` → **int**; **no conversion**. `_create_opening_balance(..., quantity=stock_qty, ...)` → `quantity_delta=quantity`. |
| **Ledger** | `quantity_delta=quantity` (or **update** of existing row — see below). |
| **Stored in base?** | **Only if** user enters quantity in base (retail) units. No conversion; wrong unit in Excel → wrong ledger. |

### 3.12 Opening balance — Excel bulk

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/services/excel_import_service.py` (`_process_batch_bulk`) |
| **UI unit** | Same “Current Stock Quantity” column; no conversion. |
| **Backend** | `stock_qty = _parse_quantity(...)` (int), `opening_balances.append(..., 'quantity_delta': stock_qty, ...)`, then `bulk_insert_mappings(InventoryLedger, opening_balances)`. |
| **Ledger** | New rows only; quantity_delta = stock_qty. |
| **Stored in base?** | Same as row-by-row: **only if** Excel is in base units. |

### 3.13 Opening balance — update of existing row

| Aspect | Detail |
|--------|--------|
| **File** | `backend/app/services/excel_import_service.py` `_create_opening_balance` |
| **Behavior** | When opening balance already exists for (company, branch, item): `existing.quantity_delta = quantity` (and unit_cost/total_cost updated). |
| **Issue** | **Append-only is violated** (ledger row is updated, not appended). Quantity is still whatever was passed (assumed base in docs). |

---

## 4. STEP 2 — UNIT CONVERSION MODEL (summary)

- **Levels:** Base = retail (mult 1), wholesale (mult = pack_size), supplier (mult = pack_size × wholesale_units_per_supplier). Stored on `items`; no separate table.
- **pack_size:** On `items`; locked on update when item has real transactions.
- **Conversion:** Centralized in `InventoryService.convert_to_base_units` and `get_unit_multiplier_from_item`. Duplicated logic only where batch splits use `int(float(batch.quantity) * float(multiplier))` instead of calling `convert_to_base_units`.
- **Before insert:** In all paths except Excel opening balance and batch-split purchases, conversion is done before ledger insert. Batch-split purchases convert manually with `int()`.

---

## 5. STEP 3 — CORRUPTION RISKS

| Risk | Location | Severity |
|------|----------|----------|
| **Storing 1 strip as quantity_delta = 1** | If any path sent transaction unit to ledger without conversion: not found. All paths either use `convert_to_base_units` or (batch splits) multiply by multiplier. Risk is **truncation** in batch splits, not “1 strip = 1” in base. | Low (wrong quantity only when fractional in transaction unit). |
| **Mixed-unit storage** | No evidence; design and code assume base everywhere. | Low. |
| **Raw quantity from request without conversion** | Excel opening balance: raw column value → quantity_delta. No conversion; template/docs say “base/retail”. If user enters “2” meaning 2 cartons (200 base), ledger gets 2. | **HIGH** if template is misread or misused. |
| **Integer truncation before insert** | GRN and purchase invoice batch paths: `quantity_base = int(float(batch["quantity"]) * float(multiplier))`. Fractional base units truncated. | **MODERATE** (small systematic under-count on fractional entries). |
| **remaining_quantity INTEGER vs quantity_delta NUMERIC** | `remaining_quantity` is Integer; code sets it to same value as quantity_base (int or float). Float coerced to int → truncation. Balance logic uses SUM(quantity_delta), not remaining_quantity, so **stock balance is correct**; remaining_quantity is for display/tracking only. | Low for valuation; possible display inconsistency. |
| **Opening balance update (non–append-only)** | Excel re-import can **update** existing opening balance row instead of appending. | **MODERATE** (audit trail and append-only guarantee broken). |

---

## 6. STEP 4 — BATCH SPLITTING

- **Carton → strip split:** When multiple batches are entered (GRN or purchase invoice), each batch gets its own ledger row. `quantity_base` is computed per batch (with `int()` as above). No separate “split” that would store carton as 1; each row is in base.
- **parent_batch_id / split_sequence:** Set on new ledger rows (e.g. GRN/purchase batch index as split_sequence). Not used in balance or FEFO; balance is SUM(quantity_delta) per (item, branch) or per (item, branch, batch_number, expiry_date). So split metadata does not bypass base-unit semantics.
- **remaining_quantity:** Set to quantity_base at insert; not updated on subsequent sales/transfers. True balance is SUM(quantity_delta). So no bypass of base-unit enforcement from remaining_quantity.

---

## 7. STEP 5 — DOWNSTREAM QUERIES

- **Stock balance:** `InventoryService.get_current_stock` = `SUM(quantity_delta)` by item/branch. All callers treat result as **base (retail) units**. Correct if ledger is base.
- **Dashboard / list:** Items API uses same SUM(quantity_delta) as `current_stock`; frontend shows it with `base_unit` label. No division by pack_size for “current stock”; display assumes base.
- **Item movement report:** `build_item_movement_report` uses opening balance and running balance from SUM(quantity_delta) and row.quantity_delta; report assumes base. Correct.
- **Batch availability / FEFO:** `allocate_stock_fefo` and `allocate_stock_fefo_with_lock` aggregate SUM(quantity_delta) per batch; allocation quantities are in base. Correct.
- **Batch quantity correction:** `_batch_current_quantity` = SUM(quantity_delta) for batch; compared to physical_count (expected base). Correct.

No path was found that assumes transaction unit or divides by pack_size when reading quantity_delta for stock or reports.

---

## 8. EXACT FAILURE SCENARIOS

1. **Excel opening balance in wrong unit**  
   Item: 1 carton = 10 strips = 100 tablets. User puts “2” in “Current Stock Quantity” meaning 2 cartons. Ledger gets quantity_delta = 2. System and reports show 2 tablets. **Result:** 200 tablets physically present displayed as 2.

2. **Batch split truncation**  
   Purchase invoice: 1.5 strips (15 tablets), unit = Strip, pack_size = 10. Batch quantity 1.5, multiplier 10 → 15.0; `int(15.0)=15` → correct. If 1.25 strips: 12.5 → int 12 → 12 tablets stored; 0.5 tablet lost.

3. **Stock take count precision**  
   Count entered as 98.7 base (e.g. from conversion). Stored in Integer column as 98 or 99. Variance and thus ledger adjustment use the stored value; small rounding error in adjustment.

---

## 9. ARCHITECTURAL GAPS

1. **No DB constraint or column for unit** — Ledger does not store transaction_unit or conversion_factor; base-unit semantics are by convention and code only.
2. **Duplicate conversion in batch paths** — GRN and purchase invoice batch logic use `int(quantity * multiplier)` instead of `convert_to_base_units`, and truncate.
3. **Excel opening balance** — No conversion; assumes column is base. Template/docs must be strict; one mistaken column meaning corrupts stock.
4. **Opening balance update** — Single opening balance row is updated on re-import instead of appending; breaks append-only and clear audit trail.
5. **Schema drift** — Root `schema.sql` still has quantity_delta as INTEGER; applied migrations use NUMERIC(20,4).
6. **Integer columns for derived counts** — StockTakeCount.counted_quantity and variance are Integer; remaining_quantity is Integer; can cause truncation/rounding when values are computed as float.

---

## 10. RISK LEVEL

**Overall: MODERATE**

- **Why not LOW:** Excel opening balance has no conversion (wrong unit → large error); batch paths use `int()` truncation; opening balance update breaks append-only; integer columns can round.
- **Why not HIGH:** All “normal” transaction paths (sales, purchases single line, adjustments, transfers, stock take, quotation) convert to base before insert; downstream queries consistently assume base; no evidence of mixed-unit storage in practice.

---

## 11. SAFE MIGRATION / HARDENING OPTIONS

- **A) Enforce base unit strictly**
  - Use `InventoryService.convert_to_base_units` (or a shared helper) in **all** insert paths. Replace `int(batch.quantity * multiplier)` in GRN and purchase invoice batch logic with conversion then round/truncate explicitly if needed.
  - For Excel: either document “Current Stock Quantity = base only” very clearly and optionally add a “Unit” column and convert, or add a unit column and always convert to base before write.

- **B) Add transaction_unit column**
  - Store the unit in which the user transacted (e.g. “Strip”) and optionally quantity in that unit. Enables auditing and display; balance logic can remain on quantity_delta (base) or be derived.

- **C) Add conversion_factor column**
  - Store multiplier used at insert time (e.g. 10 for strips). Helps audit and reconciliation; balance can stay SUM(quantity_delta) if quantity_delta remains base.

- **D) DB constraint enforcement**
  - Cannot enforce “base unit only” purely by constraint without storing unit or factor. Could add a CHECK that quantity_delta is integer if business rules disallow fractional base (current model allows fractional). Prefer application-level enforcement and optional audit columns (B/C).

Recommended order: **A** (unify and document conversion, fix truncation and Excel assumption), then consider **B** or **C** for auditability; **D** only if integer-only base is a firm rule.

---

## 12. FILES REFERENCE

| Area | File(s) |
|------|---------|
| Ledger model | `backend/app/models/inventory.py` |
| Conversion | `backend/app/services/inventory_service.py` (convert_to_base_units), `backend/app/services/item_units_helper.py` (get_unit_multiplier_from_item) |
| Sales | `backend/app/api/sales.py` |
| Purchases (GRN + invoice) | `backend/app/api/purchases.py` |
| Adjustments | `backend/app/api/items.py` |
| Stock take | `backend/app/api/stock_take.py` |
| Transfers | `backend/app/api/branch_inventory.py` |
| Quotations | `backend/app/api/quotations.py` |
| Excel import | `backend/app/services/excel_import_service.py` |
| Reports | `backend/app/services/item_movement_report_service.py`, `backend/app/api/reports.py` |
| Schema / migrations | `database/schema.sql`, `database/migrations/015_*`, `016_*`, `add_batch_tracking_fields.sql` |

---

*End of audit report. No code or schema changes were made.*
