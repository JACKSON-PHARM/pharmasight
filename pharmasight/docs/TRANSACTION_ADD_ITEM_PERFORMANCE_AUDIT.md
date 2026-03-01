# PharmaSight Transaction Add-Item Performance Audit

**Scope:** Backend add-item flows for Quotations, Sales Invoices, Supplier Invoices, and Purchase Orders.  
**Type:** Read-only performance audit (no code changes).

---

## 1. Per–Document-Type Structured Reports

### 1.1 Quotations

| # | Question | Finding |
|---|----------|--------|
| **1️⃣ Endpoint(s)** | `POST /quotations` (create with items), `POST /quotations/{id}/items` (add one item) | Create: `create_quotation`; Append: `add_quotation_item` |
| **2️⃣ DB queries (create)** | Document number (1) + **1 Item lookup per line** (N) + flush + 1 insert quotation + N insert items + commit + 1 refresh. No batch item load. | **~3 + 2N** (N = item count). **N+1:** one `Item` query per line in loop. |
| **2️⃣ DB queries (add item)** | 1 Quotation+items (selectinload) + duplicate check in memory + 1 Item + 1 insert line + flush + commit + **full `get_quotation(quotation_id)`** for response. | Add-item: **~2 + get_quotation**. get_quotation: 1 Quotation+items+item (selectinload) + **1 PricingService.get_item_cost per line** + 1 Company + 1 Branch + 1 User. So **N+1 cost lookups** in response. |
| **3️⃣ Totals** | Create: computed in loop (incremental). Add: **incremental** (header updated: `total_exclusive += line_total_exclusive`, etc.). | ✅ Incremental on add. |
| **4️⃣ Full document reload after insert** | Add item returns `get_quotation(quotation_id, ...)` → full document refetch with items + item relation. | ⚠️ **Yes.** Entire document re-fetched and enriched (margin/cost per line) for response. |
| **5️⃣ Heavy joins on add** | Add: load Quotation + items (selectinload). Response: get_quotation loads Quotation + items + Item (selectinload), then per-item cost (see 2). | ⚠️ **Heavy on response:** selectinload(Quotation.items).selectinload(QuotationItem.item) + **per-line cost query**. |
| **6️⃣ Tenant/company validation** | No explicit company_id validation from payload; RLS set once in `get_current_user` from `get_effective_company_id_for_user`. Create uses `quotation.company_id` from body. | Company from user's branch (DB); document company_id from payload on create (not re-validated against JWT/company). |
| **7️⃣ Session GUC (RLS)** | Set once in `get_current_user` via `SET LOCAL jwt.claims.company_id`. Single tenant db from `get_tenant_db`. | ✅ Once per request. |
| **8️⃣ Inventory/stock checks** | Create: **none** (quotations do not affect stock). Add item: **none**. Convert-to-invoice: `InventoryService.check_stock_availability` per line (and Item per line). | ✅ No stock check on add. Convert: N stock checks + N Item lookups. |
| **9️⃣ Single DB transaction** | Create: one `db.commit()`. Add: one `db.commit()` then call to get_quotation (new reads in same session). | ✅ Single transaction for the write; response reads in same session. |
| **🔟 Response payload** | Add: full `QuotationResponse` (header + all items with item_code, item_name, unit_display_short, margin, unit_cost_base, company/branch/user, logo). | ⚠️ **Large:** full document + enriched items (cost/margin per line). |

---

### 1.2 Sales Invoices

| # | Question | Finding |
|---|----------|--------|
| **1️⃣ Endpoint(s)** | `POST /sales/invoice` (create), `POST /sales/invoice/{invoice_id}/items` (add one item) | Create: `create_sales_invoice`; Append: `add_sales_invoice_item` |
| **2️⃣ DB queries (create)** | Invoice number (1) + **1 Item per line** + **InventoryService.check_stock_availability per line** (each: convert_to_base_units → Item+units, get_current_stock → SUM ledger) + optional **PricingService** (get_item_cost / get_min_margin / get_price_for_tier / get_item_cost again) + optional _user_has_sell_below_min_margin (Permission + UserBranchRole + RolePermission). Then 1 insert invoice + N items + commit + refresh. | **N+1:** Item per line; **N stock checks** (each 2–3 queries); **N pricing** when no unit_price (tier price + cost + possibly margin). |
| **2️⃣ DB queries (add item)** | 1 Invoice+items (selectinload) + 1 Item + **check_stock_availability** (convert_to_base + get_current_stock) + optional **PricingService.calculate_recommended_price** (get_price_for_tier, get_item_cost → get_stock_by_batch or ledger + Item + CanonicalPricingService) or **get_item_cost** + **get_min_margin_percent** + **_user_has_sell_below_min_margin** (3 queries) + insert line + flush + commit. Then **get_sales_invoice(invoice_id, db)** for response. | Add: **~4–8+** for one item (item, stock, pricing/margin, permission). **Response:** get_sales_invoice: 1 Invoice+items+item (selectinload) + **per line** PricingService.get_item_cost + **per line** InventoryLedger (sale_ledgers) + optionally ledger by batch_id + 1 Company + 1 Branch + 1 User. |
| **3️⃣ Totals** | Create: computed in loop (incremental). Add: **incremental** (total_exclusive += line_total_exclusive, etc.). | ✅ Incremental on add. |
| **4️⃣ Full document reload after insert** | Add item ends with `return get_sales_invoice(invoice_id, db)`. | ⚠️ **Yes.** Full document refetch + all items + per-item cost, batch_allocations, Company/Branch/User, logo. |
| **5️⃣ Heavy joins on add** | Add: Invoice + items. Response: Invoice + items + Item (selectinload); then **per item** get_item_cost (ledger/batch) and **per item** InventoryLedger filter (sale_ledgers). | ⚠️ **Heavy:** repeated ledger/cost and batch queries per line in get_sales_invoice. |
| **6️⃣ Tenant/company validation** | Same as quotations: RLS from get_current_user; create uses `invoice.company_id` from body. | No explicit company_id validation from payload against JWT. |
| **7️⃣ Session GUC** | Same: once in get_current_user. | ✅ Once per request. |
| **8️⃣ Inventory/stock checks** | Create: **check_stock_availability** per line (no allocation). Add: **check_stock_availability** for new line. | ⚠️ **Yes.** One stock check per add (convert_to_base + get_current_stock). |
| **9️⃣ Single DB transaction** | One commit for add; then get_sales_invoice runs in same session (same transaction context until response). | ✅ Single transaction for write; response in same session. |
| **🔟 Response payload** | Full SalesInvoiceResponse: header, all items (item_name, item_code, unit_display_short, unit_cost_base, batch_allocations, batch_number, expiry_date), company_name, branch_name, logo_url, created_by_username. | ⚠️ **Large:** full document + cost + batch details per line. |

**Note:** `add_sales_invoice_item` returns `get_sales_invoice(invoice_id, db)` with only two arguments. The `get_sales_invoice` signature expects `(invoice_id, current_user_and_db, tenant, db)`. Passing only `(invoice_id, db)` may cause incorrect defaults for tenant/current_user (e.g. tenant as Depends object) and is a potential bug.

---

### 1.3 Supplier Invoices

| # | Question | Finding |
|---|----------|--------|
| **1️⃣ Endpoint(s)** | `POST /purchases/invoice` (create), `POST /purchases/invoice/{invoice_id}/items` (add one item) | Create: `create_supplier_invoice`; Append: `add_supplier_invoice_item` |
| **2️⃣ DB queries (create)** | Invoice number (1) + **1 Item per line** + get_unit_multiplier_from_item (Item already loaded) + track_expiry validation (no extra query) + 1 insert invoice + N items + commit + refresh. | **~3 + N** (N Item lookups in loop). No stock or pricing on create. |
| **2️⃣ DB queries (add item)** | 1 Invoice+items (selectinload) + **_supplier_invoice_item_to_totals**: 1 Item + get_unit_multiplier (same Item) + insert line + flush + header update + commit + **db.refresh(invoice)** + **get_supplier_invoice(invoice_id, ...)**. get_supplier_invoice: 1 Invoice+items+item (selectinload) + 1 User (created_by). | Add: **~3** for write; response: 1 doc+items+item + 1 User. **No N+1 in get_supplier_invoice** (item from selectinload). |
| **3️⃣ Totals** | Create: in-loop (incremental). Add: **incremental** (total_exclusive += line_excl, vat_amount += line_vat, total_inclusive, balance). | ✅ Incremental on add. |
| **4️⃣ Full document reload after insert** | Add returns `get_supplier_invoice(invoice_id, current_user_and_db, db)` (no tenant in signature). | ⚠️ **Yes.** Full document refetch for response. |
| **5️⃣ Heavy joins on add** | Add: one selectinload(Invoice.items). Response: selectinload(Invoice.items).selectinload(SupplierInvoiceItem.item); no per-line cost/ledger. | ✅ Lighter than sales: no per-line cost/ledger in get. |
| **6️⃣ Tenant/company validation** | Same pattern: RLS from get_current_user; create uses body company_id. | No explicit validation of company_id from payload. |
| **7️⃣ Session GUC** | Once in get_current_user. | ✅ Once per request. |
| **8️⃣ Inventory/stock checks** | Create/add: **none** (stock added on batch). | ✅ No stock check on add. |
| **9️⃣ Single DB transaction** | One commit; refresh(invoice); then get_supplier_invoice in same session. | ✅ Single transaction for write; response in same session. |
| **🔟 Response payload** | Full SupplierInvoiceResponse: header, items with item_code, item_name, item_category, base_unit, vat_rate; supplier_name, branch_name, created_by_name. | Moderate (no batch/cost enrichment per line). |

---

### 1.4 Purchase Orders

| # | Question | Finding |
|---|----------|--------|
| **1️⃣ Endpoint(s)** | `POST /purchases/order` (create), `POST /purchases/order/{order_id}/items` (add one item) | Create: `create_purchase_order`; Append: `add_purchase_order_item` |
| **2️⃣ DB queries (create)** | Order number: **Branch** + **DocumentSequence** (or create) + commit inside get_purchase_order_number (⚠️ separate commit). Then N order items (no Item lookup in create!), flush, then **SnapshotService.upsert_search_snapshot_last_order per item** (N), then **DailyOrderBook** lookup/insert per item (N). Then commit + refresh. | **N+1:** N snapshot upserts, N order book lookups/inserts. Create does **not** load Item per line (only item_id from payload). |
| **2️⃣ DB queries (add item)** | 1 Order+items (selectinload) + insert order_item + flush + update order total + **1 DailyOrderBook** lookup (existing) or insert + commit. Then **get_purchase_order(order_id, ...)**. get_purchase_order: 1 Order+items+item (selectinload) + Company (or from relation) + 1 User (created_by) + **per item** CanonicalPricingService.get_best_available_cost + optionally 1 User (approved_by). | Add: **~3–4** for write; **Response:** 1 + 1 User + **N cost lookups** (get_best_available_cost per line). **N+1:** one cost query per order line. |
| **3️⃣ Totals** | Create: sum in loop (incremental). Add: **incremental** (order.total_amount += total_item_price). | ✅ Incremental on add. |
| **4️⃣ Full document reload after insert** | Add returns `get_purchase_order(order_id, ...)`. | ⚠️ **Yes.** Full document refetch + item details + default_cost per line. |
| **5️⃣ Heavy joins on add** | Add: Order + items. Response: Order + items + Item (selectinload) + **CanonicalPricingService.get_best_available_cost** per item. | ⚠️ **Heavy on response:** N cost lookups (ledger/pricing). |
| **6️⃣ Tenant/company validation** | Same: RLS from get_current_user; create uses body company_id. | No explicit company_id validation from payload. |
| **7️⃣ Session GUC** | Once in get_current_user. | ✅ Once per request. |
| **8️⃣ Inventory/stock checks** | Create/add: **none** (PO does not allocate stock). | ✅ No stock check on add. |
| **9️⃣ Single DB transaction** | Add: one commit then get_purchase_order. **create_purchase_order:** get_purchase_order_number does **db.commit()** inside (DocumentSequence increment) → **two commits** in one request (create flow). | ⚠️ Create: **two commits** (numbering then main). Add: single commit. |
| **🔟 Response payload** | Full PurchaseOrderResponse: header, items with item_code, item_name, category, base_unit, is_controlled, **default_cost** per line; supplier_name, branch_name, created_by_name, approved_by_name, logo_url. | ⚠️ **Large:** full document + cost per line. |

---

## 2. Shared / Transaction Services

- **DocumentService:** `get_quotation_number`, `get_sales_invoice_number`, `get_supplier_invoice_number`, `get_purchase_order_number`, `get_next_document_number`.  
  - **Quotation/Sales/GRN/Credit/Payment:** use `get_next_document_number` (single DB function call).  
  - **Purchase order / Quotation numbers:** custom path: Branch lookup + DocumentSequence select/insert + **commit** inside the method → **shared bottleneck** and extra commit in create PO/create quotation flows.
- **PricingService:** used in Sales (create + add item) and in Quotation/Purchase **response** (get_quotation, get_sales_invoice, get_purchase_order). **get_item_cost** / **calculate_recommended_price** / **get_min_margin_percent** trigger multiple queries (Item, ledger, ItemPricing, CompanyMarginTier, CompanyPricingDefault, get_stock_by_batch).
- **InventoryService.check_stock_availability:** used in Sales create and add item (one call per line / per add). Each call: convert_to_base_units (Item + units) + get_current_stock (SUM on ledger).
- **SnapshotService / SnapshotRefreshService:** used in GRN and in Sales/Quotation convert (not in add-item path for quotations/sales/invoices/PO).
- No single “transaction document service” that encapsulates create + add item + totals; each module implements its own flow → duplication and inconsistent patterns.

---

## 3. Detected Issues (Flags)

| Issue | Where | Severity |
|-------|--------|----------|
| **N+1: Item per line on create** | Quotations, Sales, Supplier Invoice create: loop over lines with `db.query(Item).filter(Item.id == item_id).first()`. | High |
| **N+1: Cost / pricing per line on response** | get_quotation: `PricingService.get_item_cost` per item. get_sales_invoice: `get_item_cost` + InventoryLedger (sale_ledgers) per item. get_purchase_order: `CanonicalPricingService.get_best_available_cost` per item. | High |
| **Re-fetch entire document after every item insert** | add_quotation_item → get_quotation; add_sales_invoice_item → get_sales_invoice; add_supplier_invoice_item → get_supplier_invoice; add_purchase_order_item → get_purchase_order. | High |
| **SELECT SUM() / aggregation on every insert** | Sales add item: `check_stock_availability` → `get_current_stock` (SUM(quantity_delta) on inventory_ledger). Not “SUM over items table” but heavy per-add. Create: same SUM per line. | Medium |
| **Company_id from payload** | Create endpoints accept company_id (and branch_id) in body and use them without validating against JWT-derived company (RLS still filters reads; writes use payload). | Medium (security/consistency) |
| **Blocking DB operations** | All add-item and create flows are synchronous; no async/background. Document number generation (PO, Quotation) does a commit inside the request. | Medium |
| **Shared service bottlenecks** | DocumentService.get_purchase_order_number / get_quotation_number: Branch + DocumentSequence query + **commit**. PricingService and InventoryService called repeatedly in loops. | Medium |
| **Repeated joins to inventory/pricing** | get_sales_invoice: per line InventoryLedger (reference_type, reference_id, item_id, transaction_type) and optionally get_item_cost (ledger, get_stock_by_batch). get_quotation / get_purchase_order: per-line cost from ledger/pricing. | High |
| **Missing composite indexes** | inventory_ledger: idx on (company_id, branch_id, item_id) exists (040). quotation_items / sales_invoice_items / supplier_invoice_items / purchase_order_items: no composite (document_id, item_id) or (company_id, branch_id, document_id) seen in migrations. FKs on document_id/item_id typically have single-column indexes from PK/FK. | Medium |
| **Full re-aggregation on update (not add)** | update_supplier_invoice_item: `total_exclusive = sum(l.line_total_exclusive for l in invoice.items)` — full re-sum over items in memory after one line update. Add-item uses incremental; update uses full sum. | Low (update path) |
| **add_sales_invoice_item response call** | `get_sales_invoice(invoice_id, db)` — only two arguments; get_sales_invoice expects (invoice_id, current_user_and_db, tenant, db). Possible wrong tenant/current_user when building response. | Medium (bug risk) |

---

## 4. Index Coverage (Relevant to Add-Item / Get Document)

- **inventory_ledger:** item_id, branch_id, company_id, reference_type+reference_id, (company_id, branch_id, item_id, created_at) in 040.
- **quotations:** company_id, branch_id, status (003).
- **sales_invoices / supplier_invoices / purchase_orders:** not fully audited; list endpoints filter by company_id, branch_id, etc. Document tables likely have FKs; composite (company_id, branch_id, id) or (branch_id, id) for “get my document” may be missing.
- **Line item tables:** quotation_items (quotation_id), sales_invoice_items (sales_invoice_id), supplier_invoice_items (purchase_invoice_id), purchase_order_items (purchase_order_id). Typical FK index on document side; (document_id, item_id) for “one item per document” uniqueness and join back could help.

---

## 5. Consolidated Optimization Plan

### A) Architectural changes

1. **Unified transaction document service (optional)**  
   - Single service for “create header”, “append line”, “recalculate totals”, “get document for response” to reduce duplication and standardize DB usage (single doc load, batch item/cost load).
2. **Header vs item append separation**  
   - Already mostly separated (create vs POST …/items). Consider **returning only the new line + updated totals** from add-item endpoints (or a small payload) instead of full document.
3. **Document numbering**  
   - Remove commit from DocumentService.get_purchase_order_number / get_quotation_number; use same transaction as document create (e.g. get_next_document_number style or sequence in same transaction).
4. **Company/branch from auth**  
   - For create, consider deriving company_id/branch_id from JWT/user context (and optionally validating payload against it) instead of trusting body only; keep RLS as backstop.

### B) SQL-level improvements

1. **Batch load items for create**  
   - Single query: `Item.id.in_([...])` for all item_ids in the request; build a map; use in loop to avoid N Item queries.
2. **Batch load cost/pricing for response**  
   - In get_quotation / get_sales_invoice / get_purchase_order: load all line item_ids; one or two batched queries for cost (e.g. ledger / pricing by item_id, branch_id) and attach to lines in memory instead of per-line get_item_cost / get_best_available_cost.
3. **Batch stock check**  
   - For create with multiple lines: single (or few) queries to get current_stock for (item_id, branch_id) for all distinct (item_id, branch_id) in the request; validate in memory.
4. **Avoid full document refetch on add item**  
   - Option 1: Return 201 with the new line + updated header totals (and optionally list of line ids).  
   - Option 2: If full document is required, load document + items in the add-item handler (already in memory after insert), compute totals, build response DTO from in-memory graph without a second get_* round-trip.

### C) Service-layer refactor

1. **PricingService**  
   - Add batch methods, e.g. `get_item_costs_batch(db, item_ids, branch_id)` returning dict item_id → cost, and use in get_quotation / get_sales_invoice / get_purchase_order instead of per-line get_item_cost.
2. **InventoryService**  
   - Add `check_stock_availability_batch(db, [(item_id, branch_id, quantity, unit_name), ...])` and use in create_sales_invoice (and similar) to avoid N separate checks.
3. **DocumentService**  
   - Make get_purchase_order_number / get_quotation_number use a path that does not commit (e.g. same get_next_document_number pattern or SELECT/UPDATE sequence in caller’s transaction).
4. **CanonicalPricingService**  
   - Expose batch get_best_available_cost for list of (item_id, branch_id, company_id) for use in get_purchase_order (and similar).

### D) Payload reduction

1. **Add-item response**  
   - Prefer returning the new line (and updated header totals) instead of full document; client can append to local state or refetch list when needed.
2. **Optional “minimal” get document**  
   - Query param or separate endpoint for “document + lines without cost/margin/batch” for list/preview; full enrichment only when opening for edit/print.
3. **Lazy enrichment**  
   - Don’t attach unit_cost_base, batch_allocations, margin_percent on every get; only when needed (e.g. edit screen or print).

### E) Index recommendations

1. **Line item tables**  
   - Composite unique (or supporting index) (document_id, item_id) where “one item per document” is enforced: e.g. quotation_items(quotation_id, item_id), sales_invoice_items(sales_invoice_id, item_id), supplier_invoice_items(purchase_invoice_id, item_id), purchase_order_items(purchase_order_id, item_id). Supports duplicate check and join-back.
2. **Documents**  
   - Composite (company_id, branch_id, id) or (company_id, id) on sales_invoices, supplier_invoices, purchase_orders, quotations if “list by company/branch” or “get by id scoped to company” is common.
3. **inventory_ledger**  
   - (reference_type, reference_id, item_id, transaction_type) or (reference_type, reference_id) if get_sales_invoice’s sale_ledgers filter is hot; 001 already has reference_type+reference_id.

### F) Incremental total strategy

- **Current state:** Add-item endpoints already update header totals incrementally (quotation, sales, supplier invoice, PO). No SELECT SUM() over items on add.
- **Recommendation:** Keep incremental totals on add/delete. For **update line** (e.g. update_supplier_invoice_item), either: (a) keep full re-sum over current items in memory (already in session), or (b) do incremental delta (old line totals − new line totals) to avoid iterating all lines. Re-sum in memory is acceptable if item count is small; document totals could also be maintained in DB via trigger if desired.

### G) Endpoint restructuring

1. **Create document**  
   - Keep “create with initial items” as is for UX; optimize with batched Item load and batched stock check (sales) and single transaction (fix PO number commit).
2. **Add item**  
   - **Option A:** Return 201 with body `{ "line": QuotationItemResponse, "totals": { "total_exclusive", "vat_amount", "total_inclusive" } }` (and similar for sales/supplier/PO) so client does not need full document.  
   - **Option B:** If full document is required, build response from the same session (document + items already loaded after insert) without calling get_* again.  
3. **Get document**  
   - Keep single get by id; add batch cost/pricing and optional “minimal” shape to reduce work and payload size.

---

## 6. Summary Table

| Document      | Add-item totals | Full reload after add | N+1 (create)     | N+1 (get response) | Stock check on add | Single transaction (add) |
|-------------|-----------------|------------------------|------------------|--------------------|--------------------|---------------------------|
| Quotation   | Incremental     | Yes (get_quotation)    | Item per line     | Cost per line      | No                 | Yes                       |
| Sales       | Incremental     | Yes (get_sales_invoice)| Item + stock + pricing per line | Cost + ledger per line | Yes                | Yes                       |
| Supplier inv| Incremental     | Yes (get_supplier_invoice) | Item per line  | No                 | No                 | Yes                       |
| Purchase order | Incremental  | Yes (get_purchase_order)| Snapshot + order book per line | Cost per line   | No                 | Yes (create has 2 commits) |

---

*End of audit. No code was modified.*
