/**
 * TransactionItemsTable Component - Enhanced with Vyapar-style inline search
 * 
 * Features:
 * - Item search embedded in table row (Vyapar-style)
 * - Inline suggestions dropdown below input
 * - Create item option when item doesn't exist
 * - Real-time calculations
 * - Keyboard navigation
 */

(function() {
    'use strict';
    
    // Component instance registry
    const instances = new Map();
    let instanceCounter = 0;
    
    /**
     * TransactionItemsTable Constructor
     */
    function TransactionItemsTable(mountElOrId, options) {
        // Handle two calling patterns
        if (typeof mountElOrId === 'object' && !mountElOrId.nodeType) {
            options = mountElOrId;
            mountElOrId = options.mountEl;
        }
        
        if (!options) options = {};
        if (!mountElOrId) {
            console.error('TransactionItemsTable: mountEl is required');
            return;
        }
        
        // Store configuration
        this.mountEl = typeof mountElOrId === 'string' 
            ? document.getElementById(mountElOrId) 
            : mountElOrId;
            
        if (!this.mountEl) {
            console.error('TransactionItemsTable: mountEl element not found');
            return;
        }
        
        // Generate unique instance ID
        this.instanceId = `trit_${++instanceCounter}`;
        instances.set(this.instanceId, this);
        
        this.mode = options.mode || 'purchase';
        this.context = options.context || null; // 'purchase_order' for PO-specific fields
        this.canEdit = options.canEdit !== undefined ? options.canEdit : true; // Edit permission
        this.itemsSource = options.items || options.itemsSource || [];
        // purchase_price / sale_price must come from API only (inventory_ledger); never from items table
        this.priceType = options.priceType || (this.mode === 'sale' ? 'sale_price' : 'purchase_price');
        this.onItemsChange = options.onItemsChange || null;
        this.onTotalChange = options.onTotalChange || null;
        this.onItemCreate = options.onItemCreate || null; // Callback for creating new items
        
        // Internal state
        this.items = this.normalizeItems(this.itemsSource);
        this.searchTimeout = null;
        this.searchAbortController = null;
        this.activeSearchRow = null;
        this.activeSelectedItemRow = null; // Row showing "selected item" dropdown (details / search different / view full)
        this.inputDebounceTimeout = null; // For debouncing input events
        this.totalInputDebounce = null; // For debouncing total input (reverse calc)
        this.marginInputDebounce = null; // For debouncing margin input
        this._searchId = 0; // Incremented per search; used to ignore stale responses
        this._searchDebounceMs = 250; // Debounce so requests fire only after user pauses typing
        
        // Always ensure there's at least one empty row for adding new items
        // Check if the last item is empty, if not, add one
        const hasEmptyRow = this.items.length > 0 && 
            (!this.items[this.items.length - 1].item_id && 
             !this.items[this.items.length - 1].item_name);
        
        if (this.items.length === 0 || !hasEmptyRow) {
            this.items.push(this.createEmptyItem());
        }
        
        // Render
        this.render();
        this.attachEventListeners();
        // For sale/quotation: load cost and stock for rows restored from draft (no purchase_price/stock_display)
        if (this.mode === 'sale' || this.mode === 'quotation') {
            const self = this;
            setTimeout(function() {
                for (let i = 0; i < self.items.length; i++) {
                    const it = self.items[i];
                    if (it.item_id && (it.stock_display == null || (it.purchase_price == null && it.unit_price != null)))
                        self.loadUnitsForRow(i);
                }
            }, 400);
        }
        // Auto-focus on first ITEM NAME field after render
        this.autoFocusFirstItemField();
    }
    
    /**
     * Auto-focus on the first row's ITEM input field
     */
    TransactionItemsTable.prototype.autoFocusFirstItemField = function() {
        // Use setTimeout to ensure DOM is fully rendered
        setTimeout(() => {
            // Find the first row's ITEM search input (first column)
            const firstItemInput = document.querySelector(
                `#${this.instanceId}_tbody tr[data-item-index="0"] .item-search-input`
            );
            if (firstItemInput) {
                firstItemInput.focus();
                // Place cursor at end if there's any text
                if (firstItemInput.value) {
                    firstItemInput.setSelectionRange(firstItemInput.value.length, firstItemInput.value.length);
                }
            }
        }, 200); // Increased delay to ensure DOM is ready
    };
    
    /**
     * Normalize VAT rate to percentage (Kenya: DB/Excel may store 0.16; we use 16 for 16%).
     * Returns percentage for display and calculation: 0.16 -> 16, 16 -> 16, 0 -> 0.
     */
    TransactionItemsTable.prototype.vatRateToPercent = function(value) {
        if (value == null || value === '' || isNaN(parseFloat(value))) return 0;
        const v = parseFloat(value);
        if (v === 0) return 0;
        if (v > 0 && v <= 1) return v * 100;
        return v;
    };

    /**
     * Round to 2 decimal places for money/amounts (avoids 49.99994 display).
     * Returns number for calculations; use .toFixed(2) for display strings.
     */
    TransactionItemsTable.prototype.roundMoney = function(value) {
        if (value == null || value === '' || isNaN(parseFloat(value))) return 0;
        return Math.round(parseFloat(value) * 100) / 100;
    };

    /**
     * Create empty item row
     */
    TransactionItemsTable.prototype.createEmptyItem = function() {
        return {
            item_id: null,
            item_name: '',
            item_sku: '',
            item_code: '',
            unit_name: '',
            quantity: 1,
            unit_price: 0,
            discount_percent: 0,
            tax_percent: 0,
            total: 0,
            available_stock: null, // Available stock in selected unit (for sales mode)
            is_empty: true
        };
    };
    
    /**
     * Normalize items array
     */
    TransactionItemsTable.prototype.normalizeItems = function(items) {
        if (!Array.isArray(items)) return [];
        return items.map(item => {
            const normalized = {
                item_id: item.item_id || item.id || null,
                item_name: item.item_name || item.name || '',
                item_sku: item.item_sku || item.sku || '',
                item_code: item.item_code || item.code || '',
                unit_name: item.unit_name || item.unit || '',
                quantity: item.quantity || 1,
                unit_price: item.unit_price || item.price || 0,
                purchase_price: item.purchase_price || 0, // Cost per base (wholesale) unit
                unit_cost_used: item.unit_cost_used != null ? parseFloat(item.unit_cost_used) : null, // Cost per sale unit when from API (reload)
                discount_percent: item.discount_percent || 0,
                tax_percent: this.vatRateToPercent(item.tax_percent ?? item.vat_rate ?? 0),
                total: item.total || 0,
                available_stock: typeof item.available_stock === 'number' ? item.available_stock : null,
                is_empty: false
            };
            // Calculate nett and vat_amount for normalized items
            const subtotal = (normalized.quantity || 0) * (normalized.unit_price || 0);
            const discount = subtotal * ((normalized.discount_percent || 0) / 100);
            normalized.nett = subtotal - discount;
            normalized.vat_amount = normalized.nett * ((normalized.tax_percent || 0) / 100);
            normalized.total = normalized.nett + normalized.vat_amount;
            return normalized;
        });
    };
    
    /**
     * Available stock in the currently selected unit (for display and qty validation).
     * API returns stock in base (wholesale) units; selected unit has unit_multiplier to base.
     * So available in selected unit = available_base / unit_multiplier (e.g. 3 packets, piece mult 1/100 => 300 pieces).
     */
    TransactionItemsTable.prototype.getAvailableInSelectedUnit = function(item) {
        if (item == null || typeof item.available_stock !== 'number') return null;
        const mult = item.unit_multiplier != null && item.unit_multiplier > 0 ? item.unit_multiplier : 1;
        return Math.floor(item.available_stock / mult);
    };

    /**
     * Calculate margin percentage in the selected unit (unit-aware).
     * purchase_price is cost per base (wholesale) unit; convert to cost per selected unit using unit_multiplier.
     * NOTE: This margin is markup-on-cost: (price - cost) / cost * 100.
     */
    TransactionItemsTable.prototype.calculateMargin = function(item) {
        if (this.mode !== 'sale' && this.mode !== 'quotation') return 0;
        const costPerBase = item.purchase_price || 0;
        if (costPerBase <= 0) return 0;
        const mult = item.unit_multiplier != null && item.unit_multiplier > 0 ? item.unit_multiplier : 1;
        const costPerSelectedUnit = costPerBase * mult;
        const salePricePerUnit = item.unit_price || 0;
        if (salePricePerUnit <= 0) return 0;
        if (costPerSelectedUnit <= 0) return 0;
        return ((salePricePerUnit - costPerSelectedUnit) / costPerSelectedUnit) * 100;
    };
    
    /**
     * Format margin as percentage string
     */
    TransactionItemsTable.prototype.formatMargin = function(margin) {
        if (isNaN(margin) || !isFinite(margin)) return '—';
        return margin >= 0 ? `+${margin.toFixed(1)}%` : `${margin.toFixed(1)}%`;
    };
    
    /**
     * Render the table
     */
    TransactionItemsTable.prototype.render = function() {
        const total = this.calculateTotal();
        const formatCurrency = this.getFormatCurrency();
        const formatNumber = this.getFormatNumber();
        const escapeHtml = this.getEscapeHtml();
        
        let html = `
           <div class="transaction-items-table-container" data-instance-id="${this.instanceId}" style="position: relative;">
               <table style="width: 100%; border-collapse: collapse; background: white;">
                    <thead>
                        <tr style="background: #f8f9fa; border-bottom: 2px solid var(--border-color, #dee2e6);">
                           <th style="padding: 0.75rem; text-align: left; font-weight: 600; width: 40%; min-width: 250px;">ITEM</th>
                           <th style="padding: 0.75rem; text-align: left; font-weight: 600; width: 12%;">ITEM CODE</th>
                            <th style="padding: 0.75rem; text-align: center; font-weight: 600; width: 5%;">QTY</th>
                            <th style="padding: 0.75rem; text-align: left; font-weight: 600; width: 7%; min-width: 60px;">UNIT</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 9%;" title="Price per unit excluding VAT. VAT is shown in the VAT column.">PRICE/UNIT (excl. VAT)</th>
                            ${(this.mode === 'sale' || this.mode === 'quotation') ? '<th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 6%;">MARGIN%</th>' : ''}
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 6%;">DISCOUNT%</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 6%;">VAT</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 10%;">NETT</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 10%;">TOTAL</th>
                            <th style="padding: 0.75rem; text-align: center; font-weight: 600; width: 4%;">ACTIONS</th>
                        </tr>
                    </thead>
                    <tbody id="${this.instanceId}_tbody">
        `;
        
        // Render item rows
        this.items.forEach((item, index) => {
            const isSearching = this.activeSearchRow === index;
            html += `
                <tr data-item-index="${index}" data-row-id="${this.instanceId}_row_${index}">
                    <td style="padding: 0.25rem; position: relative; min-width: 250px;">
                        <input type="text" 
                               class="form-input item-search-input ${item.item_id ? 'item-selected' : ''}" 
                               id="${this.instanceId}_item_${index}"
                               value="${escapeHtml(item.item_name || '')}" 
                               placeholder="Type item name or code..."
                               autocomplete="off"
                               data-row="${index}"
                               data-item-id="${item.item_id || ''}"
                               style="width: 100%; box-sizing: border-box; border: ${isSearching ? '2px solid var(--primary-color, #007bff)' : '1px solid var(--border-color, #dee2e6)'}; padding: 0.6rem; font-size: 0.9rem; min-width: 250px;"
                               ${!this.canEdit ? 'disabled' : ''}>
                    </td>
                    <td style="padding: 0.25rem;">
                        <input type="text" 
                               class="form-input" 
                               value="${item.item_code || item.item_sku || ''}" 
                               placeholder="Code"
                               readonly
                               style="width: 100%; padding: 0.5rem; box-sizing: border-box; background: #f8f9fa; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="item_code">
                    </td>
                    <td style="padding: 0.25rem;">
                        <div style="display: flex; flex-direction: column; gap: 0.15rem;">
                            <input type="number" 
                                   class="form-input input-direct qty-input" 
                                   value="${item.quantity || 1}" 
                                   step="0.01" 
                                   min="0.01"
                                   style="width: 100%; box-sizing: border-box; text-align: center; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);"
                                   data-row="${index}"
                                   data-field="quantity"
                                   ${!this.canEdit ? 'disabled' : ''}>
                            ${this.mode === 'sale' && (item.stock_display || typeof item.available_stock === 'number') ? (() => {
                                // Use stock_display (3-tier format) if available, otherwise fallback to available_stock
                                if (item.stock_display) {
                                    const stockNum = typeof item.available_stock === 'number' ? item.available_stock : 0;
                                    let color = 'var(--success-color, #16a34a)';
                                    if (stockNum <= 0) {
                                        color = 'var(--danger-color, #dc2626)';
                                    } else if (stockNum > 0 && stockNum < 5) {
                                        color = 'var(--warning-color, #d97706)';
                                    }
                                    return `<span class="stock-indicator" data-row="${index}" style="font-size: 0.75rem; font-weight: 500; color: ${color}; display: block; margin-top: 0.25rem;">
                                        Stock: ${escapeHtml(item.stock_display)}
                                    </span>`;
                                }
                                // Fallback to old format if stock_display not available
                                const stock = this.getAvailableInSelectedUnit(item);
                                if (stock == null) return '';
                                let color = 'var(--success-color, #16a34a)';
                                if (stock <= 0) {
                                    color = 'var(--danger-color, #dc2626)';
                                } else if (stock > 0 && stock < 5) {
                                    color = 'var(--warning-color, #d97706)';
                                }
                                return `<span class="stock-indicator" data-row="${index}" style="font-size: 0.75rem; font-weight: 500; color: ${color}; display: block; margin-top: 0.25rem;">
                                    Available: ${this.getFormatNumber()(stock)}
                                </span>`;
                            })() : ''}
                        </div>
                    </td>
                    <td style="padding: 0.25rem;">
                        ${item.item_id && (item.available_units && item.available_units.length) ? (() => {
                            const units = item.available_units;
                            let opts = units.map(u => `<option value="${escapeHtml(u.unit_name)}" data-multiplier="${escapeHtml(String(u.multiplier_to_base || 1))}" ${(item.unit_name || '') === (u.unit_name || '') ? 'selected' : ''}>${escapeHtml(u.unit_name || '')}</option>`).join('');
                            if (!opts) opts = `<option value="${escapeHtml(item.unit_name || '')}">${escapeHtml(item.unit_name || '')}</option>`;
                            return `<select class="form-input unit-select" data-row="${index}" data-field="unit_name" style="width: 100%; box-sizing: border-box; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);" ${!this.canEdit ? 'disabled' : ''}>${opts}</select>`;
                        })() : `<input type="text" class="form-input unit-display" value="${escapeHtml(item.unit_name || '')}" placeholder="Unit" readonly style="width: 100%; box-sizing: border-box; padding: 0.5rem; background: #f8f9fa; border: 1px solid var(--border-color, #dee2e6);" data-row="${index}" data-field="unit_name">`}
                    </td>
                    <td style="padding: 0.25rem;">
                        <input type="number" 
                               class="form-input input-direct price-input" 
                               value="${this.roundMoney(item.unit_price).toFixed(2)}" 
                               step="0.01" 
                               min="0"
                               style="width: 100%; box-sizing: border-box; text-align: right; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="unit_price"
                               ${!this.canEdit ? 'disabled' : ''}>
                    </td>
                    ${(this.mode === 'sale' || this.mode === 'quotation') ? `
                    <td style="padding: 0.25rem; text-align: right;">
                        <input type="number" 
                               class="form-input input-direct margin-input" 
                               value="${(this.calculateMargin(item) || 0).toFixed(1)}" 
                               step="0.1" 
                               data-row="${index}"
                               style="width: 100%; box-sizing: border-box; text-align: right; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6); font-weight: 500; color: ${this.calculateMargin(item) >= 0 ? 'var(--success-color, #10b981)' : 'var(--danger-color, #ef4444)'};"
                               title="Edit margin % — net and total will recalculate"
                               ${!this.canEdit ? 'disabled' : ''}>
                    </td>
                    ` : ''}
                    <td style="padding: 0.25rem;">
                        <input type="number" 
                               class="form-input input-direct discount-input" 
                               value="${this.roundMoney(item.discount_percent)}" 
                               step="0.01" 
                               min="0"
                               max="100"
                               style="width: 100%; box-sizing: border-box; text-align: right; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="discount_percent"
                               ${!this.canEdit ? 'disabled' : ''}>
                    </td>
                    <td style="padding: 0.25rem; text-align: right;">
                        <div style="display: flex; flex-direction: column; gap: 0.1rem;">
                            <span class="vat-percent-display" data-row="${index}" style="font-size: 0.75rem; color: var(--text-secondary, #666);">
                                ${(item.tax_percent || 0).toFixed(1)}%
                            </span>
                            <span class="vat-amount-display" data-row="${index}" style="font-weight: 500;">
                                ${formatCurrency(this.calculateVATAmount(item))}
                            </span>
                        </div>
                    </td>
                    <td style="padding: 0.25rem; text-align: right; font-weight: 600;">
                        <span class="item-nett" data-row="${index}">${formatCurrency(this.calculateNett(item))}</span>
                    </td>
                    <td style="padding: 0.25rem; text-align: right; font-weight: 600;">
                        <input type="number" class="form-input input-direct total-input" data-row="${index}" data-field="total"
                               value="${this.roundMoney(item.total).toFixed(2)}"
                               step="0.01" min="0"
                               style="width: 100%; box-sizing: border-box; text-align: right; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6); font-weight: 600;"
                               ${!this.canEdit ? 'readonly' : ''}
                               title="Editable: enter total to reverse-calculate unit price">
                    </td>
                    <td style="padding: 0.25rem; text-align: center;">
                        <div style="display: flex; gap: 0.25rem; justify-content: center; align-items: center;">
                            ${this.mode === 'purchase' && item.item_id ? `
                                <button type="button" 
                                        class="btn btn-outline btn-sm manage-batches-btn" 
                                        data-row="${index}"
                                        data-item-id="${item.item_id}"
                                        data-item-name="${escapeHtml(item.item_name)}"
                                        data-quantity="${item.quantity || 0}"
                                        data-unit-name="${escapeHtml(item.unit_name || '')}"
                                        data-unit-cost="${item.unit_price || 0}"
                                        title="Manage Batches"
                                        style="padding: 0.25rem 0.5rem; font-size: 0.875rem;">
                                    <i class="fas fa-boxes"></i>
                                </button>
                            ` : ''}
                            ${item.is_empty ? '' : `
                                <button type="button" 
                                        class="btn btn-outline btn-sm remove-item-btn" 
                                        data-row="${index}"
                                        title="Remove item"
                                        style="padding: 0.25rem 0.5rem; font-size: 0.875rem;"
                                        ${!this.canEdit ? 'disabled' : ''}>
                                    <i class="fas fa-trash"></i>
                                </button>
                            `}
                        </div>
                    </td>
                </tr>
            `;
        });
        
        const summary = this.calculateSummary();
        
        html += `
                    </tbody>
                    <tfoot>
                        <tr style="background: #f8f9fa; border-top: 2px solid var(--border-color, #dee2e6); font-weight: 600;">
                            <td colspan="${(this.mode === 'sale' || this.mode === 'quotation') ? '7' : '6'}" style="padding: 0.75rem; text-align: right;">Net:</td>
                            <td style="padding: 0.75rem; text-align: right;" id="${this.instanceId}_vat_total">${formatCurrency(summary.vat)}</td>
                            <td style="padding: 0.75rem; text-align: right; font-size: 1.1rem;" id="${this.instanceId}_nett_total">${formatCurrency(summary.nett)}</td>
                            <td style="padding: 0.75rem; text-align: right; font-size: 1.1rem;" id="${this.instanceId}_total">${formatCurrency(summary.total)}</td>
                            <td></td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        `;
        
        this.mountEl.innerHTML = html;
    };
    
    /**
     * Attach event listeners
     */
    TransactionItemsTable.prototype.attachEventListeners = function() {
        const tbody = document.getElementById(`${this.instanceId}_tbody`);
        if (!tbody) return;
        
        // Item search input handlers
        tbody.addEventListener('input', (e) => {
            if (e.target.classList.contains('item-search-input')) {
                const row = parseInt(e.target.dataset.row);
                const item = this.items[row];
                // If row had a selected item and user is typing, clear selection and run search
                if (item && item.item_id) {
                    this.clearRowSelection(row);
                    e.target.dataset.itemId = '';
                    e.target.classList.remove('item-selected');
                }
                this.handleItemSearch(e.target.value, row);
            }
        });
        
        // When focusing item field with a selected item, show details dropdown (not search)
        tbody.addEventListener('focus', (e) => {
            if (e.target.classList.contains('item-search-input')) {
                const row = parseInt(e.target.dataset.row);
                const item = this.items[row];
                if (item && item.item_id) {
                    e.preventDefault();
                    this.showSelectedItemDropdown(row);
                    return;
                }
            }
        }, true);
        
        tbody.addEventListener('click', (e) => {
            if (e.target.classList.contains('item-search-input')) {
                const row = parseInt(e.target.dataset.row);
                const item = this.items[row];
                if (item && item.item_id) {
                    this.showSelectedItemDropdown(row);
                }
            }
        });
        
        tbody.addEventListener('keydown', (e) => {
            if (e.target.classList.contains('item-search-input')) {
                if (e.key === 'Escape') {
                    this.closeSelectedItemDropdown();
                    this.closeSuggestions();
                }
                this.handleItemSearchKeydown(e, parseInt(e.target.dataset.row));
            } else if (e.target.classList.contains('qty-input') || 
                       e.target.classList.contains('price-input') || 
                       e.target.classList.contains('discount-input')) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.handleFieldChange(parseInt(e.target.dataset.row), e.target.dataset.field, e.target.value);
                    // Move to next field or add new row
                    this.moveToNextField(e.target);
                }
            } else if (e.target.classList.contains('total-input')) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.handleTotalChange(parseInt(e.target.dataset.row), e.target.value);
                }
            }
        });
        
        // Quantity, price, discount, unit change handlers (on blur/enter/change)
        tbody.addEventListener('change', (e) => {
            if (e.target.classList.contains('qty-input') || 
                e.target.classList.contains('price-input') || 
                e.target.classList.contains('discount-input')) {
                const row = parseInt(e.target.dataset.row);
                const field = e.target.dataset.field;
                this.handleFieldChange(row, field, e.target.value);
            }
            if (e.target.classList.contains('unit-select')) {
                const row = parseInt(e.target.dataset.row);
                const opt = e.target.options[e.target.selectedIndex];
                const unitName = e.target.value;
                const multiplier = opt ? parseFloat(opt.dataset.multiplier) || 1 : 1;
                this.handleUnitChange(row, unitName, multiplier);
            }
            if (e.target.classList.contains('total-input')) {
                const row = parseInt(e.target.dataset.row);
                this.handleTotalChange(row, e.target.value);
            }
            if (e.target.classList.contains('margin-input')) {
                const row = parseInt(e.target.dataset.row);
                this.handleMarginChange(row, e.target.value);
            }
        });
        
        // Real-time input handlers (debounced) for live calculation
        tbody.addEventListener('input', (e) => {
            if (e.target.classList.contains('qty-input') || 
                e.target.classList.contains('price-input') || 
                e.target.classList.contains('discount-input')) {
                const row = parseInt(e.target.dataset.row);
                const field = e.target.dataset.field;
                
                // Clear previous timeout
                if (this.inputDebounceTimeout) {
                    clearTimeout(this.inputDebounceTimeout);
                }
                
                // Debounce input for 150ms for smooth real-time calculation
                this.inputDebounceTimeout = setTimeout(() => {
                    this.handleFieldChange(row, field, e.target.value);
                }, 150);
            }
            if (e.target.classList.contains('total-input')) {
                const row = parseInt(e.target.dataset.row);
                if (this.totalInputDebounce) clearTimeout(this.totalInputDebounce);
                this.totalInputDebounce = setTimeout(() => {
                    this.handleTotalChange(row, e.target.value);
                }, 300);
            }
            if (e.target.classList.contains('margin-input')) {
                const row = parseInt(e.target.dataset.row);
                if (this.marginInputDebounce) clearTimeout(this.marginInputDebounce);
                this.marginInputDebounce = setTimeout(() => {
                    this.handleMarginChange(row, e.target.value);
                }, 300);
            }
        });
        
        // Prevent mouse wheel from changing price/total/margin/discount (direct type-in only)
        tbody.addEventListener('wheel', (e) => {
            if (e.target.classList.contains('qty-input') || e.target.classList.contains('price-input') || e.target.classList.contains('total-input') ||
                e.target.classList.contains('margin-input') || e.target.classList.contains('discount-input')) {
                e.preventDefault();
            }
        }, { passive: false });
        
        // Remove item button
        tbody.addEventListener('click', (e) => {
            if (e.target.closest('.remove-item-btn')) {
                const row = parseInt(e.target.closest('.remove-item-btn').dataset.row);
                this.removeItem(row);
            }
            // Manage batches button
            if (e.target.closest('.manage-batches-btn')) {
                const btn = e.target.closest('.manage-batches-btn');
                const rowIndex = parseInt(btn.dataset.row);
                const item = this.items[rowIndex];
                if (item && item.item_id) {
                    this.openBatchDistributionModal(rowIndex, item);
                }
            }
        });
        
        // Click outside to close suggestions and selected-item dropdown
        document.addEventListener('click', (e) => {
            if (!e.target.closest(`[data-instance-id="${this.instanceId}"]`)) {
                this.closeSuggestions();
                this.closeSelectedItemDropdown();
            }
        });
        
        // Load available units for rows that have item_id but no units yet (e.g. loaded from server)
        for (let i = 0; i < this.items.length; i++) {
            if (this.items[i].item_id && !(this.items[i].available_units && this.items[i].available_units.length)) {
                this.loadUnitsForRow(i);
            }
        }
    };
    
    /**
     * Handle item search.
     * Debounced (~250ms) so requests fire only after user pauses typing.
     * Cancels in-flight request when new query is entered. Stale responses are ignored.
     */
    TransactionItemsTable.prototype.handleItemSearch = function(query, rowIndex) {
        const queryTrimmed = query.trim();
        
        // Clear previous debounce timeout so we only fire after user pauses
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
            this.searchTimeout = null;
        }
        
        // Abort in-flight request when new query is entered (cancellation)
        if (this.searchAbortController) {
            this.searchAbortController.abort();
        }
        
        if (queryTrimmed.length < 2) {
            this.closeSuggestions();
            return;
        }
        
        // Show cached results immediately when cache hit (no request, no loading)
        const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : (typeof CONFIG !== 'undefined' ? CONFIG : null);
        const cache = (typeof window !== 'undefined' && window.searchCache) ? window.searchCache : null;
        if (config && cache) {
            const cached = cache.get(queryTrimmed, config.COMPANY_ID, config.BRANCH_ID, 50);
            if (cached !== null && cached !== undefined) {
                this.activeSearchRow = rowIndex;
                if (cached.length === 0) {
                    this.showSuggestions(rowIndex, [{ type: 'create', query: queryTrimmed, message: 'Create new item: "' + queryTrimmed + '"' }]);
                } else {
                    this.showSuggestions(rowIndex, cached.map(item => ({ type: 'item', ...item })));
                }
                return;
            }
        }
        
        // Debounce: only fire request and show loading after user pauses typing
        this.searchTimeout = setTimeout(() => {
            this.searchTimeout = null;
            this.activeSearchRow = rowIndex;
            this.showSuggestions(rowIndex, [{ type: 'loading', message: 'Searching...' }]);
            this.performItemSearch(queryTrimmed, rowIndex);
        }, this._searchDebounceMs);
    };
    
    /**
     * Perform item search via API.
     * Uses AbortController so in-flight request can be cancelled when user types again.
     * Only updates dropdown if response still matches current input (stale-response guard).
     */
    TransactionItemsTable.prototype.performItemSearch = async function(query, rowIndex) {
        const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : (typeof CONFIG !== 'undefined' ? CONFIG : null);
        
        if (!config || !config.COMPANY_ID) {
            this.showSuggestions(rowIndex, [{ type: 'error', message: 'Configuration error. Please set Company ID in Settings.' }]);
            return;
        }
        
        const api = (typeof window !== 'undefined' && window.API) ? window.API : null;
        if (!api || !api.items || !api.items.search) {
            this.showSuggestions(rowIndex, [{ type: 'error', message: 'API not available. Please refresh the page.' }]);
            return;
        }
        
        // New controller for this request; abort() called when next search starts
        this.searchAbortController = new AbortController();
        const signal = this.searchAbortController.signal;
        const searchId = ++this._searchId; // Stale-response guard: only apply if still latest
        
        const applyResults = (suggestions) => {
            if (searchId !== this._searchId) return; // Stale: user typed again, ignore
            const input = document.getElementById(`${this.instanceId}_item_${rowIndex}`);
            if (input && input.value.trim() !== query) return; // Input changed, ignore
            this.showSuggestions(rowIndex, suggestions);
        };
        
        try {
            const cache = (typeof window !== 'undefined' && window.searchCache) ? window.searchCache : null;
            const includePricing = true;
            
            if (cache) {
                const cached = cache.get(query, config.COMPANY_ID, config.BRANCH_ID, 50);
                if (cached !== null && cached !== undefined) {
                    if (cached.length === 0) {
                        applyResults([{ type: 'create', query: query, message: 'Create new item: "' + query + '"' }]);
                    } else {
                        applyResults(cached.map(item => ({ type: 'item', ...item })));
                    }
                    return;
                }
            }
            
            const requestOptions = signal ? { signal } : {};
            const searchLimit = 50;
            const items = await api.items.search(query, config.COMPANY_ID, searchLimit, config.BRANCH_ID || null, includePricing, this.context, requestOptions);
            
            if (cache && items) {
                cache.set(query, config.COMPANY_ID, config.BRANCH_ID, searchLimit, items);
            }
            
            if (searchId !== this._searchId) return;
            if (items.length === 0) {
                applyResults([{ type: 'create', query: query, message: 'Create new item: "' + query + '"' }]);
            } else {
                applyResults(items.map(item => ({ type: 'item', ...item })));
            }
        } catch (error) {
            if (error.name === 'AbortError') return; // Cancelled, do nothing
            if (searchId !== this._searchId) return;
            applyResults([
                { type: 'error', message: error.message || 'Search failed' },
                { type: 'create', query: query, message: 'Create new item: "' + query + '"' }
            ]);
        }
    };
    
    /**
     * Show suggestions dropdown (spans full table width)
     */
    TransactionItemsTable.prototype.showSuggestions = function(rowIndex, suggestions) {
        // Create or get dropdown - position it relative to table container, not cell
        const container = this.mountEl.querySelector(`[data-instance-id="${this.instanceId}"]`);
        if (!container) return;
        
        let dropdown = document.getElementById(`${this.instanceId}_suggestions_${rowIndex}`);
        if (!dropdown) {
            // Create dropdown if it doesn't exist
            dropdown = document.createElement('div');
            dropdown.id = `${this.instanceId}_suggestions_${rowIndex}`;
            dropdown.className = 'item-suggestions-dropdown';
            container.appendChild(dropdown);
        }
        
        // Get the input field to position dropdown below it
        const input = document.getElementById(`${this.instanceId}_item_${rowIndex}`);
        if (!input) return;
        
        // Calculate position relative to container
        const containerRect = container.getBoundingClientRect();
        const inputRect = input.getBoundingClientRect();
        const relativeTop = inputRect.bottom - containerRect.top + 2;
        const relativeLeft = 0; // Start from left edge of container
        
        // Position dropdown to span full width of table
        dropdown.style.cssText = `
            display: block;
            position: absolute;
            top: ${relativeTop}px;
            left: ${relativeLeft}px;
            width: 100%;
            background: white;
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: 0.25rem;
            box-shadow: 0 6px 16px rgba(0,0,0,0.25);
            z-index: 1100;
            max-height: 500px;
            overflow-y: auto;
            overflow-x: hidden;
            font-size: 0.8rem;
            line-height: 1.3;
        `;
        
        // Add custom scrollbar styling for better UX
        if (!document.getElementById('item-dropdown-scrollbar-style')) {
            const style = document.createElement('style');
            style.id = 'item-dropdown-scrollbar-style';
            style.textContent = `
                .item-suggestions-dropdown::-webkit-scrollbar {
                    width: 8px;
                }
                .item-suggestions-dropdown::-webkit-scrollbar-track {
                    background: #f1f1f1;
                    border-radius: 4px;
                }
                .item-suggestions-dropdown::-webkit-scrollbar-thumb {
                    background: #888;
                    border-radius: 4px;
                }
                .item-suggestions-dropdown::-webkit-scrollbar-thumb:hover {
                    background: #555;
                }
            `;
            document.head.appendChild(style);
        }
        
        const formatCurrency = this.getFormatCurrency();
        const escapeHtml = this.getEscapeHtml();
        
        let html = '';
        
        suggestions.forEach((suggestion, index) => {
            if (suggestion.type === 'loading') {
                html += `
                    <div style="padding: 1rem; text-align: center; color: var(--text-secondary, #666);">
                        <i class="fas fa-spinner fa-spin"></i> ${suggestion.message}
                    </div>
                `;
            } else if (suggestion.type === 'error') {
                html += `
                    <div style="padding: 1rem; text-align: center; color: var(--danger-color, #dc3545);">
                        <i class="fas fa-exclamation-triangle"></i> ${suggestion.message}
                    </div>
                `;
            } else if (suggestion.type === 'create') {
                html += `
                    <div class="suggestion-item suggestion-create" 
                         data-action="create" 
                         data-query="${escapeHtml(suggestion.query)}"
                         style="padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border-color, #dee2e6); cursor: pointer; background: #e7f3ff; min-height: 2.5rem; display: flex; align-items: center;"
                         onmouseover="this.style.background='#d0e7ff'" 
                         onmouseout="this.style.background='#e7f3ff'">
                        <i class="fas fa-plus-circle" style="color: var(--primary-color, #007bff); margin-right: 0.5rem; font-size: 0.85rem;"></i>
                        <strong style="font-size: 0.85rem;">${escapeHtml(suggestion.message)}</strong>
                    </div>
                `;
            } else if (suggestion.type === 'item') {
                const salePrice = suggestion.sale_price || 0;
                const purchasePrice = suggestion.purchase_price || 0;
                const stock = typeof suggestion.current_stock === 'number' ? suggestion.current_stock : (suggestion.stock || 0);
                const stockDisplayStr = suggestion.stock_display || null; // 3-tier formatted stock display
                const vatRate = this.vatRateToPercent(suggestion.vat_rate ?? suggestion.vatRate ?? 0);
                const vatCode = suggestion.vat_category || suggestion.vat_code || '';
                const lastSupplier = suggestion.last_supplier || '';
                const baseUnit = suggestion.base_unit || '';
                
                // Purchase Order specific fields
                const lastOrderDate = suggestion.last_order_date || null;
                const lastSupplyDate = suggestion.last_supply_date || null;
                const lastUnitCost = suggestion.last_unit_cost || purchasePrice;
                
                // For sale/quotation: if selling price is zero but cost exists, pre-calculate 30% margin
                const DEFAULT_MARGIN_PERCENT = 30;
                const effectiveSalePrice = (this.mode === 'sale' || this.mode === 'quotation') && (!salePrice || salePrice === 0) && purchasePrice > 0
                    ? Math.round(purchasePrice * (1 + DEFAULT_MARGIN_PERCENT / 100) * 100) / 100
                    : salePrice;
                // Determine which price to show based on mode (quotation uses selling price like sale)
                const displayPrice = (this.mode === 'sale' || this.mode === 'quotation') ? effectiveSalePrice : purchasePrice;
                const priceLabel = (this.mode === 'sale' || this.mode === 'quotation') ? 'Price' : 'Cost';
                
                // Build stock display with color coding (use 3-tier format if available)
                let stockDisplay = '';
                if (stockDisplayStr) {
                    // Use 3-tier formatted stock display
                    let stockColor = 'var(--text-secondary, #666)';
                    if (typeof stock === 'number') {
                        if (stock <= 0) {
                            stockColor = 'var(--danger-color, #dc2626)';
                        } else if (stock > 0 && stock < 5) {
                            stockColor = 'var(--warning-color, #d97706)';
                        } else {
                            stockColor = 'var(--success-color, #16a34a)';
                        }
                    }
                    stockDisplay = `<span style="color: ${stockColor}; font-weight: 500;">Stock: ${escapeHtml(stockDisplayStr)}</span>`;
                } else if (typeof stock === 'number') {
                    let stockColor = 'var(--text-secondary, #666)';
                    if (stock <= 0) {
                        stockColor = 'var(--danger-color, #dc2626)';
                    } else if (stock > 0 && stock < 5) {
                        stockColor = 'var(--warning-color, #d97706)';
                    } else {
                        stockColor = 'var(--success-color, #16a34a)';
                    }
                    stockDisplay = `<span style="color: ${stockColor}; font-weight: 500;">${this.getFormatNumber()(stock)} ${escapeHtml(baseUnit)}</span>`;
                } else {
                    stockDisplay = '<span style="color: var(--text-secondary, #666);">N/A</span>';
                }
                
                // Format dates
                const formatDate = (dateStr) => {
                    if (!dateStr) return '—';
                    try {
                        const date = new Date(dateStr);
                        return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
                    } catch (e) {
                        return '—';
                    }
                };
                
                // For Purchase Order context, show table format with all fields
                if (this.context === 'purchase_order') {
                    html += `
                        <div class="suggestion-item suggestion-item-option" 
                             data-item-id="${suggestion.id}"
                             data-item-name="${escapeHtml(suggestion.name)}"
                             data-item-sku="${escapeHtml(suggestion.sku || '')}"
                             data-item-code="${escapeHtml(suggestion.code || suggestion.sku || '')}"
                             data-unit-name="${escapeHtml(baseUnit)}"
                             data-sale-price="${salePrice}"
                             data-purchase-price="${lastUnitCost}"
                             data-vat-rate="${vatRate}"
                             data-stock="${stock}"
                             data-stock-display="${stockDisplayStr || ''}"
                             style="padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border-color, #dee2e6); cursor: pointer; min-height: 4rem;"
                             onmouseover="this.style.background='#f8f9fa'" 
                             onmouseout="this.style.background='white'">
                            <div style="display: grid; grid-template-columns: 2.5fr 0.8fr 0.9fr 0.9fr 1fr 1fr; column-gap: 0.5rem; align-items: center; font-size: 0.8rem;">
                                <div>
                                    <div style="font-weight: 600; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 0.1rem;">
                                        ${escapeHtml(suggestion.name)}
                                    </div>
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666);">
                                        ${escapeHtml(suggestion.sku || suggestion.code || '')}
                                    </div>
                                </div>
                                <div style="text-align: center;">
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.1rem;">INS STOCK</div>
                                    ${stockDisplay}
                                </div>
                                <div style="text-align: center;">
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.1rem;">LAST ORDER</div>
                                    <div style="font-size: 0.75rem;">${formatDate(lastOrderDate)}</div>
                                </div>
                                <div style="text-align: center;">
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.1rem;">LAST SUPPLY</div>
                                    <div style="font-size: 0.75rem;">${formatDate(lastSupplyDate)}</div>
                                </div>
                                <div style="text-align: center;">
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.1rem;">LAST SUPPLIER</div>
                                    <div style="font-size: 0.75rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(lastSupplier)}">
                                        ${lastSupplier ? escapeHtml(lastSupplier) : '—'}
                                    </div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.1rem;">LAST COST</div>
                                    <div style="font-weight: 600; font-size: 0.85rem; color: var(--primary-color, #007bff);">
                                        ${formatCurrency(lastUnitCost)}
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                } else {
                    // Standard display for other contexts
                    let additionalInfo = '';
                    if (this.mode === 'purchase') {
                        if (lastSupplier) {
                            additionalInfo = `<div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-top: 0.2rem;">
                                <i class="fas fa-truck" style="margin-right: 0.25rem;"></i>Last Supplier: ${escapeHtml(lastSupplier)}
                            </div>`;
                        }
                    } else if (this.mode === 'sale' || this.mode === 'quotation') {
                        if (vatRate > 0 || vatCode) {
                            additionalInfo = `<div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-top: 0.2rem;">
                                <i class="fas fa-receipt" style="margin-right: 0.25rem;"></i>VAT: ${vatRate.toFixed(1)}% ${vatCode ? `(${escapeHtml(vatCode)})` : ''}
                            </div>`;
                        }
                    }
                    
                    html += `
                        <div class="suggestion-item suggestion-item-option" 
                             data-item-id="${suggestion.id}"
                             data-item-name="${escapeHtml(suggestion.name)}"
                             data-item-sku="${escapeHtml(suggestion.sku || '')}"
                             data-item-code="${escapeHtml(suggestion.code || suggestion.sku || '')}"
                             data-unit-name="${escapeHtml(baseUnit)}"
                             data-sale-price="${(this.mode === 'sale' || this.mode === 'quotation') ? effectiveSalePrice : salePrice}"
                             data-purchase-price="${this.context === 'purchase_order' ? lastUnitCost : purchasePrice}"
                             data-vat-rate="${vatRate}"
                             data-stock="${stock}"
                             data-stock-display="${stockDisplayStr || ''}"
                             style="padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border-color, #dee2e6); cursor: pointer; min-height: 3rem;"
                             onmouseover="this.style.background='#f8f9fa'" 
                             onmouseout="this.style.background='white'">
                            <div style="display: grid; grid-template-columns: 3fr 1.2fr 1.5fr 1.3fr; column-gap: 0.75rem; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 0.15rem;">
                                        ${escapeHtml(suggestion.name)}
                                    </div>
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666);">
                                        ${escapeHtml(suggestion.sku || suggestion.code || '')}
                                    </div>
                                    ${additionalInfo}
                                </div>
                                <div style="text-align: center;">
                                    ${stockDisplay}
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.15rem;">${priceLabel}:</div>
                                    <div style="font-weight: 600; font-size: 0.85rem; color: var(--primary-color, #007bff);">
                                        ${formatCurrency(displayPrice)}
                                    </div>
                                    ${this.mode === 'purchase' && purchasePrice > 0 ? `
                                        <div style="font-size: 0.65rem; color: var(--text-secondary, #666); margin-top: 0.1rem;">
                                            Last Purchase
                                        </div>
                                    ` : ''}
                                </div>
                                <div style="text-align: right;">
                                    ${(this.mode === 'sale' || this.mode === 'quotation') && purchasePrice > 0 ? `
                                        <div style="font-size: 0.7rem; color: var(--text-secondary, #666); margin-bottom: 0.15rem;">Cost:</div>
                                        <div style="font-size: 0.75rem; color: var(--text-secondary, #666);">
                                            ${formatCurrency(purchasePrice)}
                                        </div>
                                    ` : ''}
                                </div>
                            </div>
                        </div>
                    `;
                }
            }
        });
        
        dropdown.innerHTML = html;
        dropdown.style.display = 'block';
        
        // Attach click handlers
        dropdown.querySelectorAll('.suggestion-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (item.dataset.action === 'create') {
                    this.handleCreateItem(item.dataset.query, rowIndex);
                } else {
                    this.handleSelectItem(item, rowIndex);
                }
            });
        });
    };
    
    /**
     * Handle item selection
     */
    TransactionItemsTable.prototype.handleSelectItem = function(suggestionEl, rowIndex) {
        const selectedItemId = suggestionEl.dataset.itemId;
        // In sale/quotation: prevent duplicate item in same document; direct user to edit existing line
        if (this.mode === 'sale' || this.mode === 'quotation') {
            for (let i = 0; i < this.items.length; i++) {
                if (i !== rowIndex && this.items[i].item_id === selectedItemId) {
                    this.closeSuggestions();
                    if (typeof showToast === 'function') {
                        showToast('Item already in this invoice. Edit the existing line or remove it first.', 'warning');
                    }
                    const rowEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${i}"]`);
                    if (rowEl) {
                        rowEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        rowEl.classList.add('highlight-row-duplicate');
                        setTimeout(function() { rowEl.classList.remove('highlight-row-duplicate'); }, 2500);
                    }
                    return;
                }
            }
        }
        const item = {
            item_id: selectedItemId,
            item_name: suggestionEl.dataset.itemName,
            item_sku: suggestionEl.dataset.itemSku,
            item_code: suggestionEl.dataset.itemCode,
            unit_name: suggestionEl.dataset.unitName,
            unit_price: (() => {
                let up = (this.mode === 'sale' || this.mode === 'quotation')
                    ? parseFloat(suggestionEl.dataset.salePrice)
                    : parseFloat(suggestionEl.dataset.purchasePrice);
                // When selling price is zero but cost exists, use 30% margin (already set on data-sale-price in suggestions)
                if ((this.mode === 'sale' || this.mode === 'quotation') && (!up || up === 0)) {
                    const cost = parseFloat(suggestionEl.dataset.purchasePrice) || 0;
                    if (cost > 0) up = Math.round(cost * 1.30 * 100) / 100;
                }
                return up;
            })(),
            purchase_price: parseFloat(suggestionEl.dataset.purchasePrice) || 0, // Store cost for margin
            quantity: this.items[rowIndex].quantity || 1,
            discount_percent: 0,
            tax_percent: this.vatRateToPercent(suggestionEl.dataset.vatRate),
            available_stock: typeof suggestionEl.dataset.stock !== 'undefined'
                ? parseFloat(suggestionEl.dataset.stock)
                : null,
            stock_display: suggestionEl.dataset.stockDisplay || null, // 3-tier formatted stock display
            is_empty: false,
            available_units: null, // Populated below from API
            unit_multiplier: 1
        };
        
        // Update item
        this.items[rowIndex] = item;
        this.recalculateRow(rowIndex);
        this.closeSuggestions();
        this.render();
        this.attachEventListeners();
        
        // Fetch full item to get available units for unit dropdown
        this.loadUnitsForRow(rowIndex);
        
        // Focus on quantity field
        setTimeout(() => {
            const qtyInput = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .qty-input`);
            if (qtyInput) qtyInput.focus();
        }, 100);
        
        // Always ensure there's an empty row at the end for adding new items
        // Check if the last item is empty, if not, add one
        const lastItem = this.items[this.items.length - 1];
        const hasEmptyRow = lastItem && 
            (!lastItem.item_id && !lastItem.item_name);
        
        if (!hasEmptyRow) {
            this.items.push(this.createEmptyItem());
            this.render();
            this.attachEventListeners();
        }
        
        this.notifyChange();
    };
    
    /**
     * Handle create item
     */
    TransactionItemsTable.prototype.handleCreateItem = function(query, rowIndex) {
        if (this.onItemCreate) {
            this.onItemCreate(query, rowIndex, (newItem) => {
                // Item was created, select it
                const suggestionEl = document.createElement('div');
                suggestionEl.dataset.itemId = newItem.id;
                suggestionEl.dataset.itemName = newItem.name;
                suggestionEl.dataset.itemSku = newItem.sku || '';
                suggestionEl.dataset.itemCode = newItem.code || newItem.sku || '';
                suggestionEl.dataset.unitName = newItem.base_unit || '';
                suggestionEl.dataset.salePrice = newItem.sale_price || 0;
                suggestionEl.dataset.purchasePrice = newItem.purchase_price || 0;
                this.handleSelectItem(suggestionEl, rowIndex);
            });
        } else {
            // Fallback: show modal or redirect
            showToast(`To create item "${query}", please go to Items page`, 'info');
        }
    };
    
    /**
     * Handle margin change: set unit price from cost (in selected unit) and margin %, then recalc net and total.
     * cost per selected unit = purchase_price * unit_multiplier; unit_price = cost_per_selected * (1 + margin%/100)
     */
    TransactionItemsTable.prototype.handleMarginChange = function(rowIndex, value) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        const item = this.items[rowIndex];
        if (!item) return;
        const marginPct = parseFloat(value);
        if (isNaN(marginPct)) return;
        const costPerBase = item.purchase_price || 0;
        if (costPerBase <= 0) return;
        const mult = item.unit_multiplier != null && item.unit_multiplier > 0 ? item.unit_multiplier : 1;
        const costPerSelectedUnit = costPerBase * mult;
        item.unit_price = Math.round(costPerSelectedUnit * (1 + marginPct / 100) * 10000) / 10000;
        this.recalculateRow(rowIndex);
        this.updateRowDisplay(rowIndex);
        this.notifyChange();
    };

    /**
     * Handle total change: reverse-calculate unit price from total.
     * total = quantity * unit_price * (1 - discount_percent/100) * (1 + tax_percent/100)
     * => unit_price = total / (quantity * (1 - discount_percent/100) * (1 + tax_percent/100))
     */
    TransactionItemsTable.prototype.handleTotalChange = function(rowIndex, value) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        const newTotal = parseFloat(value);
        if (isNaN(newTotal) || newTotal < 0) return;
        const item = this.items[rowIndex];
        if (!item) return;
        const qty = item.quantity || 0;
        if (qty <= 0) return;
        const discountPct = (item.discount_percent || 0) / 100;
        const taxPct = (item.tax_percent || 0) / 100;
        const factor = qty * (1 - discountPct) * (1 + taxPct);
        if (factor <= 0) return;
        const unitPrice = newTotal / factor;
        item.unit_price = this.roundMoney(unitPrice);
        this.recalculateRow(rowIndex);
        this.updateRowDisplay(rowIndex);
        this.updateMarginDisplay(rowIndex);
        this.notifyChange();
    };

    /**
     * Handle field change (qty, price, discount)
     */
    TransactionItemsTable.prototype.handleFieldChange = function(rowIndex, field, value) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        
        const numValue = parseFloat(value) || 0;
        const item = this.items[rowIndex];

        // Real-time stock validation for quantity in sales mode (limit = available in selected unit)
        const availableInSelected = this.mode === 'sale' ? this.getAvailableInSelectedUnit(item) : null;
        if (this.mode === 'sale' && field === 'quantity' && availableInSelected != null) {
            if (numValue > availableInSelected) {
                const clamped = availableInSelected > 0 ? availableInSelected : 0;
                this.items[rowIndex][field] = clamped;

                // Reflect clamped value in the input
                const qtyInput = document.querySelector(
                    `#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .qty-input`
                );
                if (qtyInput) {
                    qtyInput.value = clamped > 0 ? clamped : '';
                }

                if (typeof window.showToast === 'function') {
                    window.showToast('Quantity cannot exceed available stock', 'warning');
                }
            } else {
                this.items[rowIndex][field] = numValue;
            }
        } else {
            this.items[rowIndex][field] = numValue;
        }
        if (field === 'unit_price') {
            this.items[rowIndex][field] = this.roundMoney(this.items[rowIndex][field]);
        }
        this.recalculateRow(rowIndex);
        this.updateRowDisplay(rowIndex);
        this.updateMarginDisplay(rowIndex); // Update margin when price changes
        this.notifyChange();
    };
    
    /**
     * Update margin display for a row (editable input)
     */
    TransactionItemsTable.prototype.updateMarginDisplay = function(rowIndex) {
        if (this.mode !== 'sale' && this.mode !== 'quotation') return;
        
        const item = this.items[rowIndex];
        if (!item) return;
        
        const marginEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .margin-input`);
        if (marginEl) {
            const margin = this.calculateMargin(item);
            marginEl.value = (margin !== null && !isNaN(margin)) ? margin.toFixed(1) : '';
            marginEl.style.color = margin >= 0 ? 'var(--success-color, #10b981)' : 'var(--danger-color, #ef4444)';
        }
    };
    
    /**
     * Recalculate row total (round to 2 decimals so no 49.99994 display)
     */
    TransactionItemsTable.prototype.recalculateRow = function(rowIndex) {
        const item = this.items[rowIndex];
        if (!item) return;
        const round = (n) => Math.round(parseFloat(n) * 100) / 100;
        const subtotal = (item.quantity || 0) * (item.unit_price || 0);
        const discount = round(subtotal * ((item.discount_percent || 0) / 100));
        const afterDiscount = round(subtotal - discount);
        const tax = round(afterDiscount * ((item.tax_percent || 0) / 100));
        item.total = round(afterDiscount + tax);
        item.nett = afterDiscount;
        item.vat_amount = tax;
    };
    
    /**
     * Calculate VAT amount for an item
     */
    TransactionItemsTable.prototype.calculateVATAmount = function(item) {
        const subtotal = (item.quantity || 0) * (item.unit_price || 0);
        const discount = subtotal * ((item.discount_percent || 0) / 100);
        const afterDiscount = subtotal - discount;
        return afterDiscount * ((item.tax_percent || 0) / 100);
    };
    
    /**
     * Calculate Nett (after discount, before VAT) for an item
     */
    TransactionItemsTable.prototype.calculateNett = function(item) {
        const subtotal = (item.quantity || 0) * (item.unit_price || 0);
        const discount = subtotal * ((item.discount_percent || 0) / 100);
        return subtotal - discount;
    };
    
    /**
     * Calculate summary totals (Net, VAT, Total)
     */
    TransactionItemsTable.prototype.calculateSummary = function() {
        let nett = 0;
        let vat = 0;
        let total = 0;
        
        this.items.forEach(item => {
            if (item.item_id && !item.is_empty) {
                const itemNett = this.calculateNett(item);
                const itemVat = this.calculateVATAmount(item);
                nett += itemNett;
                vat += itemVat;
                total += itemNett + itemVat;
            }
        });
        
        return { nett, vat, total };
    };
    
    /**
     * Update row display
     */
    TransactionItemsTable.prototype.updateRowDisplay = function(rowIndex) {
        const item = this.items[rowIndex];
        if (!item) return;
        
        // Update VAT display
        const vatPercentEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .vat-percent-display`);
        const vatAmountEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .vat-amount-display`);
        if (vatPercentEl) {
            vatPercentEl.textContent = `${(item.tax_percent || 0).toFixed(1)}%`;
        }
        if (vatAmountEl) {
            vatAmountEl.textContent = this.getFormatCurrency()(this.calculateVATAmount(item));
        }
        
        // Update Nett display
        const nettEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .item-nett`);
        if (nettEl) {
            nettEl.textContent = this.getFormatCurrency()(this.calculateNett(item));
        }
        
        // Update Price/unit input so it stays in sync when total or unit changes (2 decimals)
        const priceEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .price-input`);
        if (priceEl) {
            const v = item.unit_price;
            priceEl.value = (v != null && v !== '' && !isNaN(Number(v))) ? this.roundMoney(v).toFixed(2) : '0.00';
        }
        
        // Update Total display (editable input) — always 2 decimals so user sees 50.00 not 49.99994
        const totalEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .total-input`);
        if (totalEl) {
            totalEl.value = this.roundMoney(item.total).toFixed(2);
        }
        
        // Update margin display in real-time (for sales and quotation)
        if (this.mode === 'sale' || this.mode === 'quotation') {
            this.updateMarginDisplay(rowIndex);
        }
        
        // Update stock indicator (3-tier display or available in selected unit) when unit or data changes
        const stockIndicator = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .stock-indicator`);
        if (stockIndicator && this.mode === 'sale' && (item.stock_display || typeof item.available_stock === 'number')) {
            if (item.stock_display) {
                // Use 3-tier formatted stock display
                const stockNum = typeof item.available_stock === 'number' ? item.available_stock : 0;
                let color = 'var(--success-color, #16a34a)';
                if (stockNum <= 0) color = 'var(--danger-color, #dc2626)';
                else if (stockNum < 5) color = 'var(--warning-color, #d97706)';
                stockIndicator.style.color = color;
                stockIndicator.textContent = 'Stock: ' + item.stock_display;
            } else {
                // Fallback to old format
                const avail = this.getAvailableInSelectedUnit(item);
                if (avail != null) {
                    let color = 'var(--success-color, #16a34a)';
                    if (avail <= 0) color = 'var(--danger-color, #dc2626)';
                    else if (avail < 5) color = 'var(--warning-color, #d97706)';
                    stockIndicator.style.color = color;
                    stockIndicator.textContent = 'Available: ' + this.getFormatNumber()(avail);
                }
            }
        }
        
        // Update summary footer
        const summary = this.calculateSummary();
        const nettTotalEl = document.getElementById(`${this.instanceId}_nett_total`);
        const vatTotalEl = document.getElementById(`${this.instanceId}_vat_total`);
        const totalEl2 = document.getElementById(`${this.instanceId}_total`);
        if (nettTotalEl) nettTotalEl.textContent = this.getFormatCurrency()(summary.nett);
        if (vatTotalEl) vatTotalEl.textContent = this.getFormatCurrency()(summary.vat);
        if (totalEl2) totalEl2.textContent = this.getFormatCurrency()(summary.total);
    };
    
    /**
     * Calculate total (inclusive of VAT)
     */
    TransactionItemsTable.prototype.calculateTotal = function() {
        const summary = this.calculateSummary();
        return summary.total;
    };
    
    /**
     * Remove item
     */
    TransactionItemsTable.prototype.removeItem = function(rowIndex) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        this.items.splice(rowIndex, 1);
        
        // Always ensure there's at least one empty row for adding new items
        const hasEmptyRow = this.items.length > 0 && 
            this.items.some(item => !item.item_id && !item.item_name);
        
        if (this.items.length === 0 || !hasEmptyRow) {
            this.items.push(this.createEmptyItem());
        }
        
        this.render();
        this.attachEventListeners();
        this.notifyChange();
    };
    
    /**
     * Close suggestions
     */
    TransactionItemsTable.prototype.closeSuggestions = function() {
        const dropdowns = document.querySelectorAll(`[id^="${this.instanceId}_suggestions_"]`);
        dropdowns.forEach(d => d.style.display = 'none');
        this.activeSearchRow = null;
    };
    
    /**
     * Clear row selection (for "Search for different item") – keep quantity 1, clear item and unit
     */
    TransactionItemsTable.prototype.clearRowSelection = function(rowIndex) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        const prev = this.items[rowIndex];
        this.items[rowIndex] = this.createEmptyItem();
        this.items[rowIndex].quantity = prev.quantity || 1;
        this.closeSelectedItemDropdown();
        this.render();
        this.attachEventListeners();
        const input = document.getElementById(`${this.instanceId}_item_${rowIndex}`);
        if (input) {
            input.focus();
            input.value = '';
        }
        this.notifyChange();
    };
    
    /**
     * Show dropdown for already-selected item. In sale mode shows Batch & Expiry (FEFO) instead of margin/VAT.
     */
    TransactionItemsTable.prototype.showSelectedItemDropdown = function(rowIndex) {
        const item = this.items[rowIndex];
        if (!item || !item.item_id) return;
        
        this.closeSuggestions();
        const container = this.mountEl.querySelector(`[data-instance-id="${this.instanceId}"]`);
        if (!container) return;
        
        let dropdown = document.getElementById(`${this.instanceId}_selected_${rowIndex}`);
        if (!dropdown) {
            dropdown = document.createElement('div');
            dropdown.id = `${this.instanceId}_selected_${rowIndex}`;
            dropdown.className = 'item-suggestions-dropdown selected-item-dropdown';
            container.appendChild(dropdown);
        }
        
        const input = document.getElementById(`${this.instanceId}_item_${rowIndex}`);
        if (!input) return;
        const containerRect = container.getBoundingClientRect();
        const inputRect = input.getBoundingClientRect();
        const relativeTop = inputRect.bottom - containerRect.top + 2;
        dropdown.style.cssText = `
            display: block; position: absolute; top: ${relativeTop}px; left: 0; width: 100%;
            background: white; border: 1px solid var(--border-color, #dee2e6); border-radius: 0.25rem;
            box-shadow: 0 6px 16px rgba(0,0,0,0.25); z-index: 1100; max-height: 320px; overflow-y: auto;
            font-size: 0.8rem; line-height: 1.3;
        `;
        
        const formatCurrency = this.getFormatCurrency();
        const escapeHtml = this.getEscapeHtml();
        const code = item.item_code || item.item_sku || '';
        const availInUnit = this.getAvailableInSelectedUnit(item);
        const stockStr = item.stock_display || (availInUnit != null ? this.getFormatNumber()(availInUnit) : (typeof item.available_stock === 'number' ? this.getFormatNumber()(item.available_stock) : 'N/A'));
        dropdown.innerHTML = `
            <div class="selected-item-details" style="padding: 0.75rem; border-bottom: 1px solid var(--border-color, #dee2e6);">
                <div style="font-weight: 600; margin-bottom: 0.35rem;">${escapeHtml(item.item_name || '')}</div>
                <div style="color: var(--text-secondary, #666); font-size: 0.8rem;">
                    Code: ${escapeHtml(code)} &nbsp;|&nbsp; Stock: ${stockStr}
                </div>
                <div id="${this.instanceId}_selected_batches_${rowIndex}" style="margin-top: 0.5rem; font-size: 0.75rem; color: var(--text-secondary, #666);">Loading batch/expiry…</div>
            </div>
            <div class="suggestion-item selected-item-action" data-action="search-different" data-row="${rowIndex}" style="padding: 0.5rem 0.75rem; cursor: pointer; display: flex; align-items: center; border-bottom: 1px solid var(--border-color, #dee2e6);" onmouseover="this.style.background='#f0f4ff'" onmouseout="this.style.background='white'">
                <i class="fas fa-search" style="color: var(--primary-color, #007bff); margin-right: 0.5rem;"></i>
                <span>Search for different item</span>
            </div>
            <div class="suggestion-item selected-item-action" data-action="view-details" data-row="${rowIndex}" data-item-id="${item.item_id}" style="padding: 0.5rem 0.75rem; cursor: pointer; display: flex; align-items: center;" onmouseover="this.style.background='#f0f4ff'" onmouseout="this.style.background='white'">
                <i class="fas fa-external-link-alt" style="color: var(--primary-color, #007bff); margin-right: 0.5rem;"></i>
                <span>View full item details</span>
            </div>
        `;
        
        this.activeSelectedItemRow = rowIndex;
        
        // In sale mode: fetch batches (FEFO) and show Batch # and Expiry — what will be deducted first
        const batchPlaceholder = document.getElementById(`${this.instanceId}_selected_batches_${rowIndex}`);
        if (this.mode === 'sale' && batchPlaceholder) {
            const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : null;
            const api = (typeof window !== 'undefined' && window.API) ? window.API : null;
            const branchId = config && config.BRANCH_ID ? config.BRANCH_ID : null;
            if (api && api.inventory && api.inventory.getBatches && branchId) {
                api.inventory.getBatches(item.item_id, branchId).then(function(batches) {
                    if (!batchPlaceholder.parentNode) return;
                    if (!batches || batches.length === 0) {
                        batchPlaceholder.innerHTML = '<span style="color: var(--text-secondary, #666);">No batch/expiry info</span>';
                        return;
                    }
                    const formatExpiry = function(d) {
                        if (!d) return '—';
                        try { return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }); } catch (e) { return d; }
                    };
                    let html = '<strong style="display: block; margin-bottom: 0.25rem;">Batch &amp; Expiry (FEFO — deducted first):</strong>';
                    batches.forEach(function(b, idx) {
                        const batchNum = (b.batch_number || '—');
                        const exp = formatExpiry(b.expiry_date);
                        const qty = typeof b.quantity === 'number' ? b.quantity : '';
                        html += '<div style="margin-bottom: 0.15rem;">' + (idx + 1) + '. Batch ' + escapeHtml(batchNum) + ' &nbsp; Expiry: ' + escapeHtml(exp) + (qty !== '' ? ' &nbsp; Qty: ' + qty : '') + '</div>';
                    });
                    batchPlaceholder.innerHTML = html;
                }).catch(function() {
                    if (batchPlaceholder.parentNode) batchPlaceholder.innerHTML = '<span style="color: var(--text-secondary, #666);">Batch/expiry unavailable</span>';
                });
            } else {
                batchPlaceholder.innerHTML = '<span style="color: var(--text-secondary, #666);">Batch/expiry unavailable</span>';
            }
        } else if (batchPlaceholder) {
            const sellingPrice = formatCurrency(item.unit_price || 0);
            const costPrice = (item.purchase_price != null && item.purchase_price !== '') ? formatCurrency(item.purchase_price) : null;
            const margin = (this.mode === 'quotation') ? this.formatMargin(this.calculateMargin(item)) : null;
            const vat = (item.tax_percent || 0).toFixed(1) + '%';
            const priceLine = costPrice ? `Selling: ${sellingPrice} &nbsp;|&nbsp; Cost: ${costPrice} &nbsp;|&nbsp; Margin: ${margin} &nbsp;|&nbsp; VAT: ${vat}` : `Price: ${sellingPrice} &nbsp;|&nbsp; VAT: ${vat}`;
            batchPlaceholder.innerHTML = priceLine;
        }
        
        dropdown.querySelectorAll('.selected-item-action').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const action = el.dataset.action;
                const r = parseInt(el.dataset.row);
                this.closeSelectedItemDropdown();
                if (action === 'search-different') {
                    this.clearRowSelection(r);
                } else if (action === 'view-details' && el.dataset.itemId) {
                    const itemId = el.dataset.itemId;
                    if (typeof window.showItemFullDetailsModal === 'function') {
                        window.showItemFullDetailsModal(itemId);
                    } else if (typeof window.loadPage === 'function') {
                        window.location.hash = '#items?item_id=' + encodeURIComponent(itemId);
                        window.loadPage('items');
                    } else {
                        window.location.hash = '#items?item_id=' + encodeURIComponent(itemId);
                    }
                }
            });
        });
    };
    
    /**
     * Close selected-item dropdown
     */
    TransactionItemsTable.prototype.closeSelectedItemDropdown = function() {
        const dropdowns = document.querySelectorAll(`[id^="${this.instanceId}_selected_"]`);
        dropdowns.forEach(d => { d.style.display = 'none'; });
        this.activeSelectedItemRow = null;
    };
    
    /**
     * Build 3-tier unit list from item fields (wholesale_unit, retail_unit, supplier_unit, pack_size, wholesale_units_per_supplier).
     * Used when API returns no/empty units or as fallback so user can always choose wholesale, retail, or supplier.
     */
    TransactionItemsTable.prototype.buildUnitsFrom3Tier = function(full) {
        const wholesaleName = (full.wholesale_unit || full.base_unit || 'piece').toString().trim() || 'piece';
        const retailName = (full.retail_unit || '').toString().trim();
        const supplierName = (full.supplier_unit || '').toString().trim();
        const pack = Math.max(1, parseInt(full.pack_size, 10) || 1);
        const wups = Math.max(0.0001, parseFloat(full.wholesale_units_per_supplier) || 1);
        const units = [];
        units.push({ unit_name: wholesaleName, multiplier_to_base: 1, is_default: true });
        if (retailName) {
            const sameAsWholesale = retailName.toLowerCase() === wholesaleName.toLowerCase();
            if (!(sameAsWholesale && pack === 1)) {
                units.push({ unit_name: retailName, multiplier_to_base: 1 / pack, is_default: false });
            }
        }
        if (supplierName && supplierName.toLowerCase() !== wholesaleName.toLowerCase()) {
            units.push({ unit_name: supplierName, multiplier_to_base: wups, is_default: false });
        }
        return units.length ? units : [{ unit_name: wholesaleName, multiplier_to_base: 1, is_default: true }];
    };

    /**
     * Load available units for a row (from API) and re-render unit cell.
     * Always shows wholesale, retail, supplier when item has 3-tier columns; default selection is wholesale.
     */
    TransactionItemsTable.prototype.loadUnitsForRow = async function(rowIndex) {
        const item = this.items[rowIndex];
        if (!item || !item.item_id) return;
        const api = (typeof window !== 'undefined' && window.API) ? window.API : null;
        if (!api || !api.items || !api.items.get) return;
        const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : (typeof CONFIG !== 'undefined' ? CONFIG : null);
        const branchId = config && config.BRANCH_ID ? config.BRANCH_ID : null;
        try {
            const full = await api.items.get(item.item_id, branchId);
            // Prefer API units if we have more than one; otherwise build from 3-tier columns so user can always choose
            let units = full.units && full.units.length > 1 ? full.units : this.buildUnitsFrom3Tier(full);
            item.available_units = units;
            // Cost per base (wholesale) unit for margin calculation
            if (typeof full.default_cost === 'number' && full.default_cost >= 0) {
                item.purchase_price = full.default_cost;
            }
            // Stock from API so row shows correct stock (avoids N/A when branch has stock)
            if (full.stock_display != null) item.stock_display = full.stock_display;
            if (typeof full.current_stock === 'number') item.available_stock = full.current_stock;
            // Default to wholesale (first unit) so user can change to retail/supplier if they want
            const wholesaleUnit = (units[0] && units[0].unit_name) || full.wholesale_unit || full.base_unit || 'piece';
            const currentUnit = item.unit_name || wholesaleUnit;
            const currentU = units.find(u => (u.unit_name || '') === currentUnit);
            item.unit_name = currentU ? currentUnit : wholesaleUnit;
            item.unit_multiplier = currentU ? (parseFloat(currentU.multiplier_to_base) || 1) : 1;
            this.recalculateRow(rowIndex);
            this.updateRowUnitSelect(rowIndex);
            this.updateRowDisplay(rowIndex);
        } catch (err) {
            console.warn('TransactionItemsTable: could not load units for item', item.item_id, err);
            item.available_units = [{ unit_name: item.unit_name || 'unit', multiplier_to_base: 1 }];
            item.unit_multiplier = 1;
            this.updateRowUnitSelect(rowIndex);
        }
    };
    
    /**
     * Refresh stock display for all items (called after batching invoice)
     */
    TransactionItemsTable.prototype.refreshStockForAllItems = async function() {
        const api = (typeof window !== 'undefined' && window.API) ? window.API : null;
        if (!api || !api.items || !api.items.search) return;
        const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : (typeof CONFIG !== 'undefined' ? CONFIG : null);
        if (!config || !config.COMPANY_ID || !config.BRANCH_ID) return;
        
        // Refresh stock for each item that has an item_id
        for (let i = 0; i < this.items.length; i++) {
            const item = this.items[i];
            if (item && item.item_id) {
                try {
                    // Search for the item to get updated stock_display
                    const results = await api.items.search(item.item_name || '', config.COMPANY_ID, 1, config.BRANCH_ID, false);
                    const updated = results.find(r => r.id === item.item_id);
                    if (updated && updated.stock_display) {
                        item.stock_display = updated.stock_display;
                        item.available_stock = updated.current_stock;
                        this.updateRowDisplay(i);
                    }
                } catch (err) {
                    console.warn('TransactionItemsTable: could not refresh stock for item', item.item_id, err);
                }
            }
        }
    };
    
    /**
     * Refresh cost, units and stock for all filled rows (e.g. after sales type / 3-tier unit change).
     * Re-fetches each item so unit list and cost are correct for current tier.
     */
    TransactionItemsTable.prototype.refreshPrices = async function() {
        for (let i = 0; i < this.items.length; i++) {
            if (this.items[i].item_id) {
                await this.loadUnitsForRow(i);
            }
        }
    };
    
    /**
     * Update only the unit cell for a row (avoid full re-render)
     */
    TransactionItemsTable.prototype.updateRowUnitSelect = function(rowIndex) {
        const row = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"]`);
        if (!row) return;
        const item = this.items[rowIndex];
        if (!item || !item.available_units || !item.available_units.length) return;
        const cell = row.querySelector('td:nth-child(4)'); // UNIT column
        if (!cell) return;
        const escapeHtml = this.getEscapeHtml();
        const units = item.available_units;
        let opts = units.map(u => {
            const sel = (item.unit_name || '') === (u.unit_name || '') ? ' selected' : '';
            return `<option value="${escapeHtml(u.unit_name)}" data-multiplier="${escapeHtml(String(u.multiplier_to_base || 1))}"${sel}>${escapeHtml(u.unit_name || '')}</option>`;
        }).join('');
        const select = document.createElement('select');
        select.className = 'form-input unit-select';
        select.dataset.row = String(rowIndex);
        select.dataset.field = 'unit_name';
        select.style.cssText = 'width: 100%; box-sizing: border-box; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);';
        if (!this.canEdit) select.disabled = true;
        select.innerHTML = opts;
        select.addEventListener('change', (e) => {
            const opt = e.target.options[e.target.selectedIndex];
            this.handleUnitChange(rowIndex, e.target.value, opt ? parseFloat(opt.dataset.multiplier) || 1 : 1);
        });
        cell.innerHTML = '';
        cell.appendChild(select);
    };
    
    /**
     * Handle unit change: recalc unit_price from multiplier, update quantity if needed, recalc row
     */
    TransactionItemsTable.prototype.handleUnitChange = function(rowIndex, unitName, newMultiplier) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        const item = this.items[rowIndex];
        if (!item) return;
        const oldMult = item.unit_multiplier || 1;
        item.unit_name = unitName;
        item.unit_multiplier = newMultiplier;
        // Recalculate unit price when unit changes (price per base * multiplier ratio)
        if (oldMult > 0 && newMultiplier > 0) {
            const basePrice = (item.unit_price || 0) / oldMult;
            item.unit_price = basePrice * newMultiplier;
        }
        this.recalculateRow(rowIndex);
        this.updateRowDisplay(rowIndex);
        this.updateMarginDisplay(rowIndex);
        this.notifyChange();
    };
    
    /**
     * Handle keyboard navigation in search
     */
    TransactionItemsTable.prototype.handleItemSearchKeydown = function(e, rowIndex) {
        const dropdown = document.getElementById(`${this.instanceId}_suggestions_${rowIndex}`);
        if (!dropdown || dropdown.style.display === 'none') return;
        
        const items = dropdown.querySelectorAll('.suggestion-item');
        const currentIndex = Array.from(items).findIndex(item => item.classList.contains('selected'));
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            const nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
            items.forEach((item, idx) => {
                item.classList.toggle('selected', idx === nextIndex);
            });
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const prevIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
            items.forEach((item, idx) => {
                item.classList.toggle('selected', idx === prevIndex);
            });
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const selected = dropdown.querySelector('.suggestion-item.selected') || items[0];
            if (selected) {
                if (selected.dataset.action === 'create') {
                    this.handleCreateItem(selected.dataset.query, rowIndex);
                } else {
                    this.handleSelectItem(selected, rowIndex);
                }
            }
        } else if (e.key === 'Escape') {
            this.closeSuggestions();
        }
    };
    
    /**
     * Move to next field
     */
    TransactionItemsTable.prototype.moveToNextField = function(currentInput) {
        const row = parseInt(currentInput.dataset.row);
        const field = currentInput.dataset.field;
        
        let nextField = null;
        if (field === 'quantity') nextField = 'unit_price';
        else if (field === 'unit_price') nextField = 'discount_percent';
        
        if (nextField) {
            const nextInput = document.querySelector(
                `#${this.instanceId}_tbody tr[data-item-index="${row}"] [data-field="${nextField}"]`
            );
            if (nextInput) nextInput.focus();
        }
    };
    
    /**
     * Notify change callbacks
     */
    TransactionItemsTable.prototype.notifyChange = function() {
        const validItems = this.items.filter(item => item.item_id && !item.is_empty);
        
        if (this.onItemsChange) {
            this.onItemsChange(validItems);
        }
        
        if (this.onTotalChange) {
            this.onTotalChange(this.calculateTotal());
        }
    };
    
    /**
     * Get valid items (public API)
     */
    TransactionItemsTable.prototype.getItems = function() {
        return this.items.filter(item => item.item_id && !item.is_empty);
    };
    
    /**
     * Open batch distribution modal
     */
    TransactionItemsTable.prototype.openBatchDistributionModal = async function(rowIndex, item) {
        if (!item || !item.item_id) {
            if (typeof showToast === 'function') {
                showToast('Please select an item first', 'error');
            }
            return;
        }
        
        // Get item details to check if batch tracking is required
        const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : null;
        const api = (typeof window !== 'undefined' && window.API) ? window.API : null;
        
        if (!config || !api) {
            if (typeof showToast === 'function') {
                showToast('Configuration error. Please refresh the page.', 'error');
            }
            return;
        }
        
        try {
            // Get item details to check batch tracking requirements
            let itemDetails = null;
            try {
                itemDetails = await api.items.get(item.item_id);
            } catch (error) {
                console.warn('Could not fetch item details:', error);
            }
            
            const requiresExpiry = itemDetails?.track_expiry || false;
            const baseUnit = itemDetails?.base_unit || '';
            
            // Get existing batches if any (stored in item.batches)
            const existingBatches = item.batches || [];
            
            // Open batch distribution modal
            if (typeof window.showBatchDistributionModal === 'function') {
                window.showBatchDistributionModal({
                    itemIndex: rowIndex,
                    itemId: item.item_id,
                    itemName: item.item_name,
                    totalQuantity: parseFloat(item.quantity) || 0,
                    unitName: item.unit_name || '',
                    unitCost: parseFloat(item.unit_price) || 0,
                    baseUnit: baseUnit,
                    requiresExpiry: requiresExpiry,
                    existingBatches: existingBatches
                });
                
                // Set callback for when batches are saved
                window.onBatchDistributionSave = (savedItemIndex, batches) => {
                    if (savedItemIndex === rowIndex) {
                        // Store batches in item
                        if (!this.items[rowIndex]) return;
                        this.items[rowIndex].batches = batches;
                        // Trigger change notification
                        this.notifyChange();
                    }
                };
            } else {
                if (typeof showToast === 'function') {
                    showToast('Batch distribution feature not available', 'error');
                }
            }
        } catch (error) {
            console.error('Error opening batch distribution modal:', error);
            if (typeof showToast === 'function') {
                showToast('Error opening batch distribution: ' + (error.message || 'Unknown error'), 'error');
            }
        }
    };
    
    /**
     * Helper functions
     */
    TransactionItemsTable.prototype.getFormatCurrency = function() {
        return typeof window.formatCurrency === 'function'
            ? window.formatCurrency
            : (amount) => new Intl.NumberFormat('en-KE', {
                style: 'currency',
                currency: 'KES',
                minimumFractionDigits: 2
            }).format(amount || 0);
    };
    
    TransactionItemsTable.prototype.getFormatNumber = function() {
        return typeof window.formatNumber === 'function'
            ? window.formatNumber
            : (num) => (num || 0).toLocaleString('en-KE', { 
                minimumFractionDigits: 0, 
                maximumFractionDigits: 4 
            });
    };
    
    TransactionItemsTable.prototype.getEscapeHtml = function() {
        return typeof window.escapeHtml === 'function'
            ? window.escapeHtml
            : (text) => {
                const div = document.createElement('div');
                div.textContent = text || '';
                return div.innerHTML;
            };
    };
    
    // Export to global scope
    window.TransactionItemsTable = TransactionItemsTable;
    
    // Auto-focus first input field on page load (DOMContentLoaded)
    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(() => {
                const firstItemInput = document.querySelector('.item-search-input');
                if (firstItemInput) {
                    firstItemInput.focus();
                    // Place cursor at end if there's any text
                    if (firstItemInput.value) {
                        firstItemInput.setSelectionRange(firstItemInput.value.length, firstItemInput.value.length);
                    }
                }
            }, 500); // Changed from 100 to 500
        });
    }
    
})();
