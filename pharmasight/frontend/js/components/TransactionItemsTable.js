/**
 * TransactionItemsTable Component - Phase 1 (Incremental Introduction)
 * 
 * A reusable component for table-driven item entry in transactions.
 * This is Phase 1: Basic table rendering only, no integration yet.
 * 
 * CRITICAL: This component has NO side effects on load.
 * It does nothing until explicitly instantiated.
 */

(function() {
    'use strict';
    
    /**
     * TransactionItemsTable Constructor
     * 
     * @param {Object} options - Component configuration
     * @param {string|HTMLElement} mountElOrId - Element ID string or DOM element where table will be mounted
     * @param {Object} options - Component configuration (optional if mountElOrId is an object with all options)
     * @param {string} options.mode - Transaction mode: 'sale' | 'purchase'
     * @param {Array} options.items - Initial array of items (optional, alias for itemsSource)
     * @param {Array} options.itemsSource - Initial array of items (optional, alias for items)
     * @param {string} options.priceType - Price type: 'sale_price' | 'purchase_price' (optional, for future use)
     * @param {Function} options.onItemsChange - Callback when items change (optional, Phase 1: not implemented yet)
     * @param {Function} options.onTotalChange - Callback when total changes (optional, Phase 1: not implemented yet)
     */
    function TransactionItemsTable(mountElOrId, options) {
        // Handle two calling patterns:
        // 1. TransactionItemsTable('elementId', { mode: 'purchase', items: [...] })
        // 2. TransactionItemsTable({ mountEl: 'elementId', mode: 'purchase', items: [...] })
        
        if (typeof mountElOrId === 'object' && !mountElOrId.nodeType) {
            // Single object pattern
            options = mountElOrId;
            mountElOrId = options.mountEl;
        }
        
        if (!options) {
            options = {};
        }
        // Validate required options
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
        
        this.mode = options.mode || 'purchase';
        // Support both 'items' and 'itemsSource' for compatibility
        this.itemsSource = options.items || options.itemsSource || [];
        this.priceType = options.priceType || (this.mode === 'sale' ? 'sale_price' : 'purchase_price');
        
        // Store callbacks (Phase 1: stored but not actively used yet)
        this.onItemsChange = options.onItemsChange || null;
        this.onTotalChange = options.onTotalChange || null;
        
        // Internal state
        this.items = this.normalizeItems(this.itemsSource);
        
        // Render the table
        this.render();
    }
    
    /**
     * Normalize items array to internal format
     */
    TransactionItemsTable.prototype.normalizeItems = function(items) {
        if (!Array.isArray(items)) {
            return [];
        }
        
        return items.map(item => ({
            item_id: item.item_id || item.id || null,
            item_name: item.item_name || item.name || '',
            item_sku: item.item_sku || item.sku || '',
            unit_name: item.unit_name || item.unit || '',
            quantity: item.quantity || 0,
            unit_price: item.unit_price || item.price || 0,
            total: item.total || (item.quantity || 0) * (item.unit_price || item.price || 0)
        }));
    };
    
    /**
     * Render the table
     * Phase 1: Basic table only, no search dropdown, no advanced features
     */
    TransactionItemsTable.prototype.render = function() {
        const total = this.items.reduce((sum, item) => sum + (item.total || 0), 0);
        
        // Escape HTML helper (local fallback if not global)
        const escapeHtml = typeof window.escapeHtml === 'function' 
            ? window.escapeHtml 
            : function(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            };
        
        // Format currency helper (local fallback if not global)
        const formatCurrency = typeof window.formatCurrency === 'function'
            ? window.formatCurrency
            : function(amount) {
                return new Intl.NumberFormat('en-KE', {
                    style: 'currency',
                    currency: 'KES'
                }).format(amount || 0);
            };
        
        // Format number helper (local fallback if not global)
        const formatNumber = typeof window.formatNumber === 'function'
            ? window.formatNumber
            : function(num) {
                return (num || 0).toLocaleString('en-KE', { minimumFractionDigits: 0, maximumFractionDigits: 4 });
            };
        
        // Build table HTML
        let html = `
            <div class="transaction-items-table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 2px solid var(--border-color, #e0e0e0);">
                            <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Item</th>
                            <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Unit</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600;">Quantity</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600;">Unit Price</th>
                            <th style="padding: 0.75rem; text-align: right; font-weight: 600;">Total</th>
                            <th style="padding: 0.75rem; text-align: center; font-weight: 600;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="${this.mountEl.id}_tbody">
        `;
        
        // Render items rows
        if (this.items.length === 0) {
            html += `
                <tr>
                    <td colspan="6" style="padding: 2rem; text-align: center; color: var(--text-secondary, #666);">
                        No items added yet
                    </td>
                </tr>
            `;
        } else {
            this.items.forEach((item, index) => {
                html += `
                    <tr data-item-index="${index}">
                        <td style="padding: 0.75rem;">
                            <input type="text" 
                                   class="form-input" 
                                   value="${escapeHtml(item.item_name)}" 
                                   placeholder="Item name"
                                   style="width: 100%;"
                                   readonly
                                   data-field="item_name"
                                   data-row="${index}">
                        </td>
                        <td style="padding: 0.75rem;">
                            ${escapeHtml(item.unit_name || '—')}
                        </td>
                        <td style="padding: 0.75rem;">
                            <input type="number" 
                                   class="form-input" 
                                   value="${item.quantity || 0}" 
                                   step="0.01" 
                                   min="0"
                                   style="width: 100%; text-align: right;"
                                   data-field="quantity"
                                   data-row="${index}">
                        </td>
                        <td style="padding: 0.75rem;">
                            <input type="number" 
                                   class="form-input" 
                                   value="${item.unit_price || 0}" 
                                   step="0.01" 
                                   min="0"
                                   style="width: 100%; text-align: right;"
                                   data-field="unit_price"
                                   data-row="${index}">
                        </td>
                        <td style="padding: 0.75rem; text-align: right;">
                            ${formatCurrency(item.total || 0)}
                        </td>
                        <td style="padding: 0.75rem; text-align: center;">
                            <button class="btn btn-outline" 
                                    onclick="if(window.removeTransactionItem) window.removeTransactionItem('${this.mountEl.id}', ${index})"
                                    title="Remove">
                                <i class="fas fa-trash"></i>
                            </button>
                        </td>
                    </tr>
                `;
            });
        }
        
        // Close tbody and add footer
        html += `
                    </tbody>
                    <tfoot>
                        <tr style="border-top: 2px solid var(--border-color, #e0e0e0); font-weight: 600;">
                            <td colspan="4" style="padding: 0.75rem; text-align: right;">Total:</td>
                            <td style="padding: 0.75rem; text-align: right;">${formatCurrency(total)}</td>
                            <td></td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        `;
        
        // Mount to DOM
        this.mountEl.innerHTML = html;
    };
    
    /**
     * Get current items (public API for future use)
     */
    TransactionItemsTable.prototype.getItems = function() {
        return this.items.map(item => ({ ...item }));
    };
    
    /**
     * Update item at index (public API for future use)
     */
    TransactionItemsTable.prototype.updateItem = function(index, updates) {
        if (index >= 0 && index < this.items.length) {
            this.items[index] = { ...this.items[index], ...updates };
            // Recalculate total
            this.items[index].total = (this.items[index].quantity || 0) * (this.items[index].unit_price || 0);
            // Re-render
            this.render();
        }
    };
    
    // Export to global scope (NO side effects - only defines the constructor)
    window.TransactionItemsTable = TransactionItemsTable;
    
})();
