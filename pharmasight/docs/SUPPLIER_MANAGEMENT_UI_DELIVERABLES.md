# Supplier Management UI – Implementation Deliverables

## New UI Routes List

| Route (Hash) | Page | Description |
|--------------|------|-------------|
| `#purchases` | Purchases (default: Orders) | Main purchases container |
| `#purchases-orders` | Purchase Orders | Purchase orders list |
| `#purchases-order-book` | Order Book | Order book view |
| `#purchases-credit-notes` | Credit Notes | Credit notes list |
| **Supplier module** (grouped in sidebar) | | |
| `#purchases-supplier-dashboard` | Supplier Dashboard | Company-wide metrics, quick links |
| `#purchases-invoices` | Supplier Invoices | Supplier invoices list |
| `#purchases-suppliers` | Suppliers Management | Suppliers list with Outstanding, Overdue, Status badges |
| `#purchases-supplier-payments` | Supplier Payments | Global supplier payments across company |
| `#purchases-suppliers-{supplier_id}` | Supplier Detail | Dashboard with Overview, Profile, Invoices, Payments, Returns, Ledger, Statement, Aging, Metrics |

---

## Component Tree Summary

```
loadPurchases()
└── loadPurchaseSubPage(subPage)
    ├── orders        → renderPurchaseOrdersPage()
    ├── order-book    → renderOrderBookPage()
    ├── invoices      → renderSupplierInvoicesPage()
    ├── credit-notes  → renderCreditNotesPage()
    ├── suppliers     → renderSuppliersPage()
    │                   └── loadSuppliers() → listEnriched
    │                   └── renderSuppliersTable() [enhanced columns, badges, row click]
    ├── suppliers-{id}→ renderSupplierDetailPage(supplierId)
    │                   ├── renderSupplierSummaryCards()
    │                   └── renderSupplierTabContent(supplierId, tab)
    │                       ├── Overview  → renderSupplierOverviewTab()
    │                       ├── Profile   → renderSupplierProfileTab()
    │                       ├── Invoices  → renderSupplierInvoicesTab()
    │                       ├── Payments  → renderSupplierPaymentsTab()
    │                       ├── Returns   → renderSupplierReturnsTab()
    │                       ├── Ledger    → renderSupplierLedgerTab() [date range + limit]
    │                       ├── Statement → renderSupplierStatementTab() [date range + reconciliation]
    │                       ├── Aging     → renderSupplierAgingTab()
    │                       └── Metrics   → renderSupplierMetricsTab()
    └── supplier-payments → renderSupplierPaymentsPage()
```

**Modals:**
- `showNewPaymentModal(supplierId)` – **Full allocation UI**: payment date, method, reference, amount; table of unpaid invoices with checkbox + allocate amount; total allocated / unallocated; validation; submits with `allocations` array.
- `showAllocatePaymentModal(invoiceId, supplierId)` – Opens New Payment modal (same as above).
- `showNewReturnModal(supplierId, linkedInvoiceId?)` – **Full return flow**: supplier (read-only), link invoice (optional), return date, reason, item search → add lines (qty, unit cost); save → Pending; Approve from Returns tab.

---

## Reused Components List

| Component | Source | Used In |
|-----------|--------|---------|
| `showModal` / `closeModal` | utils.js | New Payment, Allocate Payment, New Return modals |
| `showToast` | utils.js | All actions, errors, confirmations |
| `formatCurrency` / `fmt()` | purchases.js (local) | KES formatting throughout |
| Card layout, `.card`, `.btn`, `.badge` | style.css | All supplier pages |
| Table styling (`.table`, `<table>`) | Existing purchases tables | Suppliers, Invoices, Payments, Returns, Ledger |
| Supplier search dropdown | purchases.js `renderSupplierSearchResults` | Create Invoice, (future: New Return item search) |
| `TransactionItemsTable` | purchases.js | Create Invoice (for Record New Invoice flow) |
| `loadPurchaseSubPage` / `switchPurchaseSubPage` | purchases.js | Navigation to Suppliers, Supplier detail, Invoice create |
| `updatePurchaseSubNavActiveState` | purchases.js | Highlights "Suppliers" when on list or detail |
| `renderPurchaseOrdersShell` / invoice shell patterns | purchases.js | Layout consistency |
| `batchSupplierInvoice` | purchases.js | Invoice posting (unchanged) |
| `viewSupplierInvoice` / `editSupplierInvoice` | purchases.js | Invoices tab "View" action |

**Not duplicated:** Inventory movement UI, stock adjustment flows, item movement components.

---

## Performance Risks

| Risk | Mitigation | Status |
|------|------------|--------|
| **Enriched suppliers list** – multiple aggregates per supplier | Backend `GET /api/suppliers/enriched-list` does single query with subqueries; indexed. | OK |
| **Ledger pagination** | Backend: `limit` (default 200), `offset`; frontend: date range filter, limit 100 per load. | Done |
| **Payments/Returns** | Backend: `limit` (100), `offset`; frontend uses default limit. | Done |
| **Statement print** | Single API call; server-calculated. | OK |
| **Aging report** | Per-supplier filter in API; small payload. | OK |
| **Multiple tab API calls** | Tabs lazy-load on click; no prefetch. | OK |
| **Hash routing** | `#purchases-suppliers-{uuid}` parses correctly; no deep re-renders. | OK |

---

## UX Improvement Suggestions

| Suggestion | Priority | Notes |
|------------|----------|-------|
| **Payment allocation modal** | Done | Full UI in New Payment: unpaid invoices table, allocate amount per row, total allocated/unallocated, validation, submit with `allocations`. |
| **New Return modal** | Done | Supplier, optional link invoice, return date, reason, item search → lines (qty, unit cost); save Pending; Approve from Returns tab. |
| **Record New Invoice pre-fill** | Done | `openCreateInvoiceWithSupplier(supplierId)`; create-invoice page pre-fills supplier. |
| **Overview + Metrics tabs** | Done | Overview: outstanding, overdue, this month purchases/payments/returns, last payment, avg days. Metrics: company + supplier slice. |
| **Statement reconciliation** | Done | Statement tab: date range; shows Statement Closing Balance + System Outstanding; note if mismatch to investigate via Ledger. |
| **Ledger/Statement date range** | Done | Ledger and Statement have From/To date inputs and Apply. |
| **Loading skeletons** | Medium | Add skeleton placeholders for tabs/tables instead of "Loading...". |
| **Empty state illustrations** | Low | SVG/icon for "No invoices", "No payments", etc. |
| **Confirmation modals** | Medium | "Approve return?" confirmation present. |
| **Back button from supplier detail** | Done | "Back to suppliers" button in header. |
| **Supplier name in breadcrumb** | Low | Show supplier name when on detail page. |
| **Keyboard shortcuts** | Low | e.g. Esc to close modals. |

---

## Validation Checklist (Post-Implementation)

After implementation, verify:

| Check | How to Verify |
|-------|----------------|
| **Supplier balance updates after payment** | Create payment → refresh supplier detail → Outstanding/Overdue reflects new balance. |
| **Aging recalculates correctly** | After payment allocation, aging buckets update (0–30, 31–60, etc.). |
| **Overdue badge updates automatically** | Invoice becomes overdue → supplier list shows red "Overdue" badge. |
| **Credit balance displays correctly** | Overpay supplier → Outstanding < 0 → blue "Credit Balance" badge. |
| **Statement matches ledger** | Compare Statement tab rows with Ledger tab; totals and running balance consistent. |
| **Multi-tenant isolation** | Switch company → suppliers/payments/returns show only that company's data. |
| **Branch filter respected** | Payments, Ledger, aging filtered by `branch_id` from session. |
| **Posted invoices not editable** | BATCHED invoice "View" → no edit; "Allocate Payment" only if balance > 0. |
| **Payments not deletable** | No delete button on payments (per spec). |
| **Credited returns not editable** | Return with status "Credited" → Approve disabled. |
| **Currency format** | All amounts show "KES X,XXX.XX". |
| **Toast on actions** | Payment created, return approved → success toast. |
| **Row click opens supplier detail** | Suppliers list row → `#purchases-suppliers-{id}`. |
| **Supplier Payments row click** | Navigates to supplier detail. |

---

## Completion Phase (Reviewer Requirements)

### Implemented

| Requirement | Implementation |
|-------------|----------------|
| **Full Payment Allocation UI** | New Payment modal loads unpaid (BATCHED, balance > 0) invoices; table with Invoice, Due Date, Total, Balance, checkbox, Allocate amount; bottom summary: Payment Amount, Total Allocated, Unallocated; warning if unallocated; validation (alloc ≤ balance, total alloc ≤ amount); submit with `allocations` array. |
| **Full New Return flow** | Modal: supplier (read-only), link invoice (optional dropdown), return date, reason; item search (API.items.search) → add lines with qty, unit cost; sync from DOM on submit; `createReturn` with lines; Approve from Returns tab. |
| **Pagination** | Backend: `GET /payments`, `/returns`, `/ledger` accept `limit`, `offset`. Frontend: Ledger uses `limit: 100`, date_from/date_to; Payments/Returns use default limit. |
| **Overview tab** | Outstanding, Overdue, This Month Purchases/Payments/Returns, Last Payment Date, Avg Payment Days (supplier-scoped where applicable). |
| **Metrics tab** | Company metrics (month) + this supplier’s slice (purchases, outstanding, overdue). |
| **Date range Ledger/Statement** | Ledger: From/To inputs, Apply; Statement: From/To, Apply. |
| **Reconciliation** | Statement tab shows Statement Closing Balance and System Outstanding (from aging); note if mismatch to investigate via Ledger. |
| **Real-time balance updates** | After payment or return approve, `refreshSupplierDetailAfterAction(supplierId)` refreshes summary cards and current tab. |
| **Invoice-based Return** | Invoices tab has "Return" button per row; `showNewReturnModal(supplierId, inv.id)` pre-links invoice. |
| **Header actions** | Supplier detail header: New Payment, New Return, Record Invoice. |

### API / Backend

- **New/updated API usage:** `listPayments`, `listReturns`, `listLedger` now pass `limit`, `offset` (and `date_from`/`date_to` where supported). No new endpoints; existing `createPayment` (with `allocations`), `createReturn`, `approveReturn` used.
- **Pagination strategy:** Ledger: first 100 entries for selected date range; no "Load more" yet. Payments/Returns: default 100; frontend could add offset for "Load more" later.

### UX summary

- Single New Payment modal with allocation table; no separate “allocate later” flow.
- New Return: one modal for create (Pending); approval and stock/ledger effects from Returns tab.
- Overview as first tab for at-a-glance supplier health.
- Statement clearly shows closing balance vs system outstanding for reconciliation.

### Edge case / risks

| Risk | Mitigation |
|------|------------|
| Return line with qty > stock | Backend rejects on Approve with "Insufficient stock"; frontend shows stock in item search and blocks adding item with 0 stock. |
| Payment total allocated > amount | Frontend validation before submit; backend also validates. |
| Allocation to non-BATCHED invoice | Backend rejects; frontend only lists BATCHED with balance > 0. |
| Ledger very long | Date filter + limit 100; user can narrow range. |
| Statement vs aging slight mismatch | Possible if aging is point-in-time and statement is period-end; reconciliation note directs user to Ledger. |

---

## File Summary

| Area | Path |
|------|------|
| Frontend API | `frontend/js/api.js` – `suppliers.listEnriched`, `listPayments`, `createPayment`, `listReturns`, `approveReturn`, `listLedger`, `getAging`, `getMetrics`, `getStatement` |
| Frontend UI | `frontend/js/pages/purchases.js` – suppliers list, supplier detail, tabs, modals, Supplier Payments page |
| Nav/Routing | `frontend/js/app.js` – Purchases sub-nav, hash parsing for `purchases-suppliers-{id}` |
| Backend API | `backend/app/api/supplier_management.py`, `suppliers.py` |
| Docs | `docs/SUPPLIER_MANAGEMENT_IMPLEMENTATION_SUMMARY.md`, `docs/SUPPLIER_MANAGEMENT_UI_DELIVERABLES.md` |
