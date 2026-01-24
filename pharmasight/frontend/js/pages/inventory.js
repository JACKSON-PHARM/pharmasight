// Inventory Management Page with Sidebar Navigation

let currentInventorySubPage = 'items'; // items, batch, expiry, movement, stock

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
            // OPTIMIZED: Check cache first
            const cache = window.searchCache || null;
            let searchResults = null;
            
            if (cache) {
                searchResults = cache.get(searchTerm, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, 20);
            }
            
            if (!searchResults) {
                // OPTIMIZED: Use search API (fast, no pricing needed for list view)
                // API max limit is 20, so use that for performance
                searchResults = await API.items.search(searchTerm, CONFIG.COMPANY_ID, 20, CONFIG.BRANCH_ID || null, false);
                
                // Cache the results
                if (cache && searchResults) {
                    cache.set(searchTerm, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, 20, searchResults);
                }
            }
            
            // Convert search results to display format
            inventoryFilteredItemsList = searchResults.map(item => ({
                id: item.id,
                name: item.name,
                sku: item.sku || '',
                base_unit: item.base_unit,
                category: item.category || '',
                current_stock: null, // Stock not included in search for performance
                last_supplier: item.last_supplier || '',
                last_unit_cost: item.purchase_price || null,
                default_cost: item.price || 0,
                is_active: item.is_active !== undefined ? item.is_active : true
            }));
            
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
                        return `
                        <tr ${rowClass}>
                            <td>${escapeHtml(item.name)}</td>
                            <td><code>${escapeHtml(item.sku || '—')}</code></td>
                            <td>${escapeHtml(item.base_unit)}</td>
                            <td>${escapeHtml(item.category || '—')}</td>
                            <td>
                                ${item.current_stock !== null && item.current_stock !== undefined 
                                    ? `<strong ${isLowStock ? 'style="color: #dc3545;"' : ''}>${formatNumber(item.current_stock)} ${item.base_unit}</strong>`
                                    : '—'}
                            </td>
                            <td>${escapeHtml(item.last_supplier || '—')}</td>
                            <td>${item.last_unit_cost !== null && item.last_unit_cost !== undefined ? formatCurrency(item.last_unit_cost) : '—'}</td>
                            <td>${formatCurrency(item.default_cost || 0)}</td>
                            <td>
                                <span class="badge ${item.is_active ? 'badge-success' : 'badge-danger'}">
                                    ${item.is_active ? 'Active' : 'Inactive'}
                                </span>
                            </td>
                            <td>
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
    return '<div><h2>Current Stock</h2><p>Current stock functionality coming soon...</p></div>';
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
    // TODO
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
