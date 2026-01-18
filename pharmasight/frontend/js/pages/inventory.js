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
                    placeholder="Search by name, SKU, or category..." 
                    oninput="filterItems()"
                    style="max-width: 400px;"
                >
            </div>
            
            <div id="itemsTableContainer">
                <div class="spinner"></div>
            </div>
        </div>
    `;
}

let inventoryItemsList = [];
let inventoryFilteredItemsList = [];

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
    try {
        inventoryItemsList = await API.items.overview(CONFIG.COMPANY_ID, CONFIG.BRANCH_ID);
        inventoryFilteredItemsList = [];
        renderItemsTable();
    } catch (error) {
        console.error('Error loading items:', error);
        showToast('Error loading items', 'error');
        const container = document.getElementById('itemsTableContainer');
        if (container) {
            container.innerHTML = '<p>Error loading items. Please try again.</p>';
        }
    }
}

function filterItems() {
    const searchTerm = document.getElementById('itemsSearchInput')?.value.toLowerCase() || '';
    if (!searchTerm) {
        inventoryFilteredItemsList = [];
    } else {
        inventoryFilteredItemsList = inventoryItemsList.filter(item => 
            (item.name || '').toLowerCase().includes(searchTerm) ||
            (item.sku || '').toLowerCase().includes(searchTerm) ||
            (item.category || '').toLowerCase().includes(searchTerm)
        );
    }
    renderItemsTable();
}

function renderItemsTable() {
    const container = document.getElementById('itemsTableContainer');
    if (!container) return;
    
    const displayList = inventoryFilteredItemsList.length > 0 || document.getElementById('itemsSearchInput')?.value ? inventoryFilteredItemsList : inventoryItemsList;
    
    if (displayList.length === 0) {
        container.innerHTML = '<p>No items found. Add your first item to get started.</p>';
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
        ${inventoryFilteredItemsList.length > 0 && inventoryFilteredItemsList.length < inventoryItemsList.length 
            ? `<p style="padding: 1rem; color: var(--text-secondary);">Showing ${inventoryFilteredItemsList.length} of ${inventoryItemsList.length} items</p>`
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
            console.log('✓ Inventory functions exported to window:', {
                loadInventory: typeof window.loadInventory,
                switchInventorySubPage: typeof window.switchInventorySubPage,
                filterItems: typeof window.filterItems,
                updateSubNavActiveState: typeof window.updateSubNavActiveState
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
