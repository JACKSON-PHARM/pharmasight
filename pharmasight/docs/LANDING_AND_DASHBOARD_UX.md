# Landing Page & On-Demand Dashboard UX

## Summary

PharmaSight now uses a **lightweight landing page** as the default home and an **on-demand heavy dashboard** so that login and refresh stay fast; heavy metrics load only when the user opens the Dashboard and clicks **Apply**.

## 1. Lightweight Landing Page (`#landing`)

- **Route:** `#landing` (default when hash is empty after login).
- **Behavior:**
  - Shows welcome message and current branch name.
  - Optional quick stat: **Pending orders (today)** — one lightweight call to order-book today-summary (count only) when branch and company are set.
  - **Navigation tiles** to: Dashboard, Inventory, Orders/Sales, Purchases & Transfers, Reports.
- **Queries:** At most one optional API call (order book today summary count). No sales, inventory, or gross-profit calls on load.
- **Files:** `frontend/index.html` (landing section), `frontend/js/pages/landing.js`, `frontend/css/style.css` (landing-* classes).

## 2. Heavy Dashboard (`#dashboard`)

- **Route:** `#dashboard`.
- **Behavior:**
  - **Date range selector:** Today, Yesterday, This Week, Last Week, This Month, Last Month, This Year, Last Year, Custom (with start/end date inputs).
  - **Apply button:** Metrics are fetched **only when the user clicks Apply**. No automatic fetch on page load.
  - **Metrics:** Sales (for range), Orders processed (invoice count), Gross profit & margin, plus branch KPIs: items count, unique items in stock, stock value, expiring soon, order book pending (today). All of these load together on Apply.
- **Caching:**
  - **Range data** (sales, gross profit, orders processed): cached by `branchId + preset + startDate + endDate`; TTL 2 minutes.
  - **KPIs** (items, stock value, expiring, order book): cached by `branchId`; TTL 2 minutes.
  - Revisiting the dashboard with the same range (or same branch for KPIs) within TTL reuses cache and avoids refetch.
- **Files:** `frontend/index.html` (dashboard section with toolbar), `frontend/js/pages/dashboard.js`, `frontend/css/style.css` (dashboard-toolbar, dashboard-preset, etc.).

## 3. Backend Change

- **Sales API** (`backend/app/api/sales.py`): Added **yesterday** to `_resolve_date_range` and to the gross-profit endpoint preset description so the dashboard can use “Yesterday” as a preset.

## 4. Routing & Defaults

- **Default route:** Empty hash defaults to `landing` (not `dashboard`).
- **After branch selection:** `handleBranchSelected` sets `#landing` and runs `startAppFlow()` so the user lands on the landing page.
- **Sidebar:** First item is **Home** (`#landing`), second is **Dashboard** (`#dashboard`). App routes list includes `landing`.
- **Auth redirect:** Authenticated users trying to open an auth page are redirected to `landing` (not dashboard).
- **Fallback:** If a requested app page is not found, the app shows the landing page.

## 5. What Was Not Changed

- **Orders, Inventory, Branch Transfers, Reports:** All existing flows and permissions are unchanged.
- **Session and branch scope:** Branch context and permissions (e.g. `canViewDashboardCard`, sales view own/all) are unchanged; dashboard and landing both use the same branch and permission checks.
- **Modals:** Order book pending modal, Expiring soon modal, CSV export, and “Open Order Book” / “Open Financial Reports” from dashboard still work as before.

## 6. Test Checklist

- [ ] **Landing loads instantly:** No heavy queries on login or refresh; at most one order-book count call.
- [ ] **Navigation tiles:** Home, Dashboard, Inventory, Sales, Purchases, Reports open the correct pages.
- [ ] **Dashboard:** Opening `#dashboard` shows the toolbar and placeholders (“—”); no metrics request until **Apply** is clicked.
- [ ] **Apply:** Selecting a date range and clicking Apply loads and displays sales, orders processed, gross profit, and KPIs; skeleton/loading state appears during fetch.
- [ ] **Caching:** Changing range and clicking Apply fetches; switching back to the same range (or revisiting dashboard with same range) within 2 minutes uses cache (no duplicate network requests for same range/branch).
- [ ] **Custom range:** Choosing “Custom” and entering start/end dates then Apply uses the backend custom date range.
- [ ] **Existing flows:** Orders, Inventory, Branch Transfers (e.g. Purchases → order book / transfers), Reports, and Settings still work and remain branch-scoped.
- [ ] **Session/branch:** After switching branch, landing shows the new branch name; dashboard Apply uses the current branch and cache is keyed by branch so no cross-branch data.

## 7. Files Touched

| Area | Files |
|------|--------|
| Landing | `frontend/index.html`, `frontend/js/pages/landing.js`, `frontend/css/style.css` |
| Dashboard | `frontend/index.html`, `frontend/js/pages/dashboard.js`, `frontend/css/style.css` |
| Routing / defaults | `frontend/js/app.js` |
| Permissions | `frontend/js/utils/permissions.js` (ordersProcessed card) |
| Backend | `backend/app/api/sales.py` (yesterday preset) |
| Fallbacks / post-setup | `frontend/js/pages/branch_select.js`, `frontend/js/pages/login.js`, `frontend/js/pages/setup.js`, `frontend/index.html` (error handler) |

## 8. Test Results (Manual Verification)

Run through the checklist in §6 after deploying:

- **Landing:** Login or refresh with branch selected → landing page appears; no dashboard API calls in network tab until user opens Dashboard and clicks Apply.
- **Navigation:** Home, Dashboard, Inventory, Sales, Purchases, Reports open correct pages; sidebar active state matches current page.
- **Dashboard:** Open `#dashboard` → toolbar and placeholders only; click Apply → metrics load; change range and Apply again → new data; same range within 2 min → cached (no extra requests).
- **Existing flows:** Create/edit orders, inventory, branch transfers, reports, settings — all unchanged and branch-scoped.
