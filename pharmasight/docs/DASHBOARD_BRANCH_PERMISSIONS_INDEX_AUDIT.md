# Dashboard Branch Filter, Permissions, and Index Audit

## 1. Inventory Ledger Indexing

### 1.1 Existing indexes on `inventory_ledger`

| Index | Definition | Source |
|-------|------------|--------|
| `idx_inventory_ledger_item` | `(item_id)` | 001_initial.sql |
| `idx_inventory_ledger_branch` | `(branch_id)` | 001_initial.sql |
| `idx_inventory_ledger_expiry` | `(expiry_date)` | 001_initial.sql |
| `idx_inventory_ledger_company` | `(company_id)` | 001_initial.sql |
| `idx_inventory_ledger_reference` | `(reference_type, reference_id)` | 001_initial.sql |
| `idx_inventory_ledger_batch` | `(item_id, batch_number, expiry_date)` | 001_initial.sql |
| `idx_inventory_ledger_company_branch_item_created` | `(company_id, branch_id, item_id, created_at)` | 040_inventory_ledger_report_index.sql |

### 1.2 Dashboard valuation query pattern

- **Filter:** `WHERE company_id = ? AND branch_id = ? AND item_id IN (...)`  
- **Data:** All rows fetched; grouping in Python by `(company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)`.

No single index fully supports this filter and grouping. The closest is:

- `idx_inventory_ledger_company_branch_item_created`: supports `company_id`, `branch_id`, `item_id`, but not `batch_number`, `expiry_date`, `unit_cost` (used in grouping). Best for date-range report, not for full scan + group-by.
- `idx_inventory_ledger_company` + `idx_inventory_ledger_branch`: planner can use both for filter; no index supports the grouping columns.

### 1.3 Support for valuation query

- **Current:** Filter is supported reasonably by `(company_id, branch_id)` (e.g. company + branch indexes or the 040 composite). Full table scan for the branch is acceptable for moderate ledger size.
- **Gap:** No index on the full layer identity. For large ledgers, a composite index on the grouping columns could reduce scan and improve grouping if the DB did aggregation (currently done in app).

### 1.4 Recommended index (if desired)

To align with layer identity and possible future SQL-side aggregation:

```sql
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_layer_identity
ON inventory_ledger (company_id, branch_id, item_id, batch_number, expiry_date, unit_cost);
```

- **Justification:** Matches filter `company_id, branch_id` and grouping columns; supports valuation and any future “all branches” query that still filters by `company_id`.
- **Safe:** Additive only; no existing indexes removed.

---

## 2. Dashboard Branch Filter UI

### 2.1 Location

- **File:** `frontend/js/pages/dashboard.js`
- **Branch source:** `getBranchIdForStock()` (no dashboard-specific branch dropdown).

### 2.2 Implementation

- **Current branch:** From `BranchContext.getBranch()` (branch context service), else `CONFIG.BRANCH_ID`, else `localStorage` (`pharmasight_config` / `pharmasight_selected_branch`).
- **Branch selector:** Global app branch selection (e.g. branch select page / header), not a control on the dashboard page. Dashboard uses whatever branch is currently selected in the app.
- **API parameter:** Every dashboard KPI (stock value, items in stock, expiring count, order book, gross profit) is called with a single `branchId` from `getBranchIdForStock()`.
- **If no branch:** `applyDashboardFilters()` shows “Select a branch first.” and returns; no API calls.

### 2.3 “All branches” support

- **UI:** There is no “All branches” option on the dashboard. No dropdown for “Current branch / Specific branch / All branches.”
- **API:** All dashboard endpoints take a single `branch_id` (path or query). There is no dashboard API that aggregates across all branches of a company.
- **Conclusion:** Only “current/session branch” (or one selected branch) is supported. “All branches combined” is not implemented in UI or backend.

### 2.4 Summary

| Requirement | Status |
|-------------|--------|
| Current branch | Yes — via BranchContext / CONFIG / localStorage |
| Specific branch | Yes — user switches branch globally, dashboard uses it |
| All branches combined | No — no UI option, no backend support |
| How branch is passed to API | Single `branchId` in each request (e.g. `getTotalStockValue(branchId)`) |

---

## 3. Backend Support for “All Branches”

### 3.1 Valuation endpoint

- **Route:** `GET /api/inventory/branch/{branch_id}/total-value`
- **Contract:** `branch_id` is required (path). There is no “all” or optional branch.

### 3.2 Current behavior

- **Single-branch:** Query filters `company_id = branch.company_id` and `branch_id = branch_id`. Returns value for that branch only.
- **All-branches:** Not supported. No endpoint that accepts “all” or omits `branch_id` and returns company-wide value.

### 3.3 If “all branches” were added later

- Filter should be: `WHERE company_id = session.company_id` (no `branch_id` filter).
- Grouping must keep full layer identity: `(company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)` so that layers from different branches are not merged. Current Python logic already uses this identity; it would remain correct if the filter were relaxed to company-only and rows from multiple branches were passed in.

### 3.4 Summary

| Mode | Supported | Notes |
|------|-----------|--------|
| Current branch | Yes | `branch_id` in path |
| Specific branch | Yes | Same; caller chooses branch |
| All branches | No | Would require new or extended endpoint and UI |

---

## 4. Dashboard Permission Enforcement

### 4.1 Card visibility (frontend)

- **File:** `frontend/js/utils/permissions.js`
- **Mechanism:** `canViewDashboardCard(cardId, branchId)`:
  - Loads permissions via `getUserPermissions(branchId)` → `API.users.getUserPermissions(userId, branchId)`.
  - For each card, requires one of the permissions in `DASHBOARD_CARD_PERMISSIONS[cardId]` (or admin).
- **Where used:** `dashboard.js` in `loadDashboard()`: for each card, `canViewDashboardCard(cardIds[i], branchId)`; if false, card is hidden (`display: none`).
- **Admin override:** If user has `users.edit` or `admin.manage_company`, they see all cards.

**Card → permissions (examples):**

- totalItems: `dashboard.view_items`, `items.view`
- totalStock: `dashboard.view_inventory`, `inventory.view`
- totalStockValue: `dashboard.view_stock_value`, `inventory.view`, `inventory.view_cost`
- todaySales / ordersProcessed: `dashboard.view_sales`, `sales.view_own`, `sales.view_all`
- todayGrossProfit: `inventory.view_cost`, `items.view_cost`, `admin.manage_company`
- expiringItems: `dashboard.view_expiring`, `inventory.view`
- orderBookPendingToday: `dashboard.view_order_book`, `orders.view`

So: **card visibility is enforced in the frontend** using branch-scoped permissions; hidden cards are not removed from DOM but not shown.

### 4.2 Branch restriction (who can see which branch)

- **Frontend:** Branch list comes from `API.branch.list(companyId)` (company-scoped). User only chooses among branches returned by the API (their company’s branches). No explicit “user_assigned_branches” check in the dashboard; it is assumed the branch list is already restricted.
- **Backend (inventory valuation):** `get_total_stock_value(branch_id)` loads the branch and uses `branch.company_id` for the query. It does **not** verify that `branch.company_id == request.state.effective_company_id` (or that the user is allowed to see that branch). So in principle a direct API call with another company’s `branch_id` could return that company’s data.
- **Backend (company API):** `get_branch(branch_id)` in `company.py` does enforce: `branch.company_id != effective_company_id` → 403. So branch-by-id for “branch resource” is protected; branch-scoped inventory endpoints do not reuse this check.

### 4.3 Where enforcement happens

| Check | Frontend | Backend |
|-------|----------|---------|
| Which cards are visible | Yes — `canViewDashboardCard` | No per-card check |
| Which branches user can select | Implicit — branch list is company-scoped | Yes — branch list by company |
| Branch belongs to user’s company (inventory APIs) | N/A | **Not enforced** in inventory (e.g. total-value) |
| Company on document/branch resource | N/A | Yes in company.get_branch and document helpers |

---

## 5. Dashboard Card Safety (Company / Branch)

### 5.1 Company and branch in dashboard requests

- **Company:** `CONFIG.COMPANY_ID` is used for items count, gross profit, order book. Backend resolves company from the authenticated user (e.g. effective_company_id) and/or document; inventory endpoints derive company from the requested branch.
- **Branch:** All branch-scoped KPIs use the single `branchId` from `getBranchIdForStock()`.

### 5.2 Backend enforcement today

- **Inventory (e.g. total-value, items-in-stock, expiring):** Filter by `branch_id` and `company_id = branch.company_id`. So response is for one branch and that branch’s company. **Gap:** No check that `branch.company_id == current user’s effective_company_id`; if an attacker sends another company’s branch_id, they could get that company’s data.
- **Sales (gross profit):** Uses `branchId`; backend should validate branch/company (not re-audited here).
- **Items count:** `API.items.count(CONFIG.COMPANY_ID)` — company-scoped; backend should validate company (not re-audited here).

### 5.3 Risk

- **Missing check:** Inventory branch-scoped endpoints (e.g. `get_total_stock_value`, `get_items_in_stock_count`, `get_expiring_count`, `get_expiring`) do not ensure `branch.company_id == effective_company_id`. Rely on frontend only sending branch IDs from the company-scoped branch list.

---

## 6. Risk Summary

| Risk | Severity | Notes |
|------|----------|--------|
| No index on full layer identity | Low | Current query is filter-heavy; acceptable for moderate ledger size; optional composite index recommended if ledger grows. |
| No “all branches” in UI or API | N/A | By design; not a defect. |
| Dashboard shows unauthorized branch data | Medium | If API called with another company’s branch_id, inventory endpoints can return that company’s data; frontend does not send such IDs. |
| Card visibility only in frontend | Low | Backend does not re-check per card; permissions are branch-scoped; acceptable if backend branch access is fixed. |
| Branch switching without permission check | Low | Branch list is company-scoped; no per-branch permission on dashboard; inventory endpoints do not validate branch vs user company. |

---

## 7. Minimal Corrections (Proposed)

### 7.1 (Optional) Add layer-identity index

If you want to optimize valuation (and possible future all-branches) queries:

```sql
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_layer_identity
ON inventory_ledger (company_id, branch_id, item_id, batch_number, expiry_date, unit_cost);
```

No change to application logic.

### 7.2 (Recommended) Enforce branch belongs to user’s company

In `get_total_stock_value` (and similarly in `get_items_in_stock_count`, `get_expiring_count`, `get_expiring`, and any other branch-scoped read in inventory API):

- After loading `branch`, ensure `branch.company_id == request.state.effective_company_id` (or `get_effective_company_id_for_user(db, user)`).
- If not, raise `403` (e.g. “Access denied to this branch”) so that only branches of the user’s company are allowed.

This matches the check already used in `company.get_branch(branch_id)` and prevents cross-company data leakage even if the API is called with an arbitrary branch_id.

### 7.3 No change

- FIFO, cost adjustments, batch valuation, ledger structure: no change.
- Dashboard UI: no refactor; “all branches” remains out of scope unless product requirements change.
- Permission model: no change; only add backend branch–company check for inventory endpoints.

---

## 8. Summary Table

| Item | Finding |
|------|--------|
| **Indexes on inventory_ledger** | 7 indexes; none on full `(company_id, branch_id, item_id, batch_number, expiry_date, unit_cost)`. Optional composite recommended. |
| **Valuation query efficiency** | Filter supported by existing indexes; grouping in app; acceptable; index would help at scale. |
| **Dashboard branch filter** | Single branch from BranchContext/CONFIG/localStorage; no dashboard dropdown; no “All branches.” |
| **API branch parameter** | Always one `branchId` per request; no “all” mode. |
| **All-branches backend** | Not implemented; if added, keep layer identity including `branch_id` in grouping. |
| **Card visibility** | Frontend: `canViewDashboardCard` with `getUserPermissions(branchId)`. Backend: no per-card check. |
| **Branch restriction** | Frontend: branch list company-scoped. Backend: inventory endpoints do not validate branch vs user company. |
| **Proposed fixes** | (1) Optional: add `idx_inventory_ledger_layer_identity`. (2) Recommended: validate `branch.company_id == effective_company_id` in branch-scoped inventory endpoints. |
