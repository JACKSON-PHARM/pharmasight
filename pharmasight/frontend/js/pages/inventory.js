// Inventory Management Page with Sidebar Navigation

let currentInventorySubPage = 'items'; // items, batch, expiry, movement, stock

/** Branch for stock/last supplier: session branch (same as header), then CONFIG, then localStorage. */
function getBranchIdForStock() {
    const branch = typeof BranchContext !== 'undefined' && BranchContext.getBranch ? BranchContext.getBranch() : null;
    if (branch && branch.id) return branch.id;
    if (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) return CONFIG.BRANCH_ID;
    try {
        const saved = localStorage.getItem('pharmasight_config');
        if (saved) {
            const c = JSON.parse(saved);
            if (c.BRANCH_ID) return c.BRANCH_ID;
        }
    } catch (e) { /* ignore */ }
    return null;
}

// Declare functions first (hoisting)
async function loadInventory() {
    console.log('loadInventory called');
    const page = document.getElementById('inventory');
    
    if (!page) {
        console.error('Inventory page element not found');
        return;
    }
    
    try {
        if (!CONFIG.COMPANY_ID) {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>Please set up your company and branch first.</p>
                        <button class="btn btn-primary mt-2" onclick="window.location.hash='#setup'; loadPage('setup');">
                            Go to Setup
                        </button>
                    </div>
                </div>
            `;
            return;
        }
        // Use session branch (same as header) for stock and last supplier
        const sessionBranchId = getBranchIdForStock();
        if (sessionBranchId && CONFIG.BRANCH_ID !== sessionBranchId) {
            CONFIG.BRANCH_ID = sessionBranchId;
            if (typeof saveConfig === 'function') saveConfig();
        }
        
        // Initialize with Items sub-page
        currentInventorySubPage = 'items';
        renderInventoryPage();
    } catch (error) {
        console.error('Error loading inventory page:', error);
        console.error('Error stack:', error.stack);
        page.innerHTML = `
            <div class="card">
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>Error loading inventory page: ${error.message}</p>
                    <pre>${error.stack}</pre>
                </div>
            </div>
        `;
    }
}

function renderInventoryPage() {
    const page = document.getElementById('inventory');
    if (!page) return;
    
    try {
        // Remove inline sidebar - now using main sidebar sub-navigation
        page.innerHTML = `
            <div style="background: white; border-radius: 8px; padding: 1.5rem; box-shadow: var(--shadow); min-height: calc(100vh - 120px);">
                <div id="inventorySubPageContent">
                    ${renderSubPageContent()}
                </div>
            </div>
        `;
        
        // Update sub-nav active state based on current sub-page (with delay to ensure DOM is ready)
        setTimeout(updateSubNavActiveState, 50);
        
        // Load sub-page data
        loadSubPageData();
    } catch (error) {
        console.error('Error in renderInventoryPage:', error);
        page.innerHTML = `
            <div class="card">
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>Error rendering inventory page: ${error.message}</p>
                    <pre>${error.stack}</pre>
                </div>
            </div>
        `;
    }
}

function renderSubPageContent() {
    try {
        switch(currentInventorySubPage) {
            case 'items':
                return renderItemsSubPage();
            case 'batch':
                return renderBatchTrackingSubPage();
            case 'expiry':
                return renderExpiryReportSubPage();
            case 'movement':
                return renderItemMovementSubPage();
            case 'stock':
                return renderCurrentStockSubPage();
            default:
                return '<p>Sub-page not found</p>';
        }
    } catch (error) {
        console.error('Error in renderSubPageContent:', error);
        return `<div class="alert alert-danger">Error rendering content: ${error.message}</div>`;
    }
}

// Update sub-nav active state
function updateSubNavActiveState() {
    try {
        const subNavItems = document.querySelectorAll('.sub-nav-item');
        if (subNavItems.length === 0) {
            // Sub-nav not loaded yet, try again after a short delay
            setTimeout(updateSubNavActiveState, 100);
            return;
        }
        
        subNavItems.forEach(item => {
            const subPage = item.dataset.subPage;
            if (subPage === currentInventorySubPage) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    } catch (error) {
        console.warn('Error updating sub-nav active state:', error);
    }
}

function switchInventorySubPage(subPage) {
    currentInventorySubPage = subPage;
    renderInventoryPage();
    // Update sub-nav active state after a short delay to ensure DOM is ready
    setTimeout(updateSubNavActiveState, 50);
}

// ============================================
// ITEMS SUB-PAGE
// ============================================
function renderItemsSubPage() {
    return `
        <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <h2 style="margin: 0;"><i class="fas fa-box"></i> Items Management</h2>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="downloadItemTemplate()">
                        <i class="fas fa-download"></i> Download Template
                    </button>
                    <button class="btn btn-outline" onclick="clearForReimport()" id="clearForReimportBtn" title="Clear all items and data for this company so you can run a fresh Excel import (only when no sales/purchases yet)">
                        <i class="fas fa-broom"></i> Clear for re-import
                    </button>
                    <button class="btn btn-secondary" onclick="showImportExcelModal()">
                        <i class="fas fa-file-excel"></i> Import Excel
                    </button>
                    <button class="btn btn-primary" onclick="showAddItemModal()">
                        <i class="fas fa-plus"></i> New Item
                    </button>
                </div>
            </div>
            
            <div style="margin-bottom: 1rem;">
                <input 
                    type="text" 
                    id="itemsSearchInput" 
                    class="form-input" 
                    placeholder="Search by name, SKU, or category... (Type to search)" 
                    oninput="filterItems()"
                    style="max-width: 400px;"
                >
                <small style="color: var(--text-secondary); font-size: 0.875rem; display: block; margin-top: 0.25rem;">
                    <i class="fas fa-info-circle"></i> Search is optimized for 20,000+ items. Type at least 2 characters.
                </small>
            </div>
            
            <div id="itemsTableContainer">
                <div class="spinner"></div>
            </div>
        </div>
    `;
}

let inventoryItemsList = [];
let inventoryFilteredItemsList = [];
let inventorySearchTimeout = null;
let isInventorySearching = false;

async function loadSubPageData() {
    switch(currentInventorySubPage) {
        case 'items':
            await loadItemsData();
            break;
        case 'batch':
            await loadBatchTrackingData();
            break;
        case 'expiry':
            await loadExpiryReportData();
            break;
        case 'movement':
            await loadItemMovementData();
            break;
        case 'stock':
            await loadCurrentStockData();
            break;
    }
}

async function loadItemsData() {
    // OPTIMIZED: Don't load all items initially - wait for user search
    const container = document.getElementById('itemsTableContainer');
    if (container) {
        container.innerHTML = `
            <div style="padding: 3rem; text-align: center; color: var(--text-secondary);">
                <i class="fas fa-search" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                <p style="font-size: 1.1rem; margin-bottom: 0.5rem;">Search for items to get started</p>
                <p style="font-size: 0.875rem;">Type at least 2 characters in the search box above to find items</p>
            </div>
        `;
    }
    
    // Reset lists
    inventoryItemsList = [];
    inventoryFilteredItemsList = [];
}

// OPTIMIZED: Use API search instead of client-side filtering
async function filterItems() {
    const searchInput = document.getElementById('itemsSearchInput');
    if (!searchInput) return;
    
    const searchTerm = searchInput.value.trim();
    const container = document.getElementById('itemsTableContainer');
    if (!container) return;
    
    // Clear previous timeout
    if (inventorySearchTimeout) {
        clearTimeout(inventorySearchTimeout);
    }
    
    // If search is empty, show prompt
    if (searchTerm.length < 2) {
        inventoryFilteredItemsList = [];
        container.innerHTML = `
            <div style="padding: 3rem; text-align: center; color: var(--text-secondary);">
                <i class="fas fa-search" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                <p style="font-size: 1.1rem; margin-bottom: 0.5rem;">Search for items to get started</p>
                <p style="font-size: 0.875rem;">Type at least 2 characters in the search box above to find items</p>
            </div>
        `;
        return;
    }
    
    // Show loading state
    if (!isInventorySearching) {
        container.innerHTML = `
            <div style="padding: 2rem; text-align: center;">
                <div class="spinner" style="margin: 0 auto 1rem;"></div>
                <p style="color: var(--text-secondary);">Searching items...</p>
            </div>
        `;
    }
    
    // Debounce search (150ms for fast response)
    inventorySearchTimeout = setTimeout(async () => {
        isInventorySearching = true;
        
        try {
            // Use session branch so stock/last supplier match header (same as Items page)
            const branchId = getBranchIdForStock();
            const cache = window.searchCache || null;
            let searchResults = null;
            
            if (cache) {
                searchResults = cache.get(searchTerm, CONFIG.COMPANY_ID, branchId, 20);
                // If we have a branch but cached results have no stock, refetch (avoid stale cache)
                if (searchResults && branchId && searchResults.length > 0) {
                    const hasNoStock = searchResults.every(it => (it.current_stock == null && !(it.stock_display != null && it.stock_display !== '')));
                    if (hasNoStock) searchResults = null;
                }
            }
            
            if (!searchResults) {
                // Search with branch_id for stock; include_pricing=true for last_supplier and costs
                searchResults = await API.items.search(searchTerm, CONFIG.COMPANY_ID, 20, branchId || null, true);
                
                if (cache && searchResults) {
                    cache.set(searchTerm, CONFIG.COMPANY_ID, branchId, 20, searchResults);
                }
            }
            
            // Map API response to display via shared utility
            inventoryFilteredItemsList = searchResults.map(mapApiItemToDisplay);
            
            renderItemsTable();
        } catch (error) {
            console.error('Error searching items:', error);
            container.innerHTML = `
                <div style="padding: 2rem; text-align: center; color: var(--danger-color);">
                    <i class="fas fa-exclamation-circle" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                    <p>Error searching items: ${error.message || 'Search failed'}</p>
                </div>
            `;
        } finally {
            isInventorySearching = false;
        }
    }, 150);
}

function renderItemsTable() {
    const container = document.getElementById('itemsTableContainer');
    if (!container) return;
    
    // Use filtered list (from search)
    const displayList = inventoryFilteredItemsList;
    
    if (displayList.length === 0) {
        const searchInput = document.getElementById('itemsSearchInput');
        const hasSearch = searchInput && searchInput.value.trim().length >= 2;
        container.innerHTML = hasSearch 
            ? '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items found matching your search.</p>'
            : '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items found. Add your first item to get started.</p>';
        return;
    }
    
    container.innerHTML = `
        <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto;">
            <table style="width: 100%;">
                <thead style="position: sticky; top: 0; background: var(--bg-primary); z-index: 10; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <tr>
                        <th>Name</th>
                        <th>SKU</th>
                        <th>Base Unit</th>
                        <th>Category</th>
                        <th>Current Stock</th>
                        <th>Last Supplier</th>
                        <th>Last Unit Cost</th>
                        <th>Default Cost</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${displayList.map(item => {
                        const isLowStock = item.minimum_stock !== null && item.current_stock !== null && item.current_stock < item.minimum_stock;
                        const rowClass = isLowStock ? 'style="background-color: #fff3cd;"' : '';
                        const stockDisplay = typeof formatStockCell === 'function' ? formatStockCell(item) : '—';
                        return `
                        <tr ${rowClass}>
                            <td>${escapeHtml(item.name)}</td>
                            <td><code>${escapeHtml(item.sku || '—')}</code></td>
                            <td>${escapeHtml(item.base_unit)}</td>
                            <td>${escapeHtml(item.category || '—')}</td>
                            <td>${stockDisplay}</td>
                            <td>${escapeHtml(item.last_supplier || '—')}</td>
                            <td>${item.last_unit_cost !== null && item.last_unit_cost !== undefined ? formatCurrency(item.last_unit_cost) : '—'}</td>
                            <td>${formatCurrency(item.default_cost || 0)}</td>
                            <td>
                                <span class="badge ${item.is_active ? 'badge-success' : 'badge-danger'}">
                                    ${item.is_active ? 'Active' : 'Inactive'}
                                </span>
                            </td>
                            <td>
                                <button class="btn btn-primary" onclick="showAdjustStockModal('${item.id}')" title="Adjust stock: add/reduce, set batch, expiry, notes" style="min-width: 2.25rem;">
                                    <i class="fas fa-sliders-h"></i> <span style="margin-left: 0.25rem;">Adjust</span>
                                </button>
                                <button class="btn btn-outline" onclick="editItem('${item.id}')" title="Edit item">
                                    <i class="fas fa-edit"></i>
                                </button>
                                <button class="btn btn-outline" onclick="viewItemUnits('${item.id}')" title="View units">
                                    <i class="fas fa-cubes"></i>
                                </button>
                            </td>
                        </tr>
                    `;
                    }).join('')}
                </tbody>
            </table>
        </div>
        ${inventoryFilteredItemsList.length > 0 
            ? `<p style="padding: 1rem; color: var(--text-secondary);">Showing ${inventoryFilteredItemsList.length} search result${inventoryFilteredItemsList.length !== 1 ? 's' : ''}</p>`
            : ''}
    `;
}

// ============================================
// ADJUST STOCK MODAL
// ============================================
async function showAdjustStockModal(itemId) {
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Please select a branch first.', 'warning');
        else alert('Please select a branch first.');
        return;
    }
    if (!CONFIG.USER_ID) {
        if (typeof showToast === 'function') showToast('User session required to adjust stock.', 'warning');
        else alert('User session required to adjust stock.');
        return;
    }
    try {
        const branchIdNormalized = typeof branchId === 'string' ? branchId : (branchId && (branchId.id || branchId));
        const data = await API.items.get(itemId, branchIdNormalized);
        const itemName = (data && data.name) ? String(data.name) : 'Item';
        const units = (data && data.units && data.units.length) ? data.units : [{ unit_name: data.base_unit || 'piece', multiplier_to_base: 1 }];
        const lastCost = (data && (data.default_cost != null || data.default_cost_per_base != null)) ? (data.default_cost ?? data.default_cost_per_base) : 0;
        const unitOptions = units.map(u => `<option value="${escapeHtml(u.unit_name)}">${escapeHtml(u.unit_name)}</option>`).join('');

        const content = `
            <div style="margin-bottom: 1rem; padding: 0.75rem; background: var(--bg-secondary, #f5f5f5); border-radius: 6px;">
                <strong>${escapeHtml(itemName)}</strong>
            </div>
            <div class="form-group">
                <label>Unit (Box, Tablets, Pieces, etc.)</label>
                <select id="adjustStockUnit" class="form-input">
                    ${unitOptions}
                </select>
            </div>
            <div class="form-group">
                <label>Direction</label>
                <div style="display: flex; gap: 1rem;">
                    <label><input type="radio" name="adjustDirection" value="add" checked> Add stock</label>
                    <label><input type="radio" name="adjustDirection" value="reduce"> Reduce stock</label>
                </div>
            </div>
            <div class="form-group">
                <label>Quantity (in selected unit)</label>
                <input type="number" id="adjustStockQty" class="form-input" min="0.001" step="any" value="1" required>
            </div>
            <div class="form-group">
                <label>Unit cost (per base unit) — optional; defaults to last purchase cost</label>
                <input type="number" id="adjustStockCost" class="form-input" min="0" step="0.01" value="${lastCost}" placeholder="0 = use last price">
            </div>
            <div class="form-group">
                <label>Batch / Lot number</label>
                <input type="text" id="adjustStockBatch" class="form-input" maxlength="200" placeholder="e.g. BATCH-2024-001">
            </div>
            <div class="form-group">
                <label>Expiry date</label>
                <input type="date" id="adjustStockExpiry" class="form-input" value="" placeholder="YYYY-MM-DD">
            </div>
            <div class="form-group">
                <label>Comments / Details (source, reason — for tracking)</label>
                <textarea id="adjustStockNotes" class="form-input" rows="2" maxlength="2000" placeholder="e.g. Received from store X, stock take correction"></textarea>
            </div>
        `;
        const footer = `
            <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" id="adjustStockSubmitBtn"><i class="fas fa-check"></i> Apply adjustment</button>
        `;
        if (typeof showModal === 'function') {
            showModal('Adjust Item', content, footer);
        } else {
            document.getElementById('modalOverlay').style.display = 'flex';
            document.getElementById('modal').innerHTML = '<div class="modal-header"><h3>Adjust Item</h3><button class="modal-close" onclick="closeModal()"><i class="fas fa-times"></i></button></div><div class="modal-body">' + content + '</div><div class="modal-footer">' + footer + '</div>';
        }
        const submitBtn = document.getElementById('adjustStockSubmitBtn');
        if (submitBtn) {
            submitBtn.onclick = async () => submitAdjustStock(itemId);
        }
    } catch (err) {
        const msg = err.message || (err.data && err.data.detail) || 'Failed to load item';
        if (typeof showToast === 'function') showToast(msg, 'error');
        else alert(msg);
    }
}

async function submitAdjustStock(itemId) {
    const unitEl = document.getElementById('adjustStockUnit');
    const qtyEl = document.getElementById('adjustStockQty');
    const costEl = document.getElementById('adjustStockCost');
    const directionRadios = document.querySelectorAll('input[name="adjustDirection"]');
    if (!unitEl || !qtyEl || !directionRadios.length) return;
    const unit_name = unitEl.value;
    const quantity = parseFloat(qtyEl.value);
    const direction = Array.from(directionRadios).find(r => r.checked);
    const dir = direction ? direction.value : 'add';
    if (!quantity || quantity <= 0) {
        if (typeof showToast === 'function') showToast('Enter a valid quantity.', 'warning');
        else alert('Enter a valid quantity.');
        return;
    }
    const unit_cost = costEl ? parseFloat(costEl.value) : null;
    const batchEl = document.getElementById('adjustStockBatch');
    const expiryEl = document.getElementById('adjustStockExpiry');
    const notesEl = document.getElementById('adjustStockNotes');
    const branchId = getBranchIdForStock();
    const branchIdRaw = branchId != null ? (typeof branchId === 'string' ? branchId : (branchId && (branchId.id || branchId))) : null;
    const userIdRaw = CONFIG.USER_ID != null ? (typeof CONFIG.USER_ID === 'string' ? CONFIG.USER_ID : (CONFIG.USER_ID && (CONFIG.USER_ID.id || CONFIG.USER_ID))) : null;
    const payload = {
        branch_id: branchIdRaw,
        user_id: userIdRaw,
        unit_name: unit_name,
        quantity: quantity,
        direction: dir,
        unit_cost: (unit_cost != null && !isNaN(unit_cost) && unit_cost > 0) ? unit_cost : null,
        batch_number: batchEl && batchEl.value.trim() ? batchEl.value.trim() : null,
        expiry_date: expiryEl && expiryEl.value ? expiryEl.value : null,
        notes: notesEl && notesEl.value.trim() ? notesEl.value.trim() : null
    };
    const submitBtn = document.getElementById('adjustStockSubmitBtn');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Applying...';
    }
    try {
        await API.items.adjustStock(itemId, payload);
        if (typeof closeModal === 'function') closeModal();
        if (typeof showToast === 'function') showToast('Stock adjusted successfully.', 'success');
        else alert('Stock adjusted successfully.');
        if (typeof filterItems === 'function') filterItems();
    } catch (err) {
        const msg = (err.data && (err.data.detail || (Array.isArray(err.data.detail) ? err.data.detail[0] : null))) || err.message || 'Adjustment failed';
        if (typeof showToast === 'function') showToast(msg, 'error');
        else alert(msg);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Apply adjustment';
        }
    }
}

// ============================================
// OTHER SUB-PAGES (Placeholders)
// ============================================
function renderBatchTrackingSubPage() {
    return '<div><h2>Batch Tracking</h2><p>Batch tracking functionality coming soon...</p></div>';
}

function renderExpiryReportSubPage() {
    return '<div><h2>Expiry Report</h2><p>Expiry report functionality coming soon...</p></div>';
}

function renderItemMovementSubPage() {
    return '<div><h2>Item Movement</h2><p>Item movement functionality coming soon...</p></div>';
}

function renderCurrentStockSubPage() {
    return `
        <div>
            <h2 style="margin-bottom: 1rem;"><i class="fas fa-chart-bar"></i> Current Stock</h2>
            <p style="color: var(--text-secondary); margin-bottom: 1rem;">Stock on hand for the selected branch (session branch).</p>
            <div id="currentStockContainer">
                <div class="spinner" style="margin: 1rem auto;"></div>
                <p style="text-align: center; color: var(--text-secondary);">Loading...</p>
            </div>
        </div>
    `;
}

async function loadBatchTrackingData() {
    // TODO
}

async function loadExpiryReportData() {
    // TODO
}

async function loadItemMovementData() {
    // TODO
}

async function loadCurrentStockData() {
    const container = document.getElementById('currentStockContainer');
    if (!container) return;
    const branchId = getBranchIdForStock();
    if (!branchId) {
        container.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> Select a branch to see current stock.</div>';
        return;
    }
    try {
        const list = await API.inventory.getAllStock(branchId);
        if (!list || list.length === 0) {
            container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No stock on hand at this branch.</p>';
            return;
        }
        const rows = list.map(row => `
            <tr>
                <td>${escapeHtml(row.item_name || '—')}</td>
                <td>${formatNumber(row.stock)} ${escapeHtml(row.base_unit || '')}</td>
            </tr>
        `).join('');
        container.innerHTML = `
            <div class="table-container" style="max-height: 60vh; overflow-y: auto;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background: white; z-index: 1;">
                        <tr>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>
                            <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Quantity</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <p style="margin-top: 0.75rem; color: var(--text-secondary);">${list.length} item(s) with stock</p>
        `;
    } catch (err) {
        console.error('Current stock load failed:', err);
        container.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Failed to load current stock. ' + (err.message || '') + '</div>';
    }
}

// Helper functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num === null || num === undefined) return '—';
    return Number(num).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

// Export functions to window object IMMEDIATELY
// Using IIFE to ensure export happens as soon as script loads
(function() {
    'use strict';
    function exportFunctions() {
        try {
            if (typeof loadInventory === 'function') {
                window.loadInventory = loadInventory;
            }
            if (typeof switchInventorySubPage === 'function') {
                window.switchInventorySubPage = switchInventorySubPage;
            }
            if (typeof filterItems === 'function') {
                window.filterItems = filterItems;
            }
            if (typeof updateSubNavActiveState === 'function') {
                window.updateSubNavActiveState = updateSubNavActiveState;
            }
            // Export loadItemsData for use from items.js
            window.loadItemsData = loadItemsData;
            if (typeof showAdjustStockModal === 'function') window.showAdjustStockModal = showAdjustStockModal;
            if (typeof submitAdjustStock === 'function') window.submitAdjustStock = submitAdjustStock;
            
            console.log('✓ Inventory functions exported to window:', {
                loadInventory: typeof window.loadInventory,
                switchInventorySubPage: typeof window.switchInventorySubPage,
                filterItems: typeof window.filterItems,
                updateSubNavActiveState: typeof window.updateSubNavActiveState,
                loadItemsData: typeof window.loadItemsData
            });
        } catch (error) {
            console.error('✗ Error exporting inventory functions:', error);
        }
    }
    
    // Export immediately
    exportFunctions();
    
    // Also export on DOM ready (in case functions aren't hoisted yet)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', exportFunctions);
    } else {
        // DOM already loaded, export now
        setTimeout(exportFunctions, 0);
    }
})();
