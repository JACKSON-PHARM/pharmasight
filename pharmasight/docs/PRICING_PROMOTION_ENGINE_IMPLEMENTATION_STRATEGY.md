# Pricing & Promotion Engine — Implementation Strategy (Revised)

**Status:** Planning (no code changes yet)  
**Date:** 2025-02-26  
**Scope:** Promotions on top of recommended price (cost + margin); transactional discount unchanged; override logging for manual price changes. No stored base_price.

---

## 1. Executive Summary

This document defines the **simplified** implementation strategy for the Pricing & Promotion Engine in PharmaSight:

- **No base price layer.** Cost + margin (current `PricingService.calculate_recommended_price`) remains the only “base”; no stored base_price column.
- **Promotions** are applied on top of recommended price (company-level or branch-level; date-bound; branch overrides company).
- **`discount_percent` and `discount_amount`** stay strictly transactional (POS line discount only); promotions are never stored in these fields — they affect only the resolved **unit price** before discount.
- **Line total formula** unchanged: `line_total_exclusive = unit_price_exclusive × quantity − discount`; then VAT.
- **Manual price changes** require override permission and are logged in `price_override_log`.

---

## 2. Pricing Hierarchy (Final)

| Layer | Description | Where it lives |
|-------|-------------|----------------|
| **1. Recommended price (base)** | Cost + margin from existing `PricingService.calculate_recommended_price`. No stored base_price. | Existing PricingService |
| **2. Promotions** | Date-bound rules (e.g. percent off, fixed price). Company or branch scope; branch overrides company. Applied to recommended price → produces promoted unit price. | New PromotionService + promotions tables |
| **3. Resolved unit price** | Result of (1) then (2). Stored in `unit_price_exclusive` when user does not override. | New PricingResolutionService |
| **4. Manual override (optional)** | User sets a different price → require permission, log in price_override_log, store in `unit_price_exclusive`. | New PriceOverrideService + sales API |
| **5. Line discount (transactional)** | Existing `discount_percent` and `discount_amount`. Applied only to the line total after unit price × quantity. **Strictly transactional;** never used for promotion storage. | Unchanged; sales_invoice_items, quotation_items |

Flow: **Recommended → Promotions → Resolved price** (or **Override** if user sets price and has permission). Then **line total = unit_price × qty − discount**; VAT as today.

---

## 3. What Stays Unchanged

- **Line total formula:** `line_total_exclusive = unit_price_exclusive × quantity − discount_amount` (or discount_percent); then VAT. No change in `sales.py` or `quotations.py`.
- **Discount columns:** `discount_percent` and `discount_amount` remain the only line-level discount; semantics are strictly transactional (POS discount only). No schema change.
- **Item model:** No new base_price (or any selling price) column. Cost + margin remains the source of “base” price.
- **Document/PDF/KRA:** Continue to read `unit_price_exclusive` and `line_total_*` from stored rows. No change.
- **Batch, quotation conversion, multi-branch, stock adjustment:** No change.

---

## 4. Services (Revised)

### 4.1 PromotionService (new)

- **CRUD** for promotions (company-level: `branch_id` null; branch-level: `branch_id` set).
- **Applicable promotions:** Given `(item_id, branch_id, company_id, date)` return promotions that:
  - Are valid for that date (`valid_from` ≤ date ≤ `valid_to`),
  - Match item (by item_id or product_category or “all”),
  - Are company-wide or for that branch.
- **Precedence:** Branch-level promotions override company-level when both apply; among same level, define a clear rule (e.g. best discount, or first match). No mixing with `discount_percent` / `discount_amount`.

### 4.2 PricingResolutionService (new)

- **Single responsibility:** Resolve the selling unit price for a line before any transactional discount.
- **Inputs:** `item_id`, `branch_id`, `company_id`, `unit_name`, `sales_type`, `date` (default today).
- **Steps:**
  1. **Base price:** Call existing `PricingService.calculate_recommended_price(...)` (cost + margin). No stored base_price.
  2. **Promotions:** Call `PromotionService.get_applicable_promotions(item_id, branch_id, company_id, date)`; apply best applicable promotion to the recommended price (branch over company).
  3. Return **resolved unit price** + optional metadata (e.g. `applied_promotion_id`, `recommended_price` for display).
- **No DB write** to invoice lines; caller (sales API or recommended-price endpoint) stores the result in `unit_price_exclusive` when appropriate.

### 4.3 PriceOverrideService (new)

- When the user supplies a **different** price than the resolved price:
  - **Validate:** User has override permission; optionally min-margin or manager approval.
  - **Log:** Insert into `price_override_log` (invoice_id, line_id or item_id, user_id, approved_by, previous_price, new_price, reason, created_at).
  - Caller (sales API) then updates the draft line’s `unit_price_exclusive`. No silent overwrite.

### 4.4 PricingService (existing)

- Unchanged: `calculate_recommended_price`, cost from ledger, margin from ItemPricing / CompanyMarginTier / CompanyPricingDefault, rounding. This remains the **only** “base” price source (no stored base_price).

---

## 5. New Tables (No base_price)

| Table | Purpose |
|-------|--------|
| **promotions** | id, company_id, branch_id (nullable: null = company-level), name, type (e.g. percent_off, fixed_price), value, valid_from, valid_to, item_scope (e.g. item_ids, product_category, all). Date-bound. |
| **promotion_items** (or JSONB on promotions) | Link promotion to items/categories (item_id and/or product_category) so PromotionService can match. |
| **price_override_log** | invoice_id, line_id (or invoice_id + item_id), user_id, approved_by (nullable), previous_price, new_price, reason, created_at. Audit only; no change to line schema. |

No `item_base_prices` or item-level base price column.

---

## 6. New API Endpoints

| Endpoint | Purpose |
|----------|--------|
| **GET /api/promotions** | List promotions (filter by branch, company, date). |
| **POST/PUT/DELETE /api/promotions** | CRUD for promotions (admin). |
| **GET /api/pricing/resolve** (optional) | Query params: item_id, branch_id, company_id, unit_name, sales_type, date. Returns resolved unit price + metadata. Used by POS or by backend when adding a line. |
| **Override handling** | When sales API receives `unit_price_exclusive` different from resolved price: call PriceOverrideService (permission + log), then update draft line. Can be inside existing PATCH/POST item flow or a dedicated **POST .../price-override** if preferred. |

Existing **GET .../items/{id}/recommended-price** should call **PricingResolutionService** (so it returns promoted price by default); optional query param `?exclude_promotions=true` to return recommended-only for display.

---

## 7. Sales API Integration (Behaviour Only)

- **Create invoice / Add item:** If `unit_price_exclusive` is **not** provided (or “use recommended”): call `PricingResolutionService.resolve(...)` and store result in `unit_price_exclusive`. Then compute line total with **existing formula** using existing `discount_percent` / `discount_amount`.
- **Create invoice / Add item / PATCH line:** If client **sends** `unit_price_exclusive` and it **differs** from resolved price: call PriceOverrideService (permission + log), then set line’s `unit_price_exclusive` to the override. Line total formula unchanged.
- **Min-margin check:** Keep as today; run after final unit price (resolved or override) is set.

No change to how discount or line total is calculated; only to **how** `unit_price_exclusive` is obtained when not provided or when overridden.

---

## 8. Discount: Strictly Transactional

- **Promotions** only affect the **unit price** (recommended → promoted). That value is stored in `unit_price_exclusive`. Promotions are **not** stored in `discount_percent` or `discount_amount`.
- **discount_percent** and **discount_amount** are used only for **transactional** POS line discount (manual entry at sale time). Formula stays: line total = unit_price × qty − discount; then VAT.
- Backward compatible: all existing data and all existing code that reads/writes these two columns remain valid.

---

## 9. Simplified Implementation Plan

**Phase 1 — Data and promotions (additive)**  
1. Add **promotions** and **promotion_items** (or equivalent) tables; add **price_override_log** table.  
2. Add SQLAlchemy models and migrations. No changes to items or sales_invoice_items.

**Phase 2 — PromotionService**  
3. Implement **PromotionService**: CRUD + `get_applicable_promotions(item_id, branch_id, company_id, date)` with branch-over-company and date-bound logic.  
4. Add **GET/POST/PUT/DELETE /api/promotions**. Do not wire into sales yet.

**Phase 3 — PricingResolutionService**  
5. Implement **PricingResolutionService**: base = `PricingService.calculate_recommended_price(...)`; then apply best promotion from PromotionService; return resolved price + metadata.  
6. Optionally add **GET /api/pricing/resolve**.  
7. Switch **GET .../items/{id}/recommended-price** to use PricingResolutionService (with optional `exclude_promotions`).

**Phase 4 — Sales API and override**  
8. In **create-invoice** and **add-invoice-item**: when `unit_price_exclusive` is missing, call PricingResolutionService and store result in `unit_price_exclusive`. Keep line total formula unchanged.  
9. Implement **PriceOverrideService**: on manual price different from resolved, check permission, write price_override_log, return success.  
10. In **create-invoice**, **add-invoice-item**, and **PATCH line**: when client sends a different `unit_price_exclusive`, call PriceOverrideService then update line. Ensure override only for DRAFT.

**Phase 5 — Validation**  
11. Regression test: invoice creation, line totals, PDF/KRA output, quotation conversion.  
12. Test: promotions applied when no price sent; override logged when user sets price with permission.

---

## 10. Summary

- **No base price layer:** Cost + margin (recommended price) is the base; no stored base_price column.
- **Promotions** applied on top of recommended price via **PromotionService** and **PricingResolutionService**; branch over company; date-bound.
- **discount_percent** and **discount_amount** strictly transactional; line total formula unchanged.
- **Override** for manual price changes: permission + **price_override_log**; no silent overwrite.
- **Implementation:** New tables (promotions, promotion_items, price_override_log); new services (PromotionService, PricingResolutionService, PriceOverrideService); wire resolution into recommended-price and sales API; override path with logging. Five phases as above.

This revised strategy is ready for implementation; no code has been modified in this phase.
