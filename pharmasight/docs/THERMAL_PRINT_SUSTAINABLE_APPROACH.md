# Thermal (80mm) Print – Sustainable Approach

## Why it keeps breaking

1. **Default is wrong for receipt printers**  
   App default is **Regular (A4)**. When the user prints an invoice to an **80mm thermal** (e.g. XP-80), the browser sends an A4-sized page. The OS/printer then **scales that whole page** onto 80mm paper → **tiny text** and **big empty margins**. So the problem is not “thermal CSS is bad” but “thermal layout is often not used at all” because the default is A4.

2. **One setting, many places**  
   Print layout comes from `CONFIG.PRINT_TYPE` (and company-level print_config). If that isn’t loaded yet, or the user never changed it from “Regular”, every print is A4. So “we tried many times” usually means: thermal layout exists, but the app is still in Regular mode when they hit Print.

3. **Thermal layout itself**  
   When thermal *is* used we have:
   - `@page { size: 80mm auto; margin: 0 }` (good)
   - Body `max-width: 72mm` (80 − 8) and padding in **px** (inconsistent on different printers)
   - **9px** font (too small on many thermals)
   - Header/footer use **px** margins (e.g. 6px, 8px) which can look like “large” blank space on thermal rolls

4. **No single source of truth for “receipt size”**  
   We don’t declare “this document is 80mm wide” in a way that’s robust across browsers and drivers. So some setups still get scaling/margins from the driver.

---

## Sustainable approach (no complex printer setup)

### 1. Default to thermal for receipts/invoices

- **Change default** so `PRINT_TYPE` is **`'thermal'`** (80mm) for the app and for company print_config when not set.
- **Rationale**: Most pharmacy till receipts are printed on 80mm thermal. If someone needs A4, they switch to “Regular Printer” once in Settings. Then “anywhere the user is” (new device, new branch, cleared cache) they get a receipt-sized document by default and don’t need to configure the printer.

### 2. One receipt size: 80mm-native

- **Always** use a layout that is **80mm-wide** when in thermal mode:
  - `@page { size: 80mm auto; margin: 0; }`
  - Content width **80mm** (or 76mm with 2mm horizontal margin in CSS). No extra side margins from our side.
- Use **mm** (not px) for all print margins and padding in thermal so behaviour is consistent across printers and DPIs.
- **Font size**: Use **10pt** (or 9pt minimum) for body so it stays readable on 80mm; avoid 9px so it doesn’t look “so small” on thermal.

### 3. Minimal header and footer (reduce paper waste)

- **Header**: One compact block (e.g. company name one line, address one line, “Sales Invoice” one line). Use **2mm** top/bottom padding in thermal (not 6px/8px).
- **Footer**: One or two lines (e.g. message + “Served by / Date”). Same **2mm** spacing.
- **No** large borders or extra vertical padding in thermal. This keeps the receipt short and reduces waste.

### 4. Don’t rely on “Remove margins” or browser settings

- For thermal, **always** use minimal margins (0 or 2mm) in our CSS. Don’t depend on the user ticking “Remove margins” for correct layout.
- Keep the checkbox for “Remove margins” as an extra option only; thermal should already be tight by default.

### 5. Company-level settings as single source of truth

- Print settings (thermal vs regular, 80mm, theme, what to show) are already stored at **company** level. Ensure they load **before** the first print (e.g. on app init or when opening Sales). Then all users get the same behaviour without per-device or per-printer setup.

### 6. Clear feedback in the print window

- Show **“Layout: Thermal (80mm)”** or **“Layout: Regular (A4)”** in the print preview bar so the user knows what they’re getting.
- If they see “Regular (A4)” but are using XP-80, the existing hint (“For receipt printers… switch to Thermal”) stays; with thermal as default, most users will already see “Thermal (80mm)”.

---

## What we will change in code

1. **Default**  
   - In `config.js`: set `PRINT_TYPE: 'thermal'` (and ensure company print_config defaults to thermal when key is missing).

2. **Thermal CSS (invoice + quotation)**  
   - Use **mm** for all thermal spacing: body padding 2mm, header/footer margin/padding 2mm.
   - Set thermal body **font-size to 10pt** (or 9pt), and ensure table/footer use the same unit (pt) so it scales predictably.
   - Keep `@page { size: 80mm auto; margin: 0 }` and body width 80mm (or 76mm with 2mm margin).

3. **Header/footer**  
   - In thermal, reduce header bottom margin and footer top margin to **2mm**; use single-line blocks where possible.

4. **Load print config before first print**  
   - Ensure company print settings are loaded when the app or Sales module loads so the first print already uses thermal (80mm) if that’s the default.

Result: **One predictable behaviour** – receipt print is 80mm by default, with readable font and minimal header/footer, so the user doesn’t need complex printer setup anywhere.
