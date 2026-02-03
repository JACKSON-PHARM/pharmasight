# Architectural Refactor: Deprecate item_units

## 1. All Places item_units / ItemUnit Is Referenced

### Backend – Excel import (refactor target)
| File | Usage |
|------|--------|
| `pharmasight/backend/app/services/excel_import_service.py` | Imports `ItemUnit`; `_process_item_units()`; `_process_excel_row_authoritative` calls it and deletes `ItemUnit` by item_id; `_process_excel_row_non_destructive` same; `_process_batch_bulk` deletes by replaceable_item_ids, fetches existing units, `_prepare_units_for_bulk`, bulk_insert `ItemUnit`, rollback path re-queries `ItemUnit`; `_prepare_units_for_bulk()` returns list of unit dicts for bulk insert. |

### Backend – Clear for reimport
| File | Usage |
|------|--------|
| `pharmasight/backend/app/services/clear_for_reimport_service.py` | Deletes from `item_units` where item_id IN (items for company). **Refactor:** Stop writing to item_units (leave table intact). |

### Backend – Items CRUD / API
| File | Usage |
|------|--------|
| `pharmasight/backend/app/api/items.py` | Queries `ItemUnit` by item_id; creates/updates `ItemUnit`; list/overview bulk-fetches `ItemUnit` by item_ids. **Scope:** Read paths should later use units from `items` (supplier_unit, wholesale_unit, retail_unit); leave item_units intact (no reads/writes per directive). |
| `pharmasight/backend/app/services/items_service.py` | Builds `ItemUnit` from 3-tier when `units` list is empty; create/update item_units. **Scope:** Same as above – future change to stop reading/writing item_units. |

### Backend – Transactions / inventory
| File | Usage |
|------|--------|
| `pharmasight/backend/app/api/quotations.py` | Validates line unit_name via `ItemUnit` (item_id + unit_name). **Future:** Validate against item.supplier_unit / wholesale_unit / retail_unit. |
| `pharmasight/backend/app/api/sales.py` | Imports `ItemUnit`. |
| `pharmasight/backend/app/api/inventory.py` | Fetches `ItemUnit` by item_id for unit breakdowns. **Future:** Use items table units. |
| `pharmasight/backend/app/api/purchases.py` | Validates line unit_name via `ItemUnit` (item_id + unit_name). **Future:** Validate against item units. |
| `pharmasight/backend/app/services/inventory_service.py` | Queries `ItemUnit` for unit list and for conversion. **Future:** Use items table + single conversion function. |
| `pharmasight/backend/app/services/order_book_service.py` | Imports `ItemUnit`. |
| `pharmasight/backend/app/services/pricing_service.py` | Queries `ItemUnit` for tier pricing conversion. **Future:** Use items table + conversion helper. |

### Models and schemas
| File | Usage |
|------|--------|
| `pharmasight/backend/app/models/item.py` | `ItemUnit` model; `Item.units` relationship. **Leave intact** (no schema change yet). |
| `pharmasight/backend/app/models/__init__.py` | Exports `ItemUnit`. |
| `pharmasight/backend/app/schemas/item.py` | `ItemUnitBase`, `ItemUnitCreate`, `ItemUnitUpdate`, `ItemUnitResponse`; ItemResponse.units. **Future:** API can stop returning units from item_units. |

### Frontend
| File | Usage |
|------|--------|
| `pharmasight/frontend/js/pages/items.js` | `viewItemUnits(itemId)` – UI to view units. **Future:** Read units from item master (supplier_unit, wholesale_unit, retail_unit). |
| `pharmasight/frontend/js/pages/inventory.js` | Same `viewItemUnits`. |

### Database / docs (no code change in this refactor)
| Location | Usage |
|----------|--------|
| `pharmasight/database/schema.sql`, `database/migrations/001_initial.sql` | CREATE TABLE item_units. **Do not execute schema changes yet.** |
| `pharmasight/database/cleanup_items_for_fresh_import.sql`, `wipe_data.sql`, `rebuild_schema.sql` | DELETE/DROP item_units. **Listed below as future schema changes.** |
| Various `.md` docs | Describe item_units; update later. |

---

## 2. Code Changes in ExcelImportService (Done in This Refactor)

- **Remove all item_units usage:** Drop `ItemUnit` import; remove `_process_item_units()`; remove all calls to it; remove all `db.query(ItemUnit).filter(...).delete(...)`; remove bulk fetch/insert of ItemUnit in `_process_batch_bulk`; remove `_prepare_units_for_bulk()` or make it return [] and do not insert.
- **Stop persisting prices to items:** In `_create_item_from_excel`, `_overwrite_item_from_excel`, `_create_item_dict_for_bulk`: do not set `default_cost`, `purchase_price_per_supplier_unit`, `wholesale_price_per_wholesale_unit`, `retail_price_per_retail_unit`. In `_update_item_from_excel` and `_process_item_pricing`: do not update those fields on Item. ItemPricing (markup) can remain for now but must not depend on item price columns.
- **Opening balance:** Create/update opening balance with `unit_cost` from Excel (purchase price), converted to cost per base (wholesale) unit via `wholesale_units_per_supplier`. New helper: `_cost_per_supplier_to_cost_per_base(purchase_per_supplier, wholesale_units_per_supplier)`. `_create_opening_balance(..., unit_cost_per_base)` accepts optional unit_cost; callers pass value derived from row.
- **Unit conversion helper:** Add module-level or static helpers: `convert_quantity_supplier_to_wholesale(qty, wholesale_units_per_supplier)`, `convert_quantity_wholesale_to_retail(qty, pack_size)` (supplier → wholesale → retail using wholesale_units_per_supplier and pack_size).

---

## 3. Ledger Opening Balance Creation Logic (Proposal)

- **When:** Per row in AUTHORITATIVE mode (and in bulk path), after item is created/updated.
- **Condition:** Only if item has no real transactions (existing logic).
- **Quantity:** From Excel “Current_Stock_Quantity” – interpreted as **base (wholesale) units** (current codebase: base = wholesale). No change to quantity semantics in this refactor unless explicitly stated elsewhere.
- **Unit cost:** From Excel “Purchase_Price_per_Supplier_Unit” (or equivalent column). Convert to cost per base (wholesale) unit:  
  `unit_cost_per_base = purchase_price_per_supplier_unit / wholesale_units_per_supplier`.  
  So one wholesale unit cost = (price per supplier unit) / (wholesale units per one supplier unit).
- **VAT context:** Ledger does not store VAT fields; VAT remains on item (vat_category, vat_rate, price_includes_vat). No change.
- **Idempotency:** If an OPENING_BALANCE row already exists for (company_id, branch_id, item_id), either skip or update that row’s quantity_delta and unit_cost (current implementation updates in place; keep that behavior).
- **Bulk path:** For each row, append to `opening_balances` with `unit_cost` = converted cost from row (using item’s wholesale_units_per_supplier), not `item.default_cost`.

---

## 4. Schema Changes (Do Not Execute Yet)

- **items table:** Remove columns from business logic first (this refactor). Later, from schema:
  - `default_cost`
  - `purchase_price_per_supplier_unit`
  - `wholesale_price_per_wholesale_unit`
  - `retail_price_per_retail_unit`
- **item_units table:** Leave physically intact. No reads, no writes from application. Later: drop table and remove ItemUnit model and any remaining references.
- **inventory_ledger:** No schema change. Already has unit_cost, quantity_delta, reference_type OPENING_BALANCE.

---

## 5. Safety Constraints Respected

- Import mode behavior (AUTHORITATIVE vs NON_DESTRUCTIVE) unchanged.
- Live transaction detection (`_get_items_with_real_transactions`) unchanged.
- No full data reset required.
- item_units table left intact; no reads/writes from Excel import or clear-for-reimport.
