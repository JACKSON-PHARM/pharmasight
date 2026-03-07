# Add row stability verification

## 1. setItems() does not call render()

**Verified.**  
- **Lines 2260–2284:** `setItems()` only calls `this.renderItemsTable()` (line 2267) and `this.attachEventListeners()` (line 2268). It does **not** call `this.render()`.

## 2. setItems() does not call renderAddRow()

**Verified.**  
- There is no `renderAddRow` method in the component. `setItems()` does not call it.

## 3. renderItemsTable() does not touch add row section

**Verified.**  
- **Lines 676–679:** `renderItemsTable()` only:
  - Queries `this.mountEl.querySelector('#' + this.instanceId + '_items_table')`
  - Replaces that table node: `table.outerHTML = this.getItemsTableHtml()`
- The add row lives under `id="${this.instanceId}_add_row_section"` (see line 376). That ID is never queried or modified in `renderItemsTable()`. Only the items table is updated.

## 4. Code paths triggered by API responses that call render()

**Issue found (fixed):**

- **Add-item API completion:** When the user clicks Add, `commitAddRow()` runs and calls `this.onAddItem(data)`. The returned promise is stored and:
  - **setTimeout(..., 0)** runs after the parent’s optimistic update and previously called `self.render()`.
  - **p.finally(...)** runs when the add-item API settles and previously called `this.render()`.

- **Update-line API completion:** When the user updates an existing line, `commitAddRow()` calls `this.onUpdateItem(idx, ...)`. The promise’s **p.finally()** previously called `this.render()` when the API settled.

In all cases, the **API response** (promise settlement) triggered a full `render()`, which **rebuilt the add row** and caused the second reset (search/dropdown/focus loss).

**Fix applied:**  
- In the **add-item** flow: replaced `render()` in `setTimeout(0)` and in `p.finally()` with `updateAddRowButtonOnly()`.  
- In the **update-line** flow: replaced `render()` in `onUpdateItem` promise’s `p.finally()` with `updateAddRowButtonOnly()`.  
- `updateAddRowButtonOnly()` only updates the Add button’s label and disabled state inside the existing add row DOM. The add row is no longer rebuilt when any of these API responses complete.

**Other render() call sites (not API-response driven):**

- **Line 2231:** Before `onAddItem(data)` — user just clicked Add; shows “Adding...” (intentional full render before async call).
- **Line 2239:** After clearing `addRowItem` so user can search next — intentional full render to show cleared add row.
- **Lines 718, 753, 773, 1592, 1614, 1627, 2025, 2205, 2211, 2215, 2310, 2332, 2341, 2491, 2622, 2636:** All are driven by user actions (sales type change, double-click row, search input, prefillAddRowSearch, clearRowSelection, etc.) or initial mount. None are triggered by “add-item API response” or generic table sync.

**Summary:** After the fix, no code path triggered by the add-item API response (or by `setItems()` from the parent) calls `render()`, so the add row is never rebuilt during table sync or when the API returns.
