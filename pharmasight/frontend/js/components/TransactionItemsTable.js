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
        this.itemsSource = options.items || options.itemsSource || [];
        this.priceType = options.priceType || (this.mode === 'sale' ? 'sale_price' : 'purchase_price');
        this.onItemsChange = options.onItemsChange || null;
        this.onTotalChange = options.onTotalChange || null;
        this.onItemCreate = options.onItemCreate || null; // Callback for creating new items
        
        // Internal state
        this.items = this.normalizeItems(this.itemsSource);
        this.searchTimeout = null;
        this.searchAbortController = null;
        this.activeSearchRow = null;
        this.inputDebounceTimeout = null; // For debouncing input events
        
        // Always add one empty row for new item entry
        if (this.items.length === 0) {
            this.items.push(this.createEmptyItem());
        }
        
        // Render
        this.render();
        this.attachEventListeners();
    }
    
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
            is_empty: true
        };
    };
    
    /**
     * Normalize items array
     */
    TransactionItemsTable.prototype.normalizeItems = function(items) {
        if (!Array.isArray(items)) return [];
        return items.map(item => ({
            item_id: item.item_id || item.id || null,
            item_name: item.item_name || item.name || '',
            item_sku: item.item_sku || item.sku || '',
            item_code: item.item_code || item.code || '',
            unit_name: item.unit_name || item.unit || '',
            quantity: item.quantity || 1,
            unit_price: item.unit_price || item.price || 0,
            purchase_price: item.purchase_price || 0, // Store purchase price for margin calculation
            discount_percent: item.discount_percent || 0,
            tax_percent: item.tax_percent || 0,
            total: item.total || 0,
            is_empty: false
        }));
    };
    
    /**
     * Calculate margin percentage
     */
    TransactionItemsTable.prototype.calculateMargin = function(item) {
        if (this.mode !== 'sale') return 0;
        const purchasePrice = item.purchase_price || 0;
        const salePrice = item.unit_price || 0;
        if (purchasePrice <= 0) return 0;
        return ((salePrice - purchasePrice) / purchasePrice) * 100;
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
            <div class="transaction-items-table-container" data-instance-id="${this.instanceId}">
                <table style="width: 100%; border-collapse: collapse; background: white;">
                    <thead>
                        <tr style="background: #f8f9fa; border-bottom: 2px solid var(--border-color, #dee2e6);">
                            <th style="padding: 0.75rem; text-align: left; font-weight: 600; width: 30%;">ITEM</th>
                            <th style="padding: 0.75rem; text-align: left; font-weight: 600; width: 10%;">ITEM CODE</th>
                            <th style="padding: 0.75rem; text-align: center; font-weight: 600; width: 8%;">QTY</th>
                            <th style="padding: 0.75rem; text-align: left; font-weight: 600; width: 8%;">UNIT</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 10%;">PRICE/UNIT</th>
                            ${this.mode === 'sale' ? '<th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 8%;">MARGIN%</th>' : ''}
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 8%;">DISCOUNT%</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600; width: 12%;">AMOUNT</th>
                            <th style="padding: 0.75rem; text-align: center; font-weight: 600; width: 10%;">ACTIONS</th>
                        </tr>
                    </thead>
                    <tbody id="${this.instanceId}_tbody">
        `;
        
        // Render item rows
        this.items.forEach((item, index) => {
            const isSearching = this.activeSearchRow === index;
            html += `
                <tr data-item-index="${index}" data-row-id="${this.instanceId}_row_${index}">
                    <td style="padding: 0.25rem; position: relative;">
                        <input type="text" 
                               class="form-input item-search-input" 
                               id="${this.instanceId}_item_${index}"
                               value="${escapeHtml(item.item_name)}" 
                               placeholder="Type item name or code..."
                               autocomplete="off"
                               data-row="${index}"
                               style="width: 100%; border: ${isSearching ? '2px solid var(--primary-color, #007bff)' : '1px solid var(--border-color, #dee2e6)'}; padding: 0.5rem;"
                               ${item.item_id ? 'readonly' : ''}>
                        <div id="${this.instanceId}_suggestions_${index}" 
                             class="item-suggestions-dropdown" 
                             style="display: none; position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid var(--border-color, #dee2e6); border-radius: 0.25rem; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 1000; max-height: 300px; overflow-y: auto; margin-top: 2px;">
                        </div>
                    </td>
                    <td style="padding: 0.25rem;">
                        <input type="text" 
                               class="form-input" 
                               value="${escapeHtml(item.item_code || item.item_sku || '')}" 
                               placeholder="Code"
                               readonly
                               style="width: 100%; padding: 0.5rem; background: #f8f9fa; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="item_code">
                    </td>
                    <td style="padding: 0.25rem;">
                        <input type="number" 
                               class="form-input qty-input" 
                               value="${item.quantity || 1}" 
                               step="0.01" 
                               min="0.01"
                               style="width: 100%; text-align: center; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="quantity">
                    </td>
                    <td style="padding: 0.25rem;">
                        <input type="text" 
                               class="form-input" 
                               value="${escapeHtml(item.unit_name || '')}" 
                               placeholder="Unit"
                               readonly
                               style="width: 100%; padding: 0.5rem; background: #f8f9fa; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="unit_name">
                    </td>
                    <td style="padding: 0.25rem;">
                        <input type="number" 
                               class="form-input price-input" 
                               value="${item.unit_price || 0}" 
                               step="0.01" 
                               min="0"
                               style="width: 100%; text-align: right; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="unit_price">
                    </td>
                    ${this.mode === 'sale' ? `
                    <td style="padding: 0.25rem; text-align: right;">
                        <span class="margin-display" 
                              data-row="${index}"
                              style="font-weight: 500; color: ${this.calculateMargin(item) >= 0 ? 'var(--success-color, #10b981)' : 'var(--danger-color, #ef4444)'};">
                            ${this.formatMargin(this.calculateMargin(item))}
                        </span>
                    </td>
                    ` : ''}
                    <td style="padding: 0.25rem;">
                        <input type="number" 
                               class="form-input discount-input" 
                               value="${item.discount_percent || 0}" 
                               step="0.01" 
                               min="0"
                               max="100"
                               style="width: 100%; text-align: right; padding: 0.5rem; border: 1px solid var(--border-color, #dee2e6);"
                               data-row="${index}"
                               data-field="discount_percent">
                    </td>
                    <td style="padding: 0.25rem; text-align: right; font-weight: 600;">
                        <span class="item-total" data-row="${index}">${formatCurrency(item.total || 0)}</span>
                    </td>
                    <td style="padding: 0.25rem; text-align: center;">
                        ${item.is_empty ? '' : `
                            <button type="button" 
                                    class="btn btn-outline btn-sm remove-item-btn" 
                                    data-row="${index}"
                                    title="Remove item"
                                    style="padding: 0.25rem 0.5rem; font-size: 0.875rem;">
                                <i class="fas fa-trash"></i>
                            </button>
                        `}
                    </td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                    <tfoot>
                        <tr style="background: #f8f9fa; border-top: 2px solid var(--border-color, #dee2e6); font-weight: 600;">
                            <td colspan="6" style="padding: 0.75rem; text-align: right;">Total:</td>
                            <td style="padding: 0.75rem; text-align: right; font-size: 1.1rem;" id="${this.instanceId}_total">${formatCurrency(total)}</td>
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
                this.handleItemSearch(e.target.value, row);
            }
        });
        
        tbody.addEventListener('keydown', (e) => {
            if (e.target.classList.contains('item-search-input')) {
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
            }
        });
        
        // Quantity, price, discount change handlers (on blur/enter)
        tbody.addEventListener('change', (e) => {
            if (e.target.classList.contains('qty-input') || 
                e.target.classList.contains('price-input') || 
                e.target.classList.contains('discount-input')) {
                const row = parseInt(e.target.dataset.row);
                const field = e.target.dataset.field;
                this.handleFieldChange(row, field, e.target.value);
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
        });
        
        // Remove item button
        tbody.addEventListener('click', (e) => {
            if (e.target.closest('.remove-item-btn')) {
                const row = parseInt(e.target.closest('.remove-item-btn').dataset.row);
                this.removeItem(row);
            }
        });
        
        // Click outside to close suggestions
        document.addEventListener('click', (e) => {
            if (!e.target.closest(`[data-instance-id="${this.instanceId}"]`)) {
                this.closeSuggestions();
            }
        });
    };
    
    /**
     * Handle item search
     */
    TransactionItemsTable.prototype.handleItemSearch = function(query, rowIndex) {
        const queryTrimmed = query.trim();
        
        // Clear previous timeout
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        
        // Abort previous request
        if (this.searchAbortController) {
            this.searchAbortController.abort();
        }
        
        if (queryTrimmed.length < 2) {
            this.closeSuggestions();
            return;
        }
        
        // Show loading
        this.activeSearchRow = rowIndex;
        this.showSuggestions(rowIndex, [{ type: 'loading', message: 'Searching...' }]);
        
        // Debounce search
        this.searchTimeout = setTimeout(() => {
            this.performItemSearch(queryTrimmed, rowIndex);
        }, 300);
    };
    
    /**
     * Perform item search via API
     */
    TransactionItemsTable.prototype.performItemSearch = async function(query, rowIndex) {
        // Check for CONFIG and API availability
        // Try both window.CONFIG and global CONFIG
        const config = (typeof window !== 'undefined' && window.CONFIG) ? window.CONFIG : (typeof CONFIG !== 'undefined' ? CONFIG : null);
        
        if (!config || !config.COMPANY_ID) {
            console.warn('TransactionItemsTable: CONFIG.COMPANY_ID not available', {
                hasWindow: typeof window !== 'undefined',
                hasWindowConfig: typeof window !== 'undefined' && !!window.CONFIG,
                hasGlobalConfig: typeof CONFIG !== 'undefined',
                companyId: config ? config.COMPANY_ID : null
            });
            this.showSuggestions(rowIndex, [{ 
                type: 'error', 
                message: 'Configuration error. Please set Company ID in Settings.' 
            }]);
            return;
        }
        
        const api = (typeof window !== 'undefined' && window.API) ? window.API : null;
        if (!api || !api.items || !api.items.search) {
            console.warn('TransactionItemsTable: API.items.search not available');
            this.showSuggestions(rowIndex, [{ 
                type: 'error', 
                message: 'API not available. Please refresh the page.' 
            }]);
            return;
        }
        
        this.searchAbortController = new AbortController();
        
        try {
            console.log('TransactionItemsTable: Searching items with query:', query, 'company_id:', config.COMPANY_ID, 'branch_id:', config.BRANCH_ID);
            // Include branch_id for pricing calculation
            const searchParams = { q: query, company_id: config.COMPANY_ID, limit: 10 };
            if (config.BRANCH_ID) {
                searchParams.branch_id = config.BRANCH_ID;
            }
            const items = await api.items.search(query, config.COMPANY_ID, 10, config.BRANCH_ID || null);
            console.log('TransactionItemsTable: Search returned', items.length, 'items');
            
            if (items.length === 0) {
                // Show "Create Item" option
                this.showSuggestions(rowIndex, [
                    { 
                        type: 'create', 
                        query: query,
                        message: `Create new item: "${query}"`
                    }
                ]);
            } else {
                // Show search results
                this.showSuggestions(rowIndex, items.map(item => ({
                    type: 'item',
                    ...item
                })));
            }
        } catch (error) {
            console.error('Item search error:', error);
            this.showSuggestions(rowIndex, [
                { type: 'error', message: error.message || 'Search failed' },
                { 
                    type: 'create', 
                    query: query,
                    message: `Create new item: "${query}"`
                }
            ]);
        }
    };
    
    /**
     * Show suggestions dropdown
     */
    TransactionItemsTable.prototype.showSuggestions = function(rowIndex, suggestions) {
        const dropdown = document.getElementById(`${this.instanceId}_suggestions_${rowIndex}`);
        if (!dropdown) return;
        
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
                         style="padding: 0.75rem; border-bottom: 1px solid var(--border-color, #dee2e6); cursor: pointer; background: #e7f3ff;"
                         onmouseover="this.style.background='#d0e7ff'" 
                         onmouseout="this.style.background='#e7f3ff'">
                        <i class="fas fa-plus-circle" style="color: var(--primary-color, #007bff); margin-right: 0.5rem;"></i>
                        <strong>${escapeHtml(suggestion.message)}</strong>
                    </div>
                `;
            } else if (suggestion.type === 'item') {
                const salePrice = suggestion.sale_price || 0;
                const purchasePrice = suggestion.purchase_price || 0;
                const stock = suggestion.current_stock || 0;
                
                html += `
                    <div class="suggestion-item suggestion-item-option" 
                         data-item-id="${suggestion.id}"
                         data-item-name="${escapeHtml(suggestion.name)}"
                         data-item-sku="${escapeHtml(suggestion.sku || '')}"
                         data-item-code="${escapeHtml(suggestion.code || suggestion.sku || '')}"
                         data-unit-name="${escapeHtml(suggestion.base_unit || '')}"
                         data-sale-price="${salePrice}"
                         data-purchase-price="${purchasePrice}"
                         data-stock="${stock}"
                         style="padding: 0.75rem; border-bottom: 1px solid var(--border-color, #dee2e6); cursor: pointer;"
                         onmouseover="this.style.background='#f8f9fa'" 
                         onmouseout="this.style.background='white'">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div style="flex: 1;">
                                <div style="font-weight: 600; margin-bottom: 0.25rem;">${escapeHtml(suggestion.name)}</div>
                                <div style="font-size: 0.875rem; color: var(--text-secondary, #666);">
                                    ${escapeHtml(suggestion.sku || suggestion.code || '')} | Stock: ${stock} ${escapeHtml(suggestion.base_unit || '')}
                                    ${suggestion.last_supplier ? `<br>Last Supplier: <strong>${escapeHtml(suggestion.last_supplier)}</strong>` : ''}
                                    ${suggestion.last_order_date ? `<br>Last Order: ${new Date(suggestion.last_order_date).toLocaleDateString()}` : ''}
                                </div>
                            </div>
                            <div style="text-align: right; margin-left: 1rem;">
                                <div style="font-size: 0.875rem; color: var(--text-secondary, #666);">Sale: ${formatCurrency(salePrice)}</div>
                                <div style="font-size: 0.875rem; color: var(--text-secondary, #666);">Purchase: ${formatCurrency(purchasePrice)}</div>
                            </div>
                        </div>
                    </div>
                `;
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
        const item = {
            item_id: suggestionEl.dataset.itemId,
            item_name: suggestionEl.dataset.itemName,
            item_sku: suggestionEl.dataset.itemSku,
            item_code: suggestionEl.dataset.itemCode,
            unit_name: suggestionEl.dataset.unitName,
            unit_price: this.mode === 'sale' 
                ? parseFloat(suggestionEl.dataset.salePrice) 
                : parseFloat(suggestionEl.dataset.purchasePrice),
            purchase_price: parseFloat(suggestionEl.dataset.purchasePrice) || 0, // Store purchase price for margin
            quantity: this.items[rowIndex].quantity || 1,
            discount_percent: 0,
            tax_percent: 0,
            is_empty: false
        };
        
        // Update item
        this.items[rowIndex] = item;
        this.recalculateRow(rowIndex);
        this.closeSuggestions();
        this.render();
        this.attachEventListeners();
        
        // Focus on quantity field
        setTimeout(() => {
            const qtyInput = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .qty-input`);
            if (qtyInput) qtyInput.focus();
        }, 100);
        
        // Add new empty row if this was the last row
        if (rowIndex === this.items.length - 1) {
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
     * Handle field change (qty, price, discount)
     */
    TransactionItemsTable.prototype.handleFieldChange = function(rowIndex, field, value) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        
        const numValue = parseFloat(value) || 0;
        this.items[rowIndex][field] = numValue;
        this.recalculateRow(rowIndex);
        this.updateRowDisplay(rowIndex);
        this.updateMarginDisplay(rowIndex); // Update margin when price changes
        this.notifyChange();
    };
    
    /**
     * Update margin display for a row
     */
    TransactionItemsTable.prototype.updateMarginDisplay = function(rowIndex) {
        if (this.mode !== 'sale') return;
        
        const item = this.items[rowIndex];
        if (!item) return;
        
        const marginEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .margin-display`);
        if (marginEl) {
            const margin = this.calculateMargin(item);
            marginEl.textContent = this.formatMargin(margin);
            marginEl.style.color = margin >= 0 ? 'var(--success-color, #10b981)' : 'var(--danger-color, #ef4444)';
        }
    };
    
    /**
     * Recalculate row total
     */
    TransactionItemsTable.prototype.recalculateRow = function(rowIndex) {
        const item = this.items[rowIndex];
        if (!item) return;
        
        const subtotal = (item.quantity || 0) * (item.unit_price || 0);
        const discount = subtotal * ((item.discount_percent || 0) / 100);
        const afterDiscount = subtotal - discount;
        const tax = afterDiscount * ((item.tax_percent || 0) / 100);
        item.total = afterDiscount + tax;
    };
    
    /**
     * Update row display
     */
    TransactionItemsTable.prototype.updateRowDisplay = function(rowIndex) {
        const item = this.items[rowIndex];
        if (!item) return;
        
        const totalEl = document.querySelector(`#${this.instanceId}_tbody tr[data-item-index="${rowIndex}"] .item-total`);
        if (totalEl) {
            totalEl.textContent = this.getFormatCurrency()(item.total || 0);
        }
        
        // Update margin display in real-time (for sales mode)
        if (this.mode === 'sale') {
            this.updateMarginDisplay(rowIndex);
        }
        
        const totalEl2 = document.getElementById(`${this.instanceId}_total`);
        if (totalEl2) {
            totalEl2.textContent = this.getFormatCurrency()(this.calculateTotal());
        }
    };
    
    /**
     * Calculate total
     */
    TransactionItemsTable.prototype.calculateTotal = function() {
        return this.items.reduce((sum, item) => sum + (item.total || 0), 0);
    };
    
    /**
     * Remove item
     */
    TransactionItemsTable.prototype.removeItem = function(rowIndex) {
        if (rowIndex < 0 || rowIndex >= this.items.length) return;
        this.items.splice(rowIndex, 1);
        
        // Ensure at least one empty row
        if (this.items.length === 0) {
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
    
})();
