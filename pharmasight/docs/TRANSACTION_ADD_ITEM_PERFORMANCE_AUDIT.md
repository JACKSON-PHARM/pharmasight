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

## 7. Add-Item Refactor (Post-Implementation)

The following changes were applied to **add-item endpoints only** (no new endpoints, no schema changes, no change to create endpoints).

### 7.1 Changes made

- **Removed full document refetch:** Each add-item endpoint no longer calls `get_quotation` / `get_sales_invoice` / `get_supplier_invoice` / `get_purchase_order` after commit.
- **Response built in-memory:** After flush and incremental totals update, the response is built from the already-loaded document and its `items` relationship. One batch query loads `Item` for all line `item_id`s; header (company/branch/user, logo) is filled with minimal queries. Cost/margin enrichment runs **only for the newly added line** where required.
- **Single transaction:** Load → validate → insert line → update totals → build response → single `db.commit()` → return. No nested commits, no DocumentService commit in add-item path.
- **Sales:** Added `tenant: Optional[Tenant] = Depends(get_tenant_optional)` so logo_url can be built the same way as in get_sales_invoice (dependency only; request/response schema unchanged).

### 7.2 Before vs after approximate DB query count (add one item)

| Document        | Before (add one item) | After (add one item) |
|-----------------|-----------------------|------------------------|
| **Quotation**   | 1 doc+items + 1 Item + insert + commit + **get_quotation** (1 doc+items+item + **N get_item_cost** + 1 Company + 1 Branch + 1 User) ≈ **5 + N** (N = total lines) | 1 doc+items + 1 Item + insert + **1 batch Item** + **1 get_item_cost (new line only)** + 1 Company + 1 Branch + 1 User + commit ≈ **8** (fixed) |
| **Sales invoice** | 1 doc+items + 1 Item + stock check + pricing/margin + insert + commit + **get_sales_invoice** (1 doc+items+item + **N get_item_cost** + **N InventoryLedger** + Company + Branch + User) ≈ **7 + 2N** | 1 doc+items + 1 Item + stock check + pricing/margin + insert + **1 batch Item** + **1 get_item_cost (new line only)** + Company + Branch + User + commit ≈ **10** (fixed) |
| **Supplier invoice** | 1 doc+items + _supplier_invoice_item_to_totals (1 Item) + insert + commit + refresh + **get_supplier_invoice** (1 doc+items+item + 1 User + supplier/branch from relation) ≈ **4 + 1** | 1 doc+items + _supplier_invoice_item_to_totals (1 Item) + insert + **1 batch Item** + User + supplier/branch (lazy or 2) + commit ≈ **6–7** (no get_*) |
| **Purchase order** | 1 doc+items + insert + DailyOrderBook lookup/upsert + commit + **get_purchase_order** (1 doc+items+item + **N get_best_available_cost** + Company + 2 User + supplier/branch) ≈ **5 + N** | 1 doc+items + insert + DailyOrderBook + **1 batch Item** + **1 get_best_available_cost (new line only)** + Company + 2 User + supplier/branch + commit ≈ **9** (fixed) |

So after refactor, add-item cost is **independent of document size** (no N+1 in response build).

### 7.3 Confirmations

| Requirement | Status |
|-------------|--------|
| Stock validation (sales) still runs before insert | ✅ `InventoryService.check_stock_availability` unchanged before insert. |
| Batch validation (supplier invoice) still runs | ✅ `_supplier_invoice_item_to_totals` still calls `_require_batch_and_expiry_for_track_expiry_item` and unit multiplier validation. |
| Duplicate item check (all) still runs | ✅ Same loop over `document.items` / duplicate check before insert. |
| Order book / DailyOrderBook rules (PO) still apply | ✅ Same `existing` lookup and update or new `DailyOrderBook` insert. |
| SnapshotService / snapshot logic untouched | ✅ Not used in add-item paths; no changes. |
| Response schema unchanged | ✅ Same `QuotationResponse` / `SalesInvoiceResponse` / `SupplierInvoiceResponse` / `PurchaseOrderResponse`; built from in-memory document. |
| Each add still committed immediately | ✅ Single `db.commit()` after building response; no batching, no delayed commit. |
| No new endpoints, no fast/light variants | ✅ Only `POST /.../{id}/items` handlers changed. |
| Create endpoints not modified | ✅ No changes to create_quotation, create_sales_invoice, create_supplier_invoice, create_purchase_order. |

### 7.4 Performance expectation

- **Quotations, supplier invoice, purchase order:** add-item should be in the **sub-500 ms** range (write + batch Item + 1 cost query for new line + header lookups).
- **Sales:** add-item should be in the **sub-800 ms** range (write + stock check + pricing/margin + batch Item + 1 cost for new line + header lookups).

---

## 8. Single-DB / No-Tenant Readiness (Testing Without Tenant Header)

So that add-item and document retrieval work when **no X-Tenant-ID / X-Tenant-Subdomain** is sent (e.g. single database, or no tenant in `sessionStorage`), the following endpoints were switched from **get_tenant_or_default** (which raises 400 when no tenant) to **get_tenant_optional** (returns `None` when no tenant):

| Area | Endpoints | Change |
|------|-----------|--------|
| **Quotations** | get_quotation_pdf, get_quotation, add_quotation_item | Tenant optional; logo/signed URL only when `tenant is not None`. |
| **Sales** | get_sales_invoice, get_sales_invoice_pdf, add_sales_invoice_item | Already used get_tenant_optional. |
| **Supplier invoices** | get_supplier_invoice, get_supplier_invoice_pdf | Already optional or no tenant. |
| **Purchase orders** | get_purchase_order, add_purchase_order_item, approve_purchase_order, get_purchase_order_pdf_url | Tenant optional; logo/PDF upload/PDF URL only when tenant present. Approve without tenant: PO is approved but no PDF is stored. PDF URL returns 400 if tenant is None and path is tenant-assets. |

With this, the red banner *"This operation requires a tenant..."* should no longer appear for add-item or normal get-document when no tenant header is sent. Logo and tenant-assets URLs are simply omitted when tenant is missing.

---

## 9. How to Test Add-Item Request Duration (Browser Network Tab)

1. **Open the app** (e.g. Sales at `localhost:3000/#sales`).
2. **Open DevTools** → **Network** tab; enable **Preserve log** and **Disable cache**; filter **Fetch/XHR**.
3. **Create or open a draft** (e.g. new sales invoice or open existing draft).
4. **Add the first item** (e.g. search, select, set qty/price, Add). Note the request that hits `POST /api/sales/invoice/{id}/items` (or the equivalent for quotations/purchases/supplier invoices).
5. **Add the second item** the same way. Again find the `POST .../items` request.
6. **Measure:** Click the request → **Timing** (or look at the duration column). You should see a single round-trip; duration is the add-item latency (target: &lt;500 ms for quotation/supplier/PO, &lt;800 ms for sales). For a server-side breakdown, see step 7 and §10.

If the tenant banner appeared before, ensure you’re on the latest backend (tenant optional on document endpoints). If you use a single DB and never set a tenant, you can leave headers as-is; add-item and get-document should succeed without the banner.

7. **Breakdown:** Click the request → **Headers** → **Response Headers**. Look for `X-Timing-*` headers (see §10).

---

## 10. Server Response Timing Breakdown (X-Timing-* Headers)

Add-item endpoints (quotation and sales invoice) set **`request.state.timings`** so **RequestTimingMiddleware** adds **response headers** with a per-phase breakdown. In the **Network** tab you can see where the total response time (e.g. 3.56 s) is consumed.

**Where to see it (Chrome DevTools):**
1. Open **Network** tab → **Fetch/XHR**.
2. Trigger the slow action (e.g. **Add item** = POST `.../items`, or **open document** = GET `.../invoice/{id}` or `.../quotations/{id}`).
3. Click the **request** that took ~3+ seconds.
4. Open the **Timing** sub-tab. A **Server Timing** block appears when the response includes the `Server-Timing` header, with each phase (Load document, Cost lookup, etc.) and duration in ms.
5. Alternatively, **Headers** → **Response Headers** → **`X-Timing-*`** and **`Server-Timing`** for the same breakdown.

| Header | Meaning |
|--------|--------|
| **X-Timing-LoadMs** | Load document (quotation/invoice with items) from DB. |
| **X-Timing-CompanyCheckMs** | Application-level company check. |
| **X-Timing-InsertMs** | Insert new line, flush, update document totals. |
| **X-Timing-ItemsMapMs** | Batch load Item rows for all line item_ids. |
| **X-Timing-CostMs** | Cost lookup for the new line only: snapshot first, then FEFO/ledger; margin calc. |
| **X-Timing-BuildMs** | Load company, branch, user; build logo URL. |
| **X-Timing-TotalMs** | Total server-side time (matches "Waiting for server response" in Timing tab). |

**Cost lookup:** Add-item uses **item_branch_purchase_snapshot** (updated in same transaction as ledger) for **last_purchase_price** when available; one fast query. If snapshot has no cost, it falls back to **get_item_cost(use_fefo=True)** (FEFO batch, then ledger, then canonical). Snapshot is trusted; expiry is maintained in item_branch_snapshot.

---

## 11. Carry Cost/Margin from Client; Validate at Batch

**Flow:** User loads an item in the search row (item search returns cost, e.g. from snapshot). User may adjust price; margin is then calculated on the client from (price − cost) / price. When adding the item, we **carry** that cost and margin so the server does not need to look up cost again for display.

- **Add-item request** may include optional **`unit_cost_base`** and **`margin_percent`** (from client: search cost + user-adjusted price). When present, the backend uses them for the new line in the response and **skips** cost lookup (snapshot/FEFO) for that line. This keeps add-item fast and keeps the margin the user saw.
- **Margin and floor validation** are **not** done at add-item. They are done when the document is **batched** (or, for quotations, when **converting to invoice**):
  - **Sales invoice:** On **batch** (DRAFT → BATCHED), each line’s margin is computed from the **allocated batch cost** (FEFO). If margin &lt; company/item minimum and the user does not have **sales.sell_below_min_margin**, the batch is rejected.
  - **Quotation:** On **convert to invoice**, after FEFO allocation, each line’s margin is computed from quotation price and allocated cost. Same minimum-margin check and permission apply.

So: add-item is fast and carries the user’s price and margin; the only moment we **validate** margin (and floor) is at **batch** (sales) or **convert** (quotation), when we have real allocated cost.

---

## 12. Add-Item 200 ms Audit and Optimization Plan

**Measured breakdown (Server Timing, add-item request):**

| Phase | Measured (ms) | % of TotalMs |
|-------|----------------|--------------|
| **LoadMs** (Load document) | **632.70** | 36% |
| InsertMs (Insert line) | 328.90 | 19% |
| BuildMs (Build response) | 168.80 | 10% |
| CompanyCheckMs | 162.30 | 9% |
| ItemsMapMs (Items batch) | 157.30 | 9% |
| CostMs (Cost lookup) | 0.10 | &lt;1% |
| **TotalMs (server)** | **1.75 s** | 100% |
| **Browser “Waiting for server response”** | **3.47 s** | — |

**Gap (3.47 s − 1.75 s ≈ 1.7 s):** Not captured in current timers. Likely: `db.commit()`, response serialization (Pydantic → JSON), middleware, and/or DB connection/session setup before `t0`. Next step: add **CommitMs** (and optionally **SerializeMs**) and move `t0` to the very start of the handler (after deps) to see if auth/tenant/session dominate.

---

### Phase-by-phase audit

1. **Load document (632.70 ms)**  
   - **What runs:** `db.query(Quotation).options(selectinload(Quotation.items)).filter(Quotation.id == quotation_id).first()`.  
   - One query (or two with selectinload) by primary key; `quotation_items` has `idx_quotation_items_quotation_id`.  
   - **Why it can be slow:** Round-trip to DB (latency), large result set if many lines, or connection pool wait.  
   - **Levers:** Reduce rows (e.g. only load `id`/`company_id`/`branch_id`/`status` + `item_id` list for duplicate check and totals; then load full items only for response build), ensure index on `quotations.id` (PK), consider connection pooler (e.g. PgBouncer) if connection acquisition is slow.

2. **CompanyCheckMs (162.30 ms)**  
   - **What runs:** `require_document_belongs_to_user_company` → `get_effective_company_id_for_user(db, user)` (Branch ↔ UserBranchRole join, or fallback `Company.limit(1)`), then compare `document.company_id` to result.  
   - **Why it can be slow:** Two possible queries (Branch+UBR, then maybe Company); no caching of “user’s company” per request.  
   - **Levers:** Cache `effective_company_id` per (user_id, request) for the request lifecycle; or resolve once in `get_current_user` / auth dependency and pass into the helper so company check is a single in-memory compare.

3. **InsertMs (328.90 ms)**  
   - **What runs:** Duplicate check (in memory), `db.query(Item).filter(Item.id == item_data.item_id).first()`, build `QuotationItem`, `db.add(quotation_item)`, `db.flush()`, update quotation totals in memory.  
   - **Why it can be slow:** Extra **Item** fetch (separate query); `flush()` triggers INSERT + any RETURNING/defaults and FK checks.  
   - **Levers:** Reuse one Item load for both “item exists” and “ItemsMap” (see below). Ensure `quotation_items` INSERT is single row; check for triggers or heavy indexes; measure commit separately (CommitMs).

4. **ItemsMapMs (157.30 ms)**  
   - **What runs:** `db.query(Item).filter(Item.id.in_(item_ids)).all()` to build `items_map` for all line item_ids (existing + new).  
   - **Why it can be slow:** Second full Item fetch for the new line (we already load Item in Insert phase); IN-list over N item_ids.  
   - **Levers:** For add-item, **load only the new line’s Item** (single `Item.id == item_data.item_id`); attach to new line; for existing lines, use **already-loaded** items from `quotation.items[].item` (selectinload already loads `QuotationItem.item`). So replace “batch Item by all item_ids” with “one Item by item_data.item_id” and in-memory attach for existing lines from relationship. That removes the large IN query and cuts ItemsMapMs sharply.

5. **BuildMs (168.80 ms)**  
   - **What runs:** Three queries: `Company` by `quotation.company_id`, `Branch` by `quotation.branch_id`, `User` by `quotation.created_by`; optional `get_signed_url(logo_path)` (network call if tenant storage).  
   - **Why it can be slow:** Three sequential round-trips; logo URL can be slow if external.  
   - **Levers:** Single query returning company/branch/creator (e.g. raw SQL or joined load), or cache company/branch/user by id for the request (or short TTL). Defer or lazy-load logo URL for add-item response (e.g. omit or return placeholder) so add-item path does not block on storage.

6. **CostMs (0.10 ms)**  
   - Already negligible (client sends cost/margin; snapshot path when used is fast).

7. **Unaccounted (~1.7 s)**  
   - **Likely:** `db.commit()`, JSON serialization of full `QuotationResponse` (nested items), and time before `t0` (auth, tenant, session).  
   - **Levers:** Add **CommitMs** (timer around `db.commit()`); optionally **SerializeMs** (timer around response build/serialization). Move `t0` to the first line of the handler (after dependencies) to include session/auth cost in TotalMs, or add a **PreMs** timer in middleware to quantify “time before route”.

---

### Target: 200 ms end-to-end (browser “Waiting for server response”)

**Assumption:** After optimizations, “Waiting for server response” should align with server TotalMs + Commit + Serialize; target total **&lt; 200 ms**.

**Suggested order of work**

| # | Change | Phase(s) affected | Expected saving |
|---|--------|-------------------|------------------|
| 1 | **ItemsMap:** Load only new line’s Item; use `quotation.items[].item` for existing lines (selectinload already loads it). | ItemsMapMs | ~100–150 ms |
| 2 | **Build:** One query or cached lookup for company + branch + user (or cache by id per request). Defer logo URL for add-item (omit or lazy). | BuildMs | ~100–150 ms |
| 3 | **CompanyCheck:** Cache `effective_company_id` per request (or resolve once in auth deps); company check = in-memory compare. | CompanyCheckMs | ~100–160 ms |
| 4 | **Load:** Consider “light load” for add-item: load quotation header + only `item_id` list (or count) for duplicate check; then load full items in one go only for response (or keep current load but ensure indexes and pooler). | LoadMs | ~200–400 ms if load is reduced |
| 5 | **Insert:** Reuse single Item fetch for “exists” and for “items_map” (no second Item query). Add **CommitMs** (and optionally SerializeMs); optimize commit (single INSERT, no triggers if possible). | InsertMs, unaccounted | ~50–100 ms + visibility into commit/serialize |
| 6 | **Timing:** Add CommitMs (and optionally SerializeMs); optionally move t0 to start of handler to include auth/session in TotalMs. | Gap, TotalMs | No direct saving; clarifies where remaining time goes |

**Rough target after optimizations**

- LoadMs: &lt; 100 ms (light load or indexed single query).  
- CompanyCheckMs: &lt; 5 ms (cached company, compare only).  
- InsertMs: &lt; 80 ms (one Item fetch, one INSERT, no redundant work).  
- ItemsMapMs: &lt; 20 ms (single Item for new line; rest from relationship).  
- CostMs: &lt; 1 ms (unchanged).  
- BuildMs: &lt; 30 ms (one query or cache; no blocking logo).  
- CommitMs: &lt; 50 ms (measured; optimize if needed).  
- **Total server:** &lt; 200 ms, leaving room for serialization and network so browser “Waiting for server response” can meet 200 ms.

**Risks / constraints**

- Do not remove duplicate-item or company checks; only make them faster (caching, single compare).  
- Response schema and validation rules must remain the same; only reduce work (fewer queries, cached data, deferred logo).  
- If DB is remote, connection and round-trip latency will dominate; then prioritize fewer round-trips (combined queries, cache) and consider a connection pooler.

---

## 13. Add-Item Optimization Refactor (Query Structure & Identity) — Summary

**Scope:** Quotation, Sales Invoice, Supplier Invoice, Purchase Order add-item endpoints. No caching, no new services, no schema changes.

### Queries removed or avoided

| Change | Before | After |
|--------|--------|--------|
| **Tenant validation** | `require_document_belongs_to_user_company` called `get_effective_company_id_for_user(db, user)` → 1–2 queries (UserBranchRole + Branch, or Company) every time. | `effective_company_id` is set once in `get_current_user` on `request.state.effective_company_id`. When endpoints pass `request` into `require_document_belongs_to_user_company`, it uses that value; **zero extra DB round-trips** for company check. |
| **Document load** | Single query with `selectinload(document.items)` only. | Single query with **joinedload(company, branch, creator)** and **selectinload(items).selectinload(item)** so one round-trip loads document + header relations + all line items + each line’s Item. |
| **Items batch** | After insert: `db.query(Item).filter(Item.id.in_(item_ids)).all()` — one query per add-item to fetch all items for response. | **Removed.** Existing lines use already-loaded `line.item` (from selectinload). New line uses the single `Item` already fetched for validation (or returned from helper). **No second Item query.** |
| **Company / Branch / User** | After building lines: separate `db.query(Company)`, `db.query(Branch)`, `db.query(User)` for response header (3 queries). | **Removed.** Response uses eagerly loaded `document.company`, `document.branch`, `document.creator` (no extra queries). |

### Tenant identity resolution

- **Where:** `get_current_user` in `dependencies.py` (both cache path and full-resolve path).
- **What:** After resolving `company_id` (from cache or from `get_effective_company_id_for_user`), it sets `request.state.effective_company_id = company_id` before yielding `(user, db)`.
- **Usage:** All document endpoints that call `require_document_belongs_to_user_company(..., request)` now pass `request`. The helper uses `getattr(request.state, "effective_company_id", None)` when `request` is provided; if set, it skips `get_effective_company_id_for_user`. No duplication of company resolution; identity remains derived from the JWT/session only.

### Model changes (ORM only)

- **SalesInvoice, Quotation (sale.py):** Added `creator = relationship("User", primaryjoin="...created_by==User.id", foreign_keys="[...]")` so document load can use `joinedload(creator)`.
- **SupplierInvoice, PurchaseOrder (purchase.py):** Added `creator` relationship (PurchaseOrder already had `approved_by_user`). No DB schema change; no new columns or indexes.

### Instrumentation

- **CommitMs** added for add-item endpoints (Quotation, Sales): timer around `db.commit()`; reported in `request.state.timings` and exposed via `Server-Timing` / `X-Timing-*` headers.
- **Existing phases** (LoadMs, CompanyCheckMs, InsertMs, CostMs, BuildMs, TotalMs) unchanged; ItemsMapMs removed where the batch Item query was removed.

### Estimated performance gain

- **CompanyCheckMs:** ~100–160 ms → &lt; 1 ms when request has `effective_company_id` (typical for all authenticated document requests).
- **ItemsMapMs:** ~100–150 ms → 0 ms (batch Item query removed).
- **BuildMs:** ~100–150 ms → &lt; 20 ms (no separate Company/Branch/User queries; in-memory attribute assignment only).
- **Load:** One larger query (with joins) instead of 1 + 3 + 1 (document + company + branch + user + items batch); fewer round-trips, often lower total load time.
- **Target:** Handler total (Load + CompanyCheck + Insert + Cost + Build + Commit) in the **~200–300 ms** range for co-located DB, depending on network and DB load.

### Confirmation: no business logic changed

- Stock validation (sales): still performed before insert; unchanged.
- Margin validation: still applied when user provides price (sales add-item); batch/convert margin checks unchanged.
- Permission checks: `_user_has_sell_below_min_margin` and RLS unchanged.
- Batch validation (supplier invoice): unchanged; `_supplier_invoice_item_to_totals` still enforces batch/expiry where required.
- Duplicate item checks: unchanged (still in-memory over `document.items`).
- Transaction atomicity: single `db.flush()` and `db.commit()` per add-item; no change.
- Response schema and validation rules: unchanged; only the source of data (eager load vs. extra queries) changed.

---

## 14. Document Batching — Audit and Optimization (Single-DB, No Multi-Tenant DB References)

**Scope:** Endpoints that "batch" or convert documents (DRAFT → BATCHED / converted): sales invoice batch, supplier invoice batch, quotation convert-to-invoice, branch order batch. Goal: same as add-item — tenant identity from token, no redundant DB for company check, no N+1 Item queries, no multi-tenant DB assumptions.

### 14.1 Findings (pre-refactor)

| Endpoint | Tenant / company check | Item loading | Other |
|----------|------------------------|--------------|--------|
| **POST …/invoice/{id}/batch** (sales) | **Missing** — no `require_document_belongs_to_user_company` | N+1: `db.query(Item)` per line in body sync loop and per line in allocation loop | Uses `get_tenant_db`. Returns in-memory invoice after refresh. |
| **POST …/invoice/{id}/batch** (supplier) | **Missing** | N+1: `db.query(Item)` per `invoice_item` | After commit: separate `db.query(User)` for `created_by_name`; supplier/branch from relation (lazy). |
| **POST …/{quotation_id}/convert-to-invoice** | **Missing** | N+1: `db.query(Item)` per `q_item`; stock_errors loop has **duplicate** Item fetch | Uses `get_tenant_db`. Creates new invoice and returns it. |
| **POST …/orders/{order_id}/batch** (branch order) | **Missing** | No Item per line needed for batch logic | Uses `get_tenant_db`, `get_current_user`. No company check. |

**Multi-tenant DB:** None of these endpoints reference `tenant.database_url` or switch DB by tenant; they use `get_tenant_db` and `get_current_user` (correct for single shared DB). The gap is **missing tenant isolation**: an authenticated user could batch another company's document if they knew the ID.

### 14.2 Changes applied (same pattern as add-item)

1. **Tenant identity:** Add `request: Request` and call `require_document_belongs_to_user_company(db, user, document, "Invoice"|"Quotation"|"Branch order", request)` after loading the document (uses `request.state.effective_company_id` from `get_current_user`).
2. **Sales batch:** Load with `selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item)`. Use `line.item` / `invoice_item.item` instead of `db.query(Item)` in both loops.
3. **Supplier batch:** Load with `selectinload(SupplierInvoice.items).selectinload(SupplierInvoiceItem.item)` and `joinedload(supplier, branch, creator)`. Use `invoice_item.item` in loop; response uses `invoice.creator` (no separate User query).
4. **Convert quotation:** Load with `selectinload(Quotation.items).selectinload(QuotationItem.item)`. Use `q_item.item` in stock_errors and main loop; remove duplicate Item fetch.
5. **Branch order batch:** Add tenant check only (no Item eager load needed for batch).

Business logic (stock, margin, allocations, ledger, snapshots) unchanged.

---

*End of audit. Add-item refactor as in §7; single-DB as in §8; timing and snapshot as in §10; carry margin and validate at batch as in §11; 200 ms audit and plan as in §12; optimization refactor summary as in §13; document batching as in §14.*
