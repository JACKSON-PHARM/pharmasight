# PharmaSight Printing Architecture — Repo Scan Report

**Date:** March 2, 2025  
**Purpose:** Safe refactor to add QZ Tray ESC/POS thermal printing while preserving existing A4/browser printing.

---

## 1. `window.print()` Usage

| File | Line | Context |
|------|------|---------|
| `pharmasight/frontend/js/pages/inventory.js` | 2063 | `printCurrentStock()` — prints Current Stock table; sets `document.title` then calls `window.print()` |
| `pharmasight/frontend/js/pages/sales.js` | 3264 | Print button inside invoice print preview window: `onclick="window.print();"` |
| `pharmasight/frontend/js/pages/sales.js` | 3522 | Print button inside quotation print preview window: same pattern |
| `pharmasight/frontend/js/pages/purchases.js` | 2790 | Print button inside purchase order print preview window: `onclick="window.print();"` |
| `pharmasight/frontend/js/pages/purchases.js` | 2709-2710 | PDF print path for approved PO: `printWindow.print()` |
| `pharmasight/frontend/js/pages/purchases.js` | 2851 | Dynamic PO print: `printWindow.print()` after 250ms |
| `pharmasight/docs/ITEM_MOVEMENT_REPORT_PLAN.md` | 233 | Docs only — planned `window.print()` on report container |

**Summary:** `window.print()` is triggered either directly on the current page (inventory) or on a newly opened print preview window (sales invoice, quotation, purchase order).

---

## 2. `@media print` CSS Rules

| File | Line | Context |
|------|------|---------|
| `pharmasight/frontend/css/style.css` | 1779 | Item Movement Report: `.item-movement-report-doc` print styles |
| `pharmasight/frontend/js/pages/sales.js` | 3244, 3522 | Inline in `generateInvoicePrintHTML` / `generateQuotationPrintHTML`: `${pageStyle}` |
| `pharmasight/frontend/js/pages/purchases.js` | 2765 | Inline in `printPurchaseOrder`: `${pageStyle}` |
| `pharmasight/frontend/js/pages/settings.js` | 2319 | Print settings live preview: `${pageStyle}` |
| `pharmasight/backend/app/api/stock_take.py` | 207, 218 | Stock Take Recording Sheet HTML: `@media print` for color-adjust and `.no-print` |

---

## 3. `@page` CSS Rules

| File | Line | Context |
|------|------|---------|
| `pharmasight/frontend/js/pages/sales.js` | 3177, 3201 | Invoice: thermal `@page { size: 80mm auto }` vs A4 `@page { size: A4 }` |
| `pharmasight/frontend/js/pages/sales.js` | 3463, 3484 | Quotation: same thermal vs A4 logic |
| `pharmasight/frontend/js/pages/purchases.js` | 2728, 2741 | Purchase order: same thermal vs A4 logic |
| `pharmasight/frontend/js/pages/settings.js` | 2262, 2271 | Print settings preview |

---

## 4. Print Buttons

| Location | Trigger | Behavior |
|----------|---------|----------|
| Sales — invoice list row | `window.printSalesInvoice('${invoice.id}')` | Opens print layout modal → prints invoice |
| Sales — invoice view | `window.printSalesInvoice('${invoiceId}')` | Same |
| Sales — batch & print | `window.batchSalesInvoice(..., this)` | Batch + print flow |
| Sales — post-sale confirm | `if (confirm('Print receipt?')) await printSalesInvoice(invoiceId)` | Optional print after sale |
| Sales — print preview window | `onclick="window.print();"` | Print button in opened window |
| Quotations | `window.printQuotation(quotationId)` | Opens layout modal → prints quotation |
| Purchases — order row | `window.printPurchaseOrder('${orderId}')` | Layout modal → prints PO |
| Purchases — order view | `window.printPurchaseOrder('${order.id}')` | Same |
| Purchases — print preview window | `onclick="window.print();"` | Print button in opened window |
| Inventory — Current Stock | `printCurrentStock()` | Direct `window.print()` on table container |

---

## 5. Receipt & Invoice Components

| Component | File | Function | Notes |
|-----------|------|----------|-------|
| Sales invoice print | `sales.js` | `printSalesInvoice()`, `generateInvoicePrintHTML()` | Fetches invoice, builds HTML, opens window, calls `window.print()` |
| Quotation print | `sales.js` | `printQuotation()`, `generateQuotationPrintHTML()` | Same pattern |
| Purchase order print | `purchases.js` | `printPurchaseOrder()` | Builds HTML inline, opens window, calls `window.print()`; uses stored PDF if approved |
| Branch receipts | `inventory.js` | Branch transfer/receipt UI | **Not** print receipts — internal inventory docs |
| Stock take sheet | `stock_take.py` | Backend-generated HTML | Served as HTML; user prints via browser |

---

## 6. User Print Preferences

| Storage | Key / Field | Source |
|---------|-------------|--------|
| **DB (company_settings)** | `print_config` | `GET/PUT /companies/{id}/settings?key=print_config` |
| **localStorage** | `pharmasight_config` | Persists `PRINT_TYPE`, margins, theme, etc. |
| **CONFIG object** | `PRINT_TYPE`, `PRINT_PAGE_WIDTH_MM`, etc. | Loaded from `loadCompanyPrintSettings()` and `loadConfig()` |

**Print-related CONFIG keys:**
- `PRINT_TYPE`: `'thermal'` \| `'normal'` (layout: 80mm vs A4)
- `PRINT_REMOVE_MARGIN`, `PRINT_COPIES`, `PRINT_AUTO_CUT`
- `PRINT_THEME`, `PRINT_PAGE_WIDTH_MM`
- `PRINT_THERMAL_HEADER_FONT_PT`, `PRINT_THERMAL_ITEM_FONT_PT`
- `PRINT_HEADER_COMPANY`, `PRINT_HEADER_ADDRESS`, etc.
- `PRINT_ITEM_SNO`, `PRINT_ITEM_CODE`, etc.

---

## 7. Print Service Utilities

| File | Function | Purpose |
|------|----------|---------|
| `pharmasight/frontend/js/utils.js` | `choosePrintLayout()` | Modal: Thermal (80mm) \| Normal (A4) \| Cancel; returns `'thermal' \| 'normal' \| null` |
| `pharmasight/frontend/js/config.js` | `loadCompanyPrintSettings()` | Fetches `print_config` from API, merges into CONFIG |
| `pharmasight/frontend/js/config.js` | `saveCompanyPrintSettings()` | Saves CONFIG to `print_config` |
| `pharmasight/frontend/js/config.js` | `buildPrintConfigForApi()` | Serializes CONFIG for API |

---

## 8. Printer Type Determination

| Factor | How determined |
|--------|----------------|
| Layout (thermal vs A4) | `choosePrintLayout()` modal **or** `CONFIG.PRINT_TYPE` when modal skipped |
| Company defaults | `loadCompanyPrintSettings()` → `print_config` from DB |
| Per-print override | `printSalesInvoice(id, 'thermal')` / `printQuotation(id, 'normal')` — second arg overrides |

**Thermal vs A4 distinction:** Already exists via `CONFIG.PRINT_TYPE` (`'thermal'` \| `'normal'`). Both flows use `window.print()`; only CSS/layout differs (80mm vs A4).

**ESC/POS / QZ Tray:** Not present. All printing is browser-based.

---

## 9. Document Types & Print Flows

| Document | Entry point | Layout selection | Output |
|----------|-------------|------------------|--------|
| Sales invoice | `printSalesInvoice(invoiceId, printType?)` | `choosePrintLayout()` or `CONFIG.PRINT_TYPE` | New window with HTML → `window.print()` |
| Quotation | `printQuotation(quotationId, printType?)` | Same | Same |
| Purchase order | `printPurchaseOrder(orderId, printType?)` | Same; approved PO may use PDF URL | Same or PDF window |
| Current stock | `printCurrentStock()` | N/A (always full page) | `window.print()` on `#currentStockTableWrap` |
| Stock take sheet | Backend HTML | N/A | User opens URL, Ctrl+P |

---

## 10. What Must NOT Be Changed

- Existing invoice JSX/layout logic
- Existing CSS print styling (`@media print`, `@page`)
- Existing A4 PDF logic (including approved PO PDF path)
- Tax/totals logic
- Sale completion logic
- `window.print()` — must remain; A4 path continues to use it
- Default behavior for existing users

---

## 11. Recommended Refactor Scope

1. **Add** `printService.js` — abstraction with `printDocument({ type, mode, data })`
2. **Add** `thermalPrinter.js` — QZ Tray ESC/POS (`connectPrinter()`, `printReceipt()`)
3. **Add** QZ Tray CDN script (no build changes)
4. **Add** optional `PRINTER_MODE`: `'A4'` \| `'THERMAL'` (default: existing behavior)
5. **Route** print triggers through `printService.printDocument()`; A4 mode keeps current `window.print()` flow
6. **Leave** `generateInvoicePrintHTML`, `generateQuotationPrintHTML`, purchase order HTML generation **unchanged** for A4
7. **Leave** inventory `printCurrentStock()` and stock take backend **unchanged** (not in scope)

---

## 12. Refactor Plan (Implemented)

### Files Created
- `pharmasight/frontend/js/services/printService.js` — Print abstraction; routes A4 → `window.print()`, THERMAL → QZ Tray
- `pharmasight/frontend/js/services/thermalPrinter.js` — QZ Tray ESC/POS; `connectPrinter()`, `printReceipt()`, `buildEscPosReceipt()`

### Files Modified
- `pharmasight/frontend/index.html` — Added QZ Tray CDN, thermalPrinter.js, printService.js
- `pharmasight/frontend/js/config.js` — Added PRINTER_MODE, persistence
- `pharmasight/frontend/js/pages/settings.js` — Print output (A4/Thermal) UI, _setPrinterMode
- `pharmasight/frontend/js/pages/sales.js` — printSalesInvoice, printQuotation route through PrintService when THERMAL
- `pharmasight/frontend/js/pages/purchases.js` — printPurchaseOrder routes THERMAL through PrintService

### Logic
- **A4 mode** (default): Existing flow — open HTML, window.print(). No layout changes.
- **THERMAL mode** (opt-in): When CONFIG.PRINTER_MODE === 'THERMAL' and layout thermal, use QZ Tray. On failure, fall back to browser thermal for invoice/quotation.
- ESC/POS: Init `\x1B\x40`, Center `\x1B\x61\x01`, Left `\x1B\x61\x00`, Bold `\x1B\x45\x01/00`, Cut `\x1D\x56\x41\x10`
