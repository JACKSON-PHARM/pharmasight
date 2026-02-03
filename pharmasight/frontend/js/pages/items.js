// Items Management Page

let itemsList = [];
let filteredItemsList = [];
let itemsSearchTimeout = null;
let isSearching = false;

async function loadItems() {
    const page = document.getElementById('items');
    
    // Check if page element exists (might not exist if on inventory page)
    if (!page) {
        console.log('Items page element not found, skipping loadItems()');
        return;
    }
    
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
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-box"></i> Inventory Items</h3>
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
            <div style="padding: 1rem; border-bottom: 1px solid var(--border-color); display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
                <div class="form-group" style="margin: 0; flex: 1; min-width: 300px;">
                    <input 
                        type="text" 
                        id="itemsSearchInput" 
                        class="form-input" 
                        placeholder="Search by name, SKU, or category... (Type to search)" 
                        oninput="filterItems()"
                        style="width: 100%;"
                    >
                    <small style="color: var(--text-secondary); font-size: 0.875rem; display: block; margin-top: 0.25rem;">
                        <i class="fas fa-info-circle"></i> Search is optimized for 20,000+ items. Type at least 2 characters.
                    </small>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="loadAllItems()" id="loadAllItemsBtn" title="Load all items for management">
                        <i class="fas fa-list"></i> Load All Items
                    </button>
                    <button class="btn btn-outline" onclick="clearItemsView()" id="clearItemsViewBtn" style="display: none;" title="Clear view">
                        <i class="fas fa-times"></i> Clear
                    </button>
                </div>
            </div>
            <div id="itemsTableContainer">
                <div class="spinner"></div>
            </div>
        </div>
    `;
    
    // Show initial prompt
    showItemsPrompt();
    
    // Reset lists
    itemsList = [];
    filteredItemsList = [];
}

function showItemsPrompt() {
    const container = document.getElementById('itemsTableContainer');
    if (!container) return;
    
    container.innerHTML = `
        <div style="padding: 3rem; text-align: center; color: var(--text-secondary);">
            <i class="fas fa-boxes" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
            <p style="font-size: 1.1rem; margin-bottom: 0.5rem; font-weight: 500;">Items Management</p>
            <p style="font-size: 0.875rem; margin-bottom: 1.5rem;">Use search to find specific items, or click "Load All Items" to browse</p>
            <div style="display: flex; gap: 1rem; justify-content: center;">
                <button class="btn btn-outline" onclick="loadAllItems()">
                    <i class="fas fa-list"></i> Load All Items
                </button>
            </div>
        </div>
    `;
}

// Load all items for management (with pagination/limits for performance)
async function loadAllItems() {
    const container = document.getElementById('itemsTableContainer');
    const loadBtn = document.getElementById('loadAllItemsBtn');
    const clearBtn = document.getElementById('clearItemsViewBtn');
    
    if (!container) return;
    
    // Show loading state
    if (loadBtn) {
        loadBtn.disabled = true;
        loadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
    }
    
    container.innerHTML = `
        <div style="padding: 2rem; text-align: center;">
            <div class="spinner" style="margin: 0 auto 1rem;"></div>
            <p style="color: var(--text-secondary);">Loading items for management...</p>
        </div>
    `;
    
    try {
        // Validate company ID
        if (!CONFIG.COMPANY_ID) {
            throw new Error('Company ID not configured. Please set up your company in Settings.');
        }
        
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        if (!uuidRegex.test(CONFIG.COMPANY_ID)) {
            throw new Error(`Invalid Company ID format: ${CONFIG.COMPANY_ID}. Please check your settings.`);
        }
        
        // OPTIMIZED: Load items with overview data (includes stock, supplier, etc.)
        // This is for management, so we need full data
        // For 20k+ items, we'll load first 500, user can search for more
        itemsList = await API.items.overview(CONFIG.COMPANY_ID, CONFIG.BRANCH_ID);
        
        // If we have many items, limit display to first 500 for performance
        // User can still search for specific items
        if (itemsList.length > 500) {
            itemsList = itemsList.slice(0, 500);
            showToast(`Loaded first 500 items. Use search to find specific items.`, 'info');
        }
        
        filteredItemsList = [];
        renderItemsTable();
        
        // Show clear button
        if (clearBtn) clearBtn.style.display = 'block';
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.innerHTML = '<i class="fas fa-list"></i> Load All Items';
        }
    } catch (error) {
        console.error('Error loading items:', error);
        showToast('Error loading items: ' + (error.message || 'Failed to load'), 'error');
        container.innerHTML = `
            <div style="padding: 2rem; text-align: center; color: var(--danger-color);">
                <i class="fas fa-exclamation-circle" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                <p>Error loading items: ${error.message || 'Failed to load'}</p>
                <button class="btn btn-primary" onclick="loadAllItems()" style="margin-top: 1rem;">
                    <i class="fas fa-redo"></i> Retry
                </button>
            </div>
        `;
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.innerHTML = '<i class="fas fa-list"></i> Load All Items';
        }
    }
}

function clearItemsView() {
    itemsList = [];
    filteredItemsList = [];
    const searchInput = document.getElementById('itemsSearchInput');
    if (searchInput) searchInput.value = '';
    const clearBtn = document.getElementById('clearItemsViewBtn');
    if (clearBtn) clearBtn.style.display = 'none';
    showItemsPrompt();
}

// OPTIMIZED: Use API search instead of client-side filtering
async function filterItems() {
    const searchInput = document.getElementById('itemsSearchInput');
    if (!searchInput) return;
    
    const searchTerm = searchInput.value.trim();
    const container = document.getElementById('itemsTableContainer');
    if (!container) return;
    
    // Clear previous timeout
    if (itemsSearchTimeout) {
        clearTimeout(itemsSearchTimeout);
    }
    
    // If search is empty, show prompt
    if (searchTerm.length < 2) {
        filteredItemsList = [];
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
    if (!isSearching) {
        container.innerHTML = `
            <div style="padding: 2rem; text-align: center;">
                <div class="spinner" style="margin: 0 auto 1rem;"></div>
                <p style="color: var(--text-secondary);">Searching items...</p>
            </div>
        `;
    }
    
    // Debounce search (150ms for fast response)
    itemsSearchTimeout = setTimeout(async () => {
        isSearching = true;
        
        try {
            // OPTIMIZED: Check cache first
            const cache = window.searchCache || null;
            let searchResults = null;
            
            if (cache) {
                searchResults = cache.get(searchTerm, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, 20);
            }
            
            if (!searchResults) {
                // OPTIMIZED: Use search API (fast, no pricing needed for list view)
                // Ensure company_id is a valid UUID string
                if (!CONFIG.COMPANY_ID) {
                    throw new Error('Company ID not configured. Please set up your company in Settings.');
                }
                
                // Validate UUID format (basic check)
                const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
                if (!uuidRegex.test(CONFIG.COMPANY_ID)) {
                    throw new Error(`Invalid Company ID format: ${CONFIG.COMPANY_ID}. Please check your settings.`);
                }
                
                try {
                    // Search API has max limit of 20, use that for performance
                    searchResults = await API.items.search(searchTerm, CONFIG.COMPANY_ID, 20, CONFIG.BRANCH_ID || null, false);
                } catch (apiError) {
                    console.error('Search API error:', apiError);
                    // Check if it's a 422 validation error
                    if (apiError.status === 422 || apiError.data?.detail) {
                        const detail = apiError.data?.detail || 'Validation error';
                        let errorMsg = 'Search validation error';
                        if (Array.isArray(detail)) {
                            errorMsg = detail.map(d => d.msg || d.message || JSON.stringify(d)).join(', ');
                        } else if (typeof detail === 'string') {
                            errorMsg = detail;
                        } else if (detail.message) {
                            errorMsg = detail.message;
                        }
                        throw new Error(errorMsg);
                    }
                    throw apiError;
                }
                
                // Cache the results
                if (cache && searchResults) {
                    cache.set(searchTerm, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, 20, searchResults);
                }
            }
            
            // Convert search results to display format
            // Note: Search results don't have stock info, so we'll show basic info
            // For full overview with stock, user can click on item
            filteredItemsList = searchResults.map(item => ({
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
            isSearching = false;
        }
    }, 150);
}

function renderItemsTable() {
    const container = document.getElementById('itemsTableContainer');
    if (!container) return;
    
    // Use filtered list if search is active, otherwise use full list
    const searchInput = document.getElementById('itemsSearchInput');
    const hasActiveSearch = searchInput && searchInput.value.trim().length >= 2;
    const displayList = hasActiveSearch ? filteredItemsList : itemsList;
    
    if (displayList.length === 0) {
        if (hasActiveSearch) {
            container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items found matching your search.</p>';
        } else if (itemsList.length === 0) {
            showItemsPrompt();
        } else {
            container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items to display.</p>';
        }
        return;
    }
    
    container.innerHTML = `
        <div class="table-container" style="max-height: calc(100vh - 300px); overflow-y: auto; position: relative;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <tr>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Name</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">SKU</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Base Unit (Wholesale)</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Category</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Current Stock</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Supplier Price</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Wholesale Price</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Retail Price</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Last Supplier</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Last Unit Cost</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${displayList.map(item => {
                        const isLowStock = item.minimum_stock !== null && item.current_stock !== null && item.current_stock < item.minimum_stock;
                        const rowClass = isLowStock ? 'style="background-color: #fff3cd;"' : '';
                        
                        // Extract 3-tier pricing
                        const pricing3tier = item.pricing_3tier || {};
                        const supplierPrice = pricing3tier.supplier_price;
                        const wholesalePrice = pricing3tier.wholesale_price;
                        const retailPrice = pricing3tier.retail_price;
                        
                        // Format stock display (packets + individual units)
                        let stockDisplay = '—';
                        if (item.stock_availability && item.stock_availability.unit_breakdown && item.stock_availability.unit_breakdown.length > 0) {
                            // Use unit breakdown for better display (e.g., "8 boxes + 40 tablets")
                            const display = item.stock_availability.unit_breakdown[0].display;
                            stockDisplay = `<strong ${isLowStock ? 'style="color: #dc3545;"' : ''}>${display}</strong>`;
                        } else if (item.current_stock !== null && item.current_stock !== undefined) {
                            // Fallback to simple number display
                            stockDisplay = `<strong ${isLowStock ? 'style="color: #dc3545;"' : ''}>${formatNumber(item.current_stock)} ${item.base_unit}</strong>`;
                        }
                        
                        return `
                        <tr ${rowClass}>
                            <td>${escapeHtml(item.name)}</td>
                            <td><code>${escapeHtml(item.sku || '—')}</code></td>
                            <td>${escapeHtml(item.base_unit)}</td>
                            <td>${escapeHtml(item.category || '—')}</td>
                            <td>${stockDisplay}</td>
                            <td>
                                ${supplierPrice 
                                    ? `<strong>${formatCurrency(supplierPrice.price)}</strong><br><small style="color: var(--text-secondary);">per ${supplierPrice.unit}</small>`
                                    : '—'}
                            </td>
                            <td>
                                ${wholesalePrice 
                                    ? `<strong>${formatCurrency(wholesalePrice.price)}</strong><br><small style="color: var(--text-secondary);">per ${wholesalePrice.unit}</small>`
                                    : '—'}
                            </td>
                            <td>
                                ${retailPrice 
                                    ? `<strong style="color: #28a745;">${formatCurrency(retailPrice.price)}</strong><br><small style="color: var(--text-secondary);">per ${retailPrice.unit}</small>`
                                    : '—'}
                            </td>
                            <td>${escapeHtml(item.last_supplier || '—')}</td>
                            <td>${item.last_unit_cost !== null && item.last_unit_cost !== undefined ? formatCurrency(item.last_unit_cost) : '—'}</td>
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
        ${hasActiveSearch && filteredItemsList.length > 0
            ? `<p style="padding: 1rem; color: var(--text-secondary);">Showing ${filteredItemsList.length} search result${filteredItemsList.length !== 1 ? 's' : ''}</p>`
            : itemsList.length > 0 && !hasActiveSearch
            ? `<p style="padding: 1rem; color: var(--text-secondary);">Showing ${itemsList.length} item${itemsList.length !== 1 ? 's' : ''}${itemsList.length >= 500 ? ' (first 500 - use search for more)' : ''}</p>`
            : ''}
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num === null || num === undefined) return '—';
    return Number(num).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function showAddItemModal() {
    const content = `
        <form id="itemForm" onsubmit="saveItem(event)" style="max-height: 70vh; overflow-y: auto;">
            <!-- Item Details Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-info-circle"></i> Item Details
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Item Code</label>
                        <input type="text" class="form-input" name="sku" placeholder="Auto-generated or manual">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Barcode</label>
                        <input type="text" class="form-input" name="barcode" placeholder="Scan or enter barcode">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Item Name *</label>
                    <input type="text" class="form-input" name="name" required placeholder="Enter item name">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Generic Name</label>
                        <input type="text" class="form-input" name="description" placeholder="Enter generic name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Category/SubGroup</label>
                        <input type="text" class="form-input" name="category" placeholder="Enter category">
                    </div>
                </div>
            </div>

            <!-- Item Nature & Type Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-tag"></i> Item Classification
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Item Nature *</label>
                        <div style="display: flex; gap: 2rem; margin-top: 0.5rem;">
                            <label class="checkbox-item">
                                <input type="radio" name="item_nature" value="physical" checked>
                                <span>Physical Item</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="radio" name="item_nature" value="service">
                                <span>Service Item</span>
                            </label>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Type *</label>
                        <div style="display: flex; gap: 2rem; margin-top: 0.5rem;">
                            <label class="checkbox-item">
                                <input type="radio" name="item_type" value="branded">
                                <span>Branded</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="radio" name="item_type" value="generic" checked>
                                <span>Generic</span>
                            </label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 3-Tier Unit System -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-layer-group"></i> 3-Tier Unit System
                </div>
                <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 1rem;">
                    Supplier buys in <strong>packets</strong> → Pharmacy buys in <strong>packets</strong> → Customer buys in <strong>tablets</strong>. Stock displayed as &quot;5 packets + 25 tablets&quot;.
                </p>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Supplier Unit (what you buy) *</label>
                        <select class="form-select" name="supplier_unit" required>
                            <option value="packet" selected>Packet</option>
                            <option value="box">Box</option>
                            <option value="bottle">Bottle</option>
                            <option value="tube">Tube</option>
                            <option value="piece">Piece</option>
                            <option value="carton">Carton</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Wholesale Unit (what pharmacies buy) *</label>
                        <select class="form-select" name="wholesale_unit" required>
                            <option value="packet" selected>Packet</option>
                            <option value="box">Box</option>
                            <option value="bottle">Bottle</option>
                            <option value="piece">Piece</option>
                            <option value="carton">Carton</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Retail Unit (what customers buy) *</label>
                        <select class="form-select" name="retail_unit" required>
                            <option value="tablet" selected>Tablet</option>
                            <option value="capsule">Capsule</option>
                            <option value="ml">ML</option>
                            <option value="gram">Gram</option>
                            <option value="piece">Piece</option>
                            <option value="sachet">Sachet</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Pack Size (retail per wholesale) *</label>
                        <input type="number" class="form-input" name="pack_size" min="1" value="30" required placeholder="e.g. 30">
                        <small style="color: var(--text-secondary); font-size: 0.85rem;">1 wholesale = N retail (e.g. 30 tablets per box)</small>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Wholesale per supplier</label>
                        <input type="number" class="form-input" name="wholesale_units_per_supplier" min="0.0001" step="0.01" value="1" placeholder="e.g. 10">
                        <small style="color: var(--text-secondary); font-size: 0.85rem;">1 supplier = N wholesale (e.g. 10 boxes per carton). Default 1.</small>
                    </div>
                    <div class="form-group" style="display: flex; align-items: flex-end; padding-bottom: 0.5rem;">
                        <label class="checkbox-item">
                            <input type="checkbox" name="can_break_bulk" id="can_break_bulk" checked>
                            <span>Can break bulk (sell individual units)</span>
                        </label>
                    </div>
                </div>
            </div>

            <!-- Item Specifications Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-flask"></i> Specifications
                </div>
                <div class="form-group">
                    <label class="form-label">Ingredients/Composition</label>
                    <textarea class="form-textarea" name="ingredients" rows="2" placeholder="Enter active ingredients and composition"></textarea>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Strength</label>
                        <input type="text" class="form-input" name="strength" placeholder="Enter strength">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Base Unit (= wholesale unit)</label>
                        <select class="form-select" name="base_unit">
                            <option value="tablet">Tablet</option>
                            <option value="capsule">Capsule</option>
                            <option value="ml">ML (Milliliter)</option>
                            <option value="gram">Gram</option>
                            <option value="piece">Piece</option>
                            <option value="bottle">Bottle</option>
                            <option value="tube">Tube</option>
                            <option value="sachet">Sachet</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Standard Pack</label>
                        <input type="text" class="form-input" name="std_pack" placeholder="Standard packaging unit">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Main Formulation</label>
                        <select class="form-select" name="formulation">
                            <option value="">Select Formulation</option>
                            <option value="tablet">Tablet</option>
                            <option value="capsule">Capsule</option>
                            <option value="syrup">Syrup</option>
                            <option value="injection">Injection</option>
                            <option value="cream">Cream</option>
                            <option value="ointment">Ointment</option>
                            <option value="drops">Drops</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Weight (Kgs)</label>
                        <input type="number" class="form-input" name="weight" step="0.001" min="0" placeholder="0.000">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Manufacturer</label>
                        <input type="text" class="form-input" name="manufacturer" placeholder="Manufacturer name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Production Class</label>
                        <select class="form-select" name="production_class">
                            <option value="normal" selected>Normal</option>
                            <option value="controlled">Controlled</option>
                            <option value="scheduled">Scheduled</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Registration Number</label>
                        <input type="text" class="form-input" name="registration_no" placeholder="PPB Registration No">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Class Code</label>
                        <input type="text" class="form-input" name="class_code" placeholder="Product class code">
                    </div>
                </div>
            </div>

            <!-- Pricing: DEPRECATED — cost/price from inventory_ledger only (Excel import or purchases). Do not send price fields. -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-info-circle"></i> Cost &amp; pricing
                </div>
                <p style="color: var(--text-secondary); font-size: 0.9rem;">
                    Cost and prices are set from <strong>inventory ledger</strong> (Excel import opening balance or purchase transactions). This form does not accept price fields.
                </p>
            </div>

            <!-- VAT/Tax Classification -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-receipt"></i> VAT Classification
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">VAT Category *</label>
                        <select class="form-select" name="vat_category" id="vat_category_select" required>
                            <option value="ZERO_RATED" selected>Zero Rated (0%) – Medicines</option>
                            <option value="STANDARD_RATED">Standard Rated (16%) – Non-medical</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">VAT Rate (%)</label>
                        <input type="number" class="form-input" name="vat_rate" id="vat_rate_input" step="0.01" min="0" max="100" value="0" placeholder="0.00">
                        <small style="color: var(--text-secondary); font-size: 0.85rem;">0% zero-rated, 16% standard-rated</small>
                    </div>
                </div>
            </div>

            <!-- Regulatory Information Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-certificate"></i> Regulatory Information
                </div>
                <div class="form-group">
                    <label class="form-label">Authorized Marketer</label>
                    <input type="text" class="form-input" name="authorized_marketer" placeholder="Enter authorized marketer/distributor name">
                    <small style="color: var(--text-secondary); font-size: 0.85rem;">Name of authorized marketer or distributor for this item</small>
                </div>
            </div>

            <!-- Unit Conversions (Breaking Bulk) Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-cubes"></i> Unit Conversions (Breaking Bulk)
                </div>
                <div id="unitsContainer">
                    <div class="form-row" id="unitRow0">
                        <div class="form-group">
                            <label class="form-label">Unit Name</label>
                            <input type="text" class="form-input" name="unit_name_0" placeholder="Enter unit name" value="tablet">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Multiplier to Base</label>
                            <input type="number" class="form-input" name="multiplier_0" placeholder="Enter multiplier" step="0.01" min="0.01" value="1">
                        </div>
                        <div class="form-group" style="display: flex; align-items: flex-end;">
                            <label class="checkbox-item">
                                <input type="checkbox" name="is_default_0" checked>
                                <span>Default</span>
                            </label>
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-outline" onclick="addUnitRow()">
                    <i class="fas fa-plus"></i> Add Unit Conversion
                </button>
            </div>

            <!-- Item Attributes Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-check-square"></i> Item Attributes
                </div>
                <div class="checkbox-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="has_refill" value="1">
                        <span>Has Refill</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="not_for_sale" value="1">
                        <span>Not For Sale</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="high_value" value="1">
                        <span>High Value</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="fast_moving" value="1">
                        <span>Fast Moving</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="controlled" value="1">
                        <span>Controlled Substance</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="track_expiry" value="1" checked>
                        <span>Track Expiry Dates</span>
                    </label>
                </div>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="itemForm">
            <i class="fas fa-save"></i> Save Item
        </button>
    `;
    
    showModal('New Inventory Item', content, footer);
    unitRowCount = 1; // Reset counter
    
    // Auto-update VAT rate when VAT category changes
    setTimeout(() => {
        const vatCat = document.querySelector('#itemForm select[name="vat_category"]');
        const vatRate = document.querySelector('#itemForm input[name="vat_rate"]');
        if (vatCat && vatRate) {
            vatCat.addEventListener('change', (e) => {
                vatRate.value = e.target.value === 'STANDARD_RATED' ? '16.00' : '0.00';
            });
        }
    }, 100);
}

let unitRowCount = 1;

function addUnitRow() {
    const container = document.getElementById('unitsContainer');
    const row = document.createElement('div');
    row.className = 'form-row';
    row.id = `unitRow${unitRowCount}`;
    row.innerHTML = `
        <div class="form-group">
            <input type="text" class="form-input" name="unit_name_${unitRowCount}" placeholder="Enter unit name">
        </div>
        <div class="form-group">
            <input type="number" class="form-input" name="multiplier_${unitRowCount}" placeholder="Multiplier" step="0.01" min="0.01">
        </div>
        <div class="form-group">
            <input type="checkbox" name="is_default_${unitRowCount}"> Default
            <button type="button" class="btn btn-danger" onclick="removeUnitRow(${unitRowCount})">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `;
    container.appendChild(row);
    unitRowCount++;
}

function removeUnitRow(index) {
    const row = document.getElementById(`unitRow${index}`);
    if (row) row.remove();
}

async function saveItem(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const packSize = parseInt(formData.get('pack_size') || '1', 10) || 1;
    const canBreakBulk = formData.get('can_break_bulk') === 'on';

    // Build item data — do NOT send deprecated price fields (cost from inventory_ledger only)
    const itemData = {
        company_id: CONFIG.COMPANY_ID,
        name: formData.get('name'),
        description: formData.get('description') || null,
        sku: formData.get('sku') || null,
        barcode: formData.get('barcode') || null,
        category: formData.get('category') || null,
        base_unit: formData.get('base_unit') || formData.get('wholesale_unit') || 'piece',
        supplier_unit: formData.get('supplier_unit') || 'packet',
        wholesale_unit: formData.get('wholesale_unit') || 'packet',
        retail_unit: formData.get('retail_unit') || 'tablet',
        pack_size: packSize,
        wholesale_units_per_supplier: Math.max(0.0001, parseFloat(formData.get('wholesale_units_per_supplier') || 1)),
        can_break_bulk: canBreakBulk,
        vat_category: formData.get('vat_category') || 'ZERO_RATED',
        vat_category: formData.get('vat_category') || 'ZERO_RATED',
        vat_rate: parseFloat(formData.get('vat_rate') || 0),
        units: []
    };

    if (itemData.vat_category === 'STANDARD_RATED') itemData.vat_rate = 16;
    else if (itemData.vat_category === 'ZERO_RATED') itemData.vat_rate = 0;

    // Optional unit rows (breaking bulk); when empty, backend derives from 3-tier
    let index = 0;
    while (formData.get(`unit_name_${index}`)) {
        const unitName = formData.get(`unit_name_${index}`);
        const multiplier = parseFloat(formData.get(`multiplier_${index}`));
        const isDefault = formData.get(`is_default_${index}`) === 'on';
        if (unitName && multiplier) {
            itemData.units.push({
                unit_name: unitName,
                multiplier_to_base: multiplier,
                is_default: isDefault
            });
        }
        index++;
    }
    const hasBaseUnit = itemData.units.some(u => u.unit_name === itemData.base_unit);
    if (itemData.units.length && !hasBaseUnit) {
        itemData.units.push({
            unit_name: itemData.base_unit,
            multiplier_to_base: 1.0,
            is_default: true
        });
    }
    
    try {
        // Show loading state
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn?.innerHTML;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        }
        
        const createdItem = await API.items.create(itemData);
        showToast('Item created successfully!', 'success');
        closeModal();
        
        // Check if this was called from a transaction document
        if (window._transactionItemCreateCallback) {
            // Format item for TransactionItemsTable
            const formattedItem = {
                id: createdItem.id,
                name: createdItem.name,
                sku: createdItem.sku || '',
                code: createdItem.sku || '',
                base_unit: createdItem.base_unit,
                sale_price: 0,
                purchase_price: 0, // Cost from inventory_ledger when item is used in transactions
                vat_rate: createdItem.vat_rate || 0,
                current_stock: 0
            };
            // Call the callback to select the item in the transaction table
            window._transactionItemCreateCallback(formattedItem);
            // Clean up
            window._transactionItemCreateCallback = null;
            window._transactionItemCreateRowIndex = null;
            window._transactionItemCreateName = null;
        } else {
            // Normal flow - reload items list
            setTimeout(() => {
                if (window.loadItems) window.loadItems();
                if (window.loadInventory) window.loadInventory();
            }, 100);
        }
    } catch (error) {
        console.error('Error saving item:', error);
        showToast(error.message || 'Error creating item', 'error');
        
        // Re-enable button on error
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Save Item';
        }
    }
}

function downloadItemTemplate() {
    if (typeof XLSX === 'undefined') {
        showToast('Excel library not loaded. Please refresh the page.', 'error');
        return;
    }
    
    // 3-tier unit template: base = wholesale, conversion to retail (pack_size), conversion to supplier (wholesale_units_per_supplier)
    const headers = [
        'Item name*',
        'Generic Name',
        'Item code',
        'Barcode',
        'Category',
        'Supplier Unit',
        'Wholesale Unit',
        'Retail Unit',
        'Pack Size (retail per wholesale)',
        'Wholesale Units per Supplier',
        'Purchase Price per Supplier Unit',
        'Wholesale Price per Wholesale Unit',
        'Retail Price per Retail Unit',
        'Current stock quantity',
        'Supplier',
        'VAT Category',
        'VAT Rate',
        'Can Break Bulk'
    ];
    
    // Create workbook and worksheet
    const wb = XLSX.utils.book_new();
    const ws = XLSX.utils.aoa_to_sheet([headers]);
    
    // Set column widths for better readability
    const colWidths = headers.map((header, idx) => {
        // Calculate width based on header length, with minimums
        const baseWidth = Math.max(header.length + 2, 12);
        return { wch: Math.min(baseWidth, 40) };
    });
    ws['!cols'] = colWidths;
    
    // Add worksheet to workbook with exact sheet name
    XLSX.utils.book_append_sheet(wb, ws, 'Pharmasight Template');
    
    // Generate file and download (matching original filename)
    const fileName = `pharmasight_template.xlsx`;
    XLSX.writeFile(wb, fileName);
    
    showToast('Template downloaded! Fill it with your items and upload.', 'success');
}

/** Clear company data for fresh Excel import. Only allowed when no live transactions (no sales/purchases). */
async function clearForReimport() {
    const btn = document.getElementById('clearForReimportBtn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
    }
    try {
        const modeInfo = await API.excel.getMode(CONFIG.COMPANY_ID);
        if (modeInfo.has_live_transactions) {
            showToast(
                'Cannot clear: company has live transactions (sales, purchases, or stock movements). Clear is only allowed when there are no transactions yet.',
                'error'
            );
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-broom"></i> Clear for re-import';
            }
            return;
        }
        const ok = confirm(
            'This will permanently delete all items, inventory, sales, purchases, and related data for this company. ' +
            'You can then run a fresh Excel import. Companies, branches, and users will NOT be deleted.\n\nContinue?'
        );
        if (!ok) {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-broom"></i> Clear for re-import';
            }
            return;
        }
        if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Clearing...';
        const result = await API.excel.clearForReimport(CONFIG.COMPANY_ID);
        showToast(result.message || 'Company data cleared. You can now run a fresh Excel import.', 'success');
        loadItems();
    } catch (err) {
        const msg = (err.data && (err.data.detail || err.data.message)) || err.message || 'Clear failed';
        showToast(typeof msg === 'string' ? msg : (msg.detail || msg.message || 'Clear failed'), 'error');
    } finally {
        const btn = document.getElementById('clearForReimportBtn');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-broom"></i> Clear for re-import';
        }
    }
}

function showImportExcelModal() {
    const content = `
        <div>
            <div class="alert alert-info">
                <i class="fas fa-info-circle"></i>
                <p><strong>Excel Import (Vyper-style column mapping):</strong></p>
                <ol style="margin-top: 0.5rem; padding-left: 1.5rem;">
                    <li>Select your Excel file below</li>
                    <li>For each PharmaSight field, choose which column from your Excel sheet contains that data</li>
                    <li><strong>Required:</strong> At least "Item Name" must be mapped</li>
                    <li>Click Import when ready</li>
                </ol>
            </div>
            <div class="form-group">
                <label class="form-label">Select Excel File (.xlsx or .xls)</label>
                <input type="file" id="excelFileInput" class="form-input" accept=".xlsx,.xls" onchange="handleFileSelect(event)">
            </div>
            <div id="excelPreview" style="display: none; margin-top: 1rem;">
                <h4>Preview (first 5 rows):</h4>
                <div id="excelPreviewContent" class="table-container" style="max-height: 300px; overflow-y: auto;"></div>
                <p style="margin-top: 0.5rem; color: var(--text-secondary);">
                    <span id="excelRowCount">0</span> rows found.
                </p>
            </div>
            <div id="excelColumnMappingSection" style="display: none; margin-top: 1rem;">
                <p id="importTargetLine" style="font-size: 0.875rem; margin-bottom: 0.5rem; padding: 0.35rem 0.5rem; background: var(--bg-secondary); border-radius: 4px;"><i class="fas fa-database"></i> <strong>Import target:</strong> <span id="importTargetValue">—</span></p>
                <label style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; font-size: 0.875rem; cursor: pointer;">
                    <input type="checkbox" id="excelImportSyncCheckbox" checked>
                    <span>Run import synchronously (recommended: see errors immediately; may take several minutes for large files)</span>
                </label>
                <h4><i class="fas fa-columns"></i> Map PharmaSight fields to your Excel columns</h4>
                <p style="font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 0.5rem;">For each PharmaSight field, choose which column from your Excel sheet contains that data. <strong id="excelColumnCount">0</strong> columns available from your sheet.</p>
                <p style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 0.5rem;"><i class="fas fa-info-circle"></i> For <strong>opening balance</strong>: choose your columns for <strong>Current Stock Quantity</strong>, <strong>Wholesale Unit Price</strong> (or Purchase Price per Supplier Unit), and <strong>Supplier</strong>.</p>
                <div id="excelColumnMapping" style="max-height: 420px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 4px;"></div>
            </div>
            <div id="excelError" class="alert alert-danger" style="display: none; margin-top: 1rem;"></div>
        </div>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" id="importExcelBtn" onclick="importExcelFile()" disabled>
            <i class="fas fa-upload"></i> Import Items
        </button>
    `;
    
    showModal('Import Items from Excel', content, footer);
    
    // Reset file input
    setTimeout(() => {
        const fileInput = document.getElementById('excelFileInput');
        if (fileInput) fileInput.value = '';
        window.excelFile = null;
    }, 100);
}

let excelFile = null; // Store the actual file object
let excelImportHeaders = []; // Excel column headers for building column_mapping

// Normalize string for fuzzy match (lowercase, collapse spaces/underscores)
function normalizeForMatch(s) {
    return (s || '').toLowerCase().replace(/[\s_\-*]+/g, ' ').trim();
}

// Suggest system field id for an Excel header (fuzzy match on label).
// Order matters: specific matches (VAT Category, Supplier name, etc.) before generic (category, description).
function suggestFieldForHeader(header, expectedFields) {
    const n = normalizeForMatch(header);
    if (!n) return '';
    // —— Explicit matches first (per discussion: VAT Category, VAT Rate, Supplier, etc.) ——
    if (n.includes('vat') && n.includes('category')) return 'vat_category';
    if (n.includes('vat') && n.includes('rate')) return 'vat_rate';
    // "Supplier" as name only (not Supplier_Unit, Supplier_Item_Code, etc.)
    if (n === 'supplier' || (n.includes('supplier') && !n.includes('unit') && !n.includes('item') && !n.includes('code') && !n.includes('last') && !n.includes('cost'))) return 'supplier';
    // Item name / description / category (description must not be "vat description")
    if (n.includes('item') && n.includes('name')) return 'item_name';
    if ((n.includes('description') || n.includes('generic')) && !n.includes('vat')) return 'description';
    if (n === 'category' || (n.includes('category') && !n.includes('vat'))) return 'category';
    if (n.includes('item') && n.includes('code')) return 'item_code';
    if (n.includes('barcode')) return 'barcode';
    // 3-tier units: names only
    if (n.includes('supplier') && n.includes('unit')) return 'supplier_unit';
    if (n.includes('wholesale') && n.includes('unit') && !n.includes('price')) return 'wholesale_unit';
    if (n.includes('retail') && n.includes('unit') && !n.includes('price')) return 'retail_unit';
    // Conversion rates (including new template: Conversion_To_Retail, Conversion_To_Supplier, Supplier_Pack_Size)
    if ((n.includes('pack') && n.includes('size')) || (n.includes('conversion') && (n.includes('retail') || n.includes('rate')) && !n.includes('supplier')) || n === 'conversion to retail') return 'pack_size';
    if ((n.includes('wholesale') && n.includes('supplier')) || (n.includes('conversion') && n.includes('supplier')) || n === 'conversion to supplier' || (n.includes('supplier') && n.includes('pack') && n.includes('size'))) return 'wholesale_units_per_supplier';
    if (n.includes('base') && n.includes('unit')) return 'wholesale_unit';
    if (n.includes('secondary') && n.includes('unit')) return 'retail_unit';
    // Prices: wholesale unit price (purchase cost per wholesale) first
    if ((n.includes('wholesale') && n.includes('price')) || (n.includes('purchase') && n.includes('wholesale')) || n === 'wholesale unit price') return 'wholesale_unit_price';
    if (n.includes('purchase') || n.includes('last cost') || n.includes('price list last cost')) return 'purchase_price_per_supplier_unit';
    // Stock
    if (n.includes('current') && (n.includes('stock') || n.includes('quantity'))) return 'current_stock_quantity';
    if (n.includes('minimum') && (n.includes('stock') || n.includes('quantity'))) return 'current_stock_quantity';
    if ((n.includes('stock') || n.includes('quantity')) && !n.includes('minimum')) return 'current_stock_quantity';
    if (n.includes('can') && n.includes('break')) return 'can_break_bulk';
    if (n.includes('track') && n.includes('expiry')) return 'track_expiry';
    if (n.includes('controlled')) return 'is_controlled';
    if (n.includes('cold') && n.includes('chain')) return 'is_cold_chain';
    // Fallback: match by label
    for (const f of expectedFields) {
        const labelNorm = normalizeForMatch(f.label);
        if (labelNorm === n || labelNorm.includes(n) || n.includes(labelNorm)) return f.id;
    }
    return '';
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const errorDiv = document.getElementById('excelError');
    const previewDiv = document.getElementById('excelPreview');
    const previewContent = document.getElementById('excelPreviewContent');
    const rowCount = document.getElementById('excelRowCount');
    const importBtn = document.getElementById('importExcelBtn');
    const mappingSection = document.getElementById('excelColumnMappingSection');
    const mappingContainer = document.getElementById('excelColumnMapping');
    
    errorDiv.style.display = 'none';
    previewDiv.style.display = 'none';
    if (mappingSection) mappingSection.style.display = 'none';
    importBtn.disabled = true;
    excelFile = null;
    excelImportHeaders = [];
    
    const reader = new FileReader();
    reader.onload = async function(e) {
        try {
            if (typeof XLSX === 'undefined') {
                throw new Error('XLSX library not loaded. Please refresh the page.');
            }
            
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, {type: 'array'});
            const sheetName = workbook.SheetNames[0];
            const worksheet = workbook.Sheets[sheetName];
            // Use header: 1 to get ALL columns (sheet_to_json by key collapses duplicate/empty headers)
            const rawRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '', raw: false });
            if (!rawRows || rawRows.length === 0) {
                throw new Error('No data found in Excel file');
            }
            const headerRow = rawRows[0] || [];
            const maxCols = Math.max(headerRow.length, ...rawRows.slice(1).map(r => (r && r.length) || 0));
            // Build unique headers per column (match pandas: empty -> "Unnamed: 0", duplicates -> "Name.1", "Name.2")
            const seen = {};
            const headers = [];
            for (let i = 0; i < maxCols; i++) {
                const raw = headerRow[i];
                const rawStr = (raw != null && raw !== '') ? String(raw).trim() : '';
                let name;
                if (rawStr === '') {
                    name = 'Unnamed: ' + i;
                } else {
                    if (seen[rawStr] !== undefined) {
                        seen[rawStr] += 1;
                        name = rawStr + '.' + seen[rawStr];
                    } else {
                        seen[rawStr] = 0;
                        name = rawStr;
                    }
                }
                headers.push(name);
            }
            // Build jsonData as array of objects keyed by headers (for preview and row count)
            const jsonData = rawRows.slice(1).map(row => {
                const obj = {};
                headers.forEach((h, i) => { obj[h] = (row && row[i] != null) ? row[i] : ''; });
                return obj;
            });
            if (jsonData.length === 0) {
                throw new Error('No data rows found in Excel file');
            }
            excelFile = file;
            excelImportHeaders = headers;
            
            // Show preview
            const previewRows = jsonData.slice(0, 5);
            let previewHTML = '<table style="width: 100%; font-size: 0.875rem;"><thead><tr>';
            headers.forEach(h => previewHTML += `<th style="padding: 0.5rem; border: 1px solid var(--border-color);">${escapeHtml(h)}</th>`);
            previewHTML += '</tr></thead><tbody>';
            previewRows.forEach(row => {
                previewHTML += '<tr>';
                headers.forEach(h => {
                    previewHTML += `<td style="padding: 0.5rem; border: 1px solid var(--border-color);">${escapeHtml(row[h] || '')}</td>`;
                });
                previewHTML += '</tr>';
            });
            previewHTML += '</tbody></table>';
            previewContent.innerHTML = previewHTML;
            rowCount.textContent = jsonData.length;
            previewDiv.style.display = 'block';
            
            // Fetch expected fields and build mapping UI
            let expectedFields = [];
            try {
                const res = await API.excel.getExpectedFields();
                expectedFields = (res && res.fields) || [];
            } catch (_) {
                // 3-tier only: wholesale = base (1), retail = wholesale × pack_size, supplier = wholesale ÷ wholesale_units_per_supplier
                expectedFields = [
                    { id: 'item_name', label: 'Item Name', required: true },
                    { id: 'description', label: 'Description', required: false },
                    { id: 'item_code', label: 'Item Code (SKU)', required: false },
                    { id: 'barcode', label: 'Barcode', required: false },
                    { id: 'category', label: 'Category', required: false },
                    { id: 'wholesale_unit', label: 'Wholesale Unit (base = 1 per item; e.g. box, bottle)', required: false },
                    { id: 'retail_unit', label: 'Retail Unit (e.g. tablet, piece, ml)', required: false },
                    { id: 'supplier_unit', label: 'Supplier Unit (e.g. carton, crate, dozen)', required: false },
                    { id: 'pack_size', label: 'Pack Size (retail per wholesale: 1 wholesale = N retail)', required: false },
                    { id: 'wholesale_units_per_supplier', label: 'Wholesale per Supplier (e.g. 12 = 1 carton has 12 wholesale)', required: false },
                    { id: 'can_break_bulk', label: 'Can Break Bulk', required: false },
                    { id: 'track_expiry', label: 'Track Expiry', required: false },
                    { id: 'is_controlled', label: 'Is Controlled', required: false },
                    { id: 'is_cold_chain', label: 'Is Cold Chain', required: false },
                    { id: 'wholesale_unit_price', label: 'Wholesale Unit Price (purchase cost per wholesale unit)', required: false },
                    { id: 'purchase_price_per_supplier_unit', label: 'Purchase Price per Supplier Unit (fallback)', required: false },
                    { id: 'wholesale_price_per_wholesale_unit', label: 'Wholesale Price', required: false },
                    { id: 'retail_price_per_retail_unit', label: 'Retail Price / Sale Price', required: false },
                    { id: 'current_stock_quantity', label: 'Current Stock Quantity', required: false },
                    { id: 'supplier', label: 'Supplier', required: false },
                    { id: 'vat_category', label: 'VAT Category', required: false },
                    { id: 'vat_rate', label: 'VAT Rate', required: false },
                ];
            }
            
            // Suggest which Excel header maps to each system field (first header that matches)
            function suggestedExcelHeaderForSystemField(systemFieldId, excelHeaders, expectedFields) {
                for (let i = 0; i < excelHeaders.length; i++) {
                    if (suggestFieldForHeader(excelHeaders[i], expectedFields) === systemFieldId) return excelHeaders[i];
                }
                return '';
            }
            let mappingHTML = '<table style="width: 100%; font-size: 0.875rem;"><thead><tr><th style="text-align:left;">PharmaSight field</th><th style="text-align:left;">Your Excel column</th></tr></thead><tbody>';
            expectedFields.forEach(f => {
                const suggested = suggestedExcelHeaderForSystemField(f.id, headers, expectedFields);
                const reqLabel = f.required ? ' <span style="color: var(--danger);">*</span>' : '';
                mappingHTML += '<tr><td style="padding: 0.35rem 0.5rem;">' + escapeHtml(f.label) + reqLabel + '</td><td style="padding: 0.35rem 0.5rem;">';
                mappingHTML += '<select class="form-input excel-map-select" data-system-field-id="' + escapeHtml(f.id) + '" style="min-width: 220px;">';
                mappingHTML += '<option value="">— Don\'t map —</option>';
                headers.forEach(h => {
                    const sel = h === suggested ? ' selected' : '';
                    mappingHTML += '<option value="' + escapeHtml(h) + '"' + sel + '>' + escapeHtml(h) + '</option>';
                });
                mappingHTML += '</select></td></tr>';
            });
            mappingHTML += '</tbody></table>';
            mappingContainer.innerHTML = mappingHTML;
            const colCountEl = document.getElementById('excelColumnCount');
            if (colCountEl) colCountEl.textContent = headers.length;
            const targetEl = document.getElementById('importTargetValue');
            if (targetEl) {
                const sub = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain');
                targetEl.textContent = sub ? `Tenant (${sub}) — items will appear when viewing this tenant` : 'Default database';
            }
            mappingSection.style.display = 'block';
            importBtn.disabled = false;
            
        } catch (error) {
            console.error('Excel parsing error:', error);
            errorDiv.style.display = 'block';
            errorDiv.innerHTML = '<strong>Error:</strong> ' + escapeHtml(error.message);
        }
    };
    
    reader.readAsArrayBuffer(file);
}

function escapeHtml(s) {
    if (s == null) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function getExcelColumnMapping() {
    const selects = document.querySelectorAll('#excelColumnMapping .excel-map-select');
    const mapping = {};
    selects.forEach(sel => {
        const systemId = (sel.getAttribute('data-system-field-id') || '').trim();
        const excelHeader = (sel.value || '').trim();
        if (excelHeader && systemId) {
            mapping[excelHeader] = systemId;
        }
    });
    return mapping;
}

// Prevent multiple simultaneous imports
let isImporting = false;

async function importExcelFile() {
    // Prevent multiple simultaneous imports
    if (isImporting) {
        showToast('Import already in progress. Please wait...', 'warning');
        return;
    }
    
    if (!excelFile) {
        showToast('Please select an Excel file first', 'error');
        return;
    }
    
    const columnMapping = getExcelColumnMapping();
    const hasItemName = Object.values(columnMapping).indexOf('item_name') !== -1;
    if (!hasItemName) {
        showToast('Please map at least one column to "Item Name" (required)', 'error');
        return;
    }
    
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID || !CONFIG.USER_ID) {
        showToast('Company, Branch, and User must be configured', 'error');
        return;
    }
    
    const importBtn = document.getElementById('importExcelBtn');
    const modalBody = document.querySelector('.modal-body');
    
    if (!modalBody) {
        showToast('Error: Modal not found', 'error');
        return;
    }
    
    // Set importing flag
    isImporting = true;
    
    // Add progress indicator with progress bar; scope warning at top so "default DB" is unmissable
    let progressHTML = `
        <div id="importScopeWarning" style="display: none; margin-bottom: 1rem; padding: 0.75rem 1rem; font-size: 0.9rem; background: rgba(220,53,69,0.12); border: 1px solid rgba(220,53,69,0.5); border-radius: 6px; color: var(--text-primary);"></div>
        <div id="importProgress" style="margin-top: 0; padding: 1rem; background: var(--bg-secondary); border-radius: 4px;">
            <div id="importStatus" style="font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                <i class="fas fa-spinner fa-spin"></i> <span id="importStatusText">Uploading and processing Excel file...</span>
            </div>
            <div style="width: 100%; background: var(--border-color); border-radius: 4px; height: 8px; overflow: hidden;">
                <div id="importProgressBar" style="width: 0%; height: 100%; background: var(--primary-color); transition: width 0.3s ease;"></div>
            </div>
            <div id="importProgressText" style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.25rem; text-align: center;">
                0%
            </div>
        </div>
    `;
    modalBody.insertAdjacentHTML('beforeend', progressHTML);
    
    // Progress update function
    const updateProgress = (percent, statusText) => {
        const progressBar = document.getElementById('importProgressBar');
        const progressText = document.getElementById('importProgressText');
        const statusTextEl = document.getElementById('importStatusText');
        if (progressBar) progressBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
        if (progressText) progressText.textContent = `${Math.round(percent)}%`;
        if (statusTextEl && statusText) statusTextEl.textContent = statusText;
    };
    
    // Simulate progress (since we can't get real-time updates without WebSocket)
    let progressPercent = 0;
    let progressInterval = null;
    let startTime = Date.now();
    let lastUpdateTime = startTime;
    
    importBtn.disabled = true;
    importBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importing...';
    
    // Poll for progress instead of simulating
    let pollInterval = null;
    let jobId = null;
    
    try {
        // Check import mode first
        const modeInfo = await API.excel.getMode(CONFIG.COMPANY_ID);
        updateProgress(5, `Mode: ${modeInfo.mode} - Starting import...`);
        
        // Upload file to backend. Sync=1: import runs in request, returns when done. Sync=0: returns job_id, poll progress.
        const useSync = document.getElementById('excelImportSyncCheckbox') ? document.getElementById('excelImportSyncCheckbox').checked : true;
        updateProgress(10, useSync ? 'Uploading and running import (this may take several minutes)...' : 'Uploading and starting import...');
        const startResult = await API.excel.import(
            excelFile,
            CONFIG.COMPANY_ID,
            CONFIG.BRANCH_ID,
            CONFIG.USER_ID,
            null,
            columnMapping,
            useSync
        );
        
        if (!startResult.job_id) {
            throw new Error('Failed to start import job');
        }
        
        jobId = startResult.job_id;
        if (startResult.success === false && (startResult.message || '').toLowerCase().includes('already in progress')) {
            showToast('Same file is already importing. Showing its progress. To start fresh, use "Clear for re-import" first (when no live transactions).', 'info');
        }
        
        // If backend ran import synchronously (sync=1), response has final status/stats — no polling
        if (startResult.status === 'completed' || startResult.status === 'failed') {
            clearInterval(pollInterval);
            const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
            if (startResult.status === 'completed') {
                updateProgress(100, `Import completed in ${totalTime} seconds!`);
                const stats = startResult.stats || {};
                const created = stats.items_created || 0;
                const updated = stats.items_updated || 0;
                let message = `Import completed successfully. `;
                message += `Items: ${created} created`;
                if (updated) message += `, ${updated} updated`;
                if (stats.items_skipped) message += `, ${stats.items_skipped} skipped`;
                if (stats.opening_balances_created) message += ` | Opening balances: ${stats.opening_balances_created} created`;
                if (stats.suppliers_created) message += ` | Suppliers: ${stats.suppliers_created} created`;
                if (stats.errors && stats.errors.length > 0) {
                    console.warn('Import errors:', stats.errors);
                    message += ` | ${stats.errors.length} errors (check console)`;
                }
                showToast(message, 'success');
                if (created === 0 && updated === 0 && (startResult.total_rows || 0) > 0) {
                    showToast('No items were created. If you use a tenant link, ensure you are viewing the same tenant. Or run with "Run import synchronously" to see any error.', 'warning');
                }
            } else {
                updateProgress(0, `Import failed after ${totalTime} seconds`);
                showToast(`Import failed: ${startResult.error_message || 'Unknown error'}`, 'error');
            }
            setTimeout(() => { closeModal(); loadItems(); }, 2000);
            if (importBtn) { importBtn.disabled = false; importBtn.innerHTML = '<i class="fas fa-upload"></i> Import Items'; }
            isImporting = false;
            return;
        }
        
        updateProgress(15, 'Import started - Processing in background...');
        
        let consecutiveFailures = 0;
        const maxConsecutiveFailures = 5;
        
        // Poll for progress every 2 seconds (async mode only)
        pollInterval = setInterval(async () => {
            try {
                const progress = await API.excel.getProgress(jobId);
                consecutiveFailures = 0; // Reset on success

                // Only warn when user has tenant context but progress is from default DB (mismatch). Default DB alone is the intended primary DB for now.
                const scopeEl = document.getElementById('importScopeWarning');
                const isDefaultDb = progress.database_scope === 'default';
                const hasTenantContext = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_tenant_subdomain');
                const mismatch = hasTenantContext && isDefaultDb; // expected tenant DB but got default
                if (scopeEl && mismatch) {
                    scopeEl.style.display = 'block';
                    scopeEl.innerHTML = '<strong><i class="fas fa-database"></i> Different database</strong><br>You opened the app with a tenant link but this import ran against the <strong>default database</strong>. To import into your tenant (Supabase), open the app from your tenant URL and run a new import.';
                } else if (scopeEl) {
                    scopeEl.style.display = 'none';
                }
                
                // Update progress bar with real data
                const progressPct = progress.progress_percent || 0;
                const status = progress.status;
                const processed = progress.processed_rows || 0;
                const total = progress.total_rows || 0;
                
                // Format elapsed time
                const elapsed = (Date.now() - startTime) / 1000;
                const minutes = Math.floor(elapsed / 60);
                const seconds = Math.floor(elapsed % 60);
                const timeStr = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
                
                if (status === 'processing' || status === 'pending') {
                    updateProgress(
                        progressPct,
                        `Processing ${processed}/${total} items... (${timeStr} elapsed)`
                    );
                } else if (status === 'completed') {
                    clearInterval(pollInterval);
                    const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
                    updateProgress(100, `Import completed in ${totalTime} seconds!`);
                    
                    // Same success message for default DB and tenant DB
                    const stats = progress.stats || {};
                    const created = stats.items_created || 0;
                    const updated = stats.items_updated || 0;
                    let message = `Import completed successfully. `;
                    message += `Items: ${created} created`;
                    if (updated) message += `, ${updated} updated`;
                    if (stats.items_skipped) message += `, ${stats.items_skipped} skipped`;
                    if (stats.opening_balances_created) message += ` | Opening balances: ${stats.opening_balances_created} created`;
                    if (stats.suppliers_created) message += ` | Suppliers: ${stats.suppliers_created} created`;
                    if (stats.errors && stats.errors.length > 0) {
                        console.warn('Import errors:', stats.errors);
                        message += ` | ${stats.errors.length} errors (check console)`;
                    }
                    showToast(message, 'success');
                    if (created === 0 && updated === 0 && (progress.total_rows || 0) > 0) {
                        showToast('No items were created. If you use a tenant link, ensure you are viewing the same tenant. Run with "Run import synchronously" to see any error.', 'warning');
                    }
                    
                    setTimeout(() => {
                        closeModal();
                        loadItems();
                    }, 2000);
                    
                } else if (status === 'failed') {
                    clearInterval(pollInterval);
                    const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
                    const errorMsg = progress.error_message || 'Unknown error';
                    updateProgress(0, `Import failed after ${totalTime} seconds`);
                    showToast(`Import failed: ${errorMsg}`, 'error');
                }
            } catch (pollError) {
                // 404 = job not in this database (e.g. job in default DB but user polling with tenant)
                if (pollError.status === 404) {
                    clearInterval(pollInterval);
                    const statusEl = document.getElementById('importStatus');
                    const statusTextEl = document.getElementById('importStatusText');
                    const scopeEl = document.getElementById('importScopeWarning');
                    if (statusEl) statusEl.innerHTML = '<span style="color: var(--danger-color);"><i class="fas fa-search"></i> Job not found in this database</span>';
                    if (statusTextEl) statusTextEl.textContent = 'This job is not in your current database. Open the app from your tenant URL (e.g. your-tenant.pharmasight.com) and start a new import to load data into Supabase.';
                    if (scopeEl) {
                        scopeEl.style.display = 'block';
                        scopeEl.innerHTML = '<strong><i class="fas fa-info-circle"></i> Job not in tenant database</strong><br>If you expected data in Supabase, open the app from your <strong>tenant URL</strong> and run a <strong>new import</strong>. This job may belong to the default database.';
                    }
                    showToast('Job not found in this database. Use your tenant URL and start a new import to load data into Supabase.', 'warning');
                    if (importBtn) { importBtn.disabled = false; importBtn.innerHTML = '<i class="fas fa-upload"></i> Import Items'; }
                    isImporting = false;
                    return;
                }
                consecutiveFailures += 1;
                if (consecutiveFailures >= maxConsecutiveFailures) {
                    clearInterval(pollInterval);
                    const statusEl = document.getElementById('importStatus');
                    const statusTextEl = document.getElementById('importStatusText');
                    const is503 = pollError.status === 503;
                    if (statusEl) {
                        statusEl.innerHTML = is503
                            ? '<span style="color: var(--danger-color);"><i class="fas fa-database"></i> Tenant database unreachable</span>'
                            : '<span style="color: var(--danger-color);"><i class="fas fa-unlink"></i> Cannot reach server</span>';
                    }
                    if (statusTextEl) {
                        statusTextEl.textContent = is503
                            ? (pollError.message || 'Cannot reach Supabase. Check network, Supabase status, or try again. Import may still be running.')
                            : 'Backend is not responding. Start the server on http://localhost:8000 and refresh the page to check if the import completed.';
                    }
                    showToast(is503 ? (pollError.message || 'Tenant database unreachable. Check Supabase and retry.') : 'Cannot reach server. Start the backend and refresh to check import status.', 'error');
                    if (importBtn) {
                        importBtn.disabled = false;
                        importBtn.innerHTML = '<i class="fas fa-upload"></i> Import Items';
                    }
                    isImporting = false;
                } else {
                    console.warn('Error polling progress (' + consecutiveFailures + '/' + maxConsecutiveFailures + '):', pollError.message || pollError);
                }
            }
        }, 2000); // Poll every 2 seconds
        
    } catch (error) {
        console.error('Excel import error:', error);
        if (pollInterval) clearInterval(pollInterval);
        const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
        const statusEl = document.getElementById('importStatus');
        const statusTextEl = document.getElementById('importStatusText');
        if (statusEl) {
            statusEl.innerHTML = `<span style="color: var(--danger-color);"><i class="fas fa-exclamation-triangle"></i> Error: ${error.message}</span>`;
        }
        if (statusTextEl) {
            statusTextEl.textContent = `Error: ${error.message} (after ${totalTime}s)`;
        }
        updateProgress(0, `Import failed after ${totalTime} seconds`);
        showToast(`Import failed: ${error.message}`, 'error');
    } finally {
        // Cleanup on error (success cleanup happens in poll callback)
        if (pollInterval && !jobId) {
            clearInterval(pollInterval);
        }
        isImporting = false;
        if (importBtn && !jobId) {
            importBtn.disabled = false;
            importBtn.innerHTML = '<i class="fas fa-upload"></i> Import Items';
        }
    }
}

async function editItem(itemId) {
    // Fetch full item details from API (branch_id for cost from ledger)
    let item;
    try {
        item = await API.items.get(itemId, CONFIG.BRANCH_ID || undefined);
        // Also check if we have overview data (for has_transactions flag)
        if (!item.has_transactions && itemsList.length > 0) {
            const overviewItem = itemsList.find(i => i.id === itemId);
            if (overviewItem && overviewItem.has_transactions !== undefined) {
                item.has_transactions = overviewItem.has_transactions;
            }
        }
    } catch (error) {
        console.error('Error fetching item details:', error);
        showToast('Item not found', 'error');
        return;
    }
    
    const hasTransactions = item.has_transactions || false;
    const isLocked = hasTransactions;
    
    const content = `
        <form id="editItemForm" onsubmit="updateItem(event, '${itemId}')" style="max-height: 70vh; overflow-y: auto;">
            ${isLocked ? `
                <div class="alert alert-warning" style="margin-bottom: 1rem;">
                    <i class="fas fa-lock"></i>
                    <strong>Locked Fields:</strong> This item has inventory transactions. 
                    Base unit and unit conversions cannot be modified to maintain data integrity.
                </div>
            ` : ''}
            
            <!-- Item Details Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-info-circle"></i> Item Details
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">
                            Item Code (SKU)
                            <i class="fas fa-lock" style="color: #dc3545; margin-left: 0.25rem;" title="SKU is immutable once created"></i>
                        </label>
                        <input 
                            type="text" 
                            class="form-input" 
                            name="sku" 
                            value="${escapeHtml(item.sku || '')}" 
                            readonly 
                            disabled
                            style="background-color: #f5f5f5; cursor: not-allowed;"
                            title="SKU cannot be modified once created"
                        >
                    </div>
                    <div class="form-group">
                        <label class="form-label">Barcode</label>
                        <input type="text" class="form-input" name="barcode" value="${escapeHtml(item.barcode || '')}" placeholder="Scan or enter barcode">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Item Name *</label>
                    <input type="text" class="form-input" name="name" value="${escapeHtml(item.name)}" required>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Generic Name</label>
                        <input type="text" class="form-input" name="description" value="${escapeHtml(item.description || '')}" placeholder="Enter generic name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Category</label>
                        <input type="text" class="form-input" name="category" value="${escapeHtml(item.category || '')}" placeholder="Enter category">
                    </div>
                </div>
            </div>

            <!-- Base Unit Section (Locked if has transactions) -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-ruler"></i> Unit Configuration
                    ${isLocked ? '<i class="fas fa-lock" style="color: #dc3545; margin-left: 0.5rem;" title="Locked after first transaction"></i>' : ''}
                </div>
                <div class="form-group">
                    <label class="form-label">
                        Base Unit (Wholesale) *
                        ${isLocked ? '<i class="fas fa-lock" style="color: #dc3545; margin-left: 0.25rem;" title="Cannot be modified after item has transactions"></i>' : ''}
                    </label>
                    <p style="color: var(--text-secondary); font-size: 0.8rem; margin: 0.25rem 0 0.5rem 0;">Reference unit for stock and pricing (e.g. bottle, piece, box). This is your <strong>wholesale</strong> unit.</p>
                    <select 
                        class="form-select" 
                        name="base_unit" 
                        required
                        ${isLocked ? 'disabled style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                        title="${isLocked ? 'Base unit is locked because item has inventory transactions' : 'Base unit (wholesale) for this item'}"
                    >
                        <option value="tablet" ${item.base_unit === 'tablet' ? 'selected' : ''}>Tablet</option>
                        <option value="capsule" ${item.base_unit === 'capsule' ? 'selected' : ''}>Capsule</option>
                        <option value="ml" ${item.base_unit === 'ml' ? 'selected' : ''}>ML (Milliliter)</option>
                        <option value="gram" ${item.base_unit === 'gram' ? 'selected' : ''}>Gram</option>
                        <option value="piece" ${item.base_unit === 'piece' ? 'selected' : ''}>Piece</option>
                        <option value="packet" ${item.base_unit === 'packet' ? 'selected' : ''}>Packet</option>
                        <option value="bottle" ${item.base_unit === 'bottle' ? 'selected' : ''}>Bottle</option>
                        <option value="tube" ${item.base_unit === 'tube' ? 'selected' : ''}>Tube</option>
                        <option value="sachet" ${item.base_unit === 'sachet' ? 'selected' : ''}>Sachet</option>
                        <option value="vial" ${item.base_unit === 'vial' ? 'selected' : ''}>Vial</option>
                        <option value="box" ${item.base_unit === 'box' ? 'selected' : ''}>Box</option>
                    </select>
                    ${isLocked ? '<input type="hidden" name="base_unit" value="' + escapeHtml(item.base_unit) + '">' : ''}
                </div>
                
                <!-- Units Display - Editable -->
                <div class="form-group" style="margin-top: 1rem;">
                    <label class="form-label">Unit Conversions (Retail & Supplier tiers)</label>
                    <p style="color: var(--text-secondary); font-size: 0.875rem; margin: 0.5rem 0;">
                        Base (wholesale): <strong>${escapeHtml(item.base_unit)}</strong> — Prices and stock are per ${escapeHtml(item.base_unit)}. Other rows are <strong>retail</strong> or <strong>supplier</strong> units with conversion to base.
                    </p>
                    <div id="unitsEditContainer" style="margin-top: 0.5rem;">
                        ${(item.units && item.units.length > 0) ? `
                            ${item.units.map((u, idx) => {
                                const multiplier = Number(u.multiplier_to_base);
                                const isLargerUnit = multiplier >= 1;
                                return `
                                <div class="unit-edit-row" data-unit-id="${u.id || ''}" style="display: flex; gap: 0.5rem; align-items: center; padding: 0.75rem; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 0.25rem; margin-bottom: 0.5rem;">
                                    <div style="flex: 1;">
                                        <label class="form-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">Unit Name</label>
                                        <input 
                                            type="text" 
                                            class="form-input unit-name-input" 
                                            value="${escapeHtml(u.unit_name)}" 
                                            placeholder="e.g., TAB, CARTON"
                                            ${isLocked ? 'readonly style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                                            data-unit-id="${u.id || ''}"
                                        >
                                    </div>
                                    <div style="flex: 1;">
                                        <label class="form-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">
                                            ${isLargerUnit ? `1 ${escapeHtml(u.unit_name)} = ? ${escapeHtml(item.base_unit)}` : `1 ${escapeHtml(item.base_unit)} = ? ${escapeHtml(u.unit_name)}`}
                                        </label>
                                        <input 
                                            type="number" 
                                            class="form-input unit-multiplier-input" 
                                            value="${isLargerUnit ? multiplier : (1 / multiplier)}" 
                                            step="0.01" 
                                            min="0.01"
                                            placeholder="Enter rate"
                                            ${isLocked ? 'readonly style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                                            data-unit-id="${u.id || ''}"
                                            data-is-larger="${isLargerUnit}"
                                        >
                                    </div>
                                    <div style="display: flex; flex-direction: column; gap: 0.25rem; align-items: center; min-width: 120px;">
                                        <label class="checkbox-item" style="margin: 0;">
                                            <input 
                                                type="checkbox" 
                                                class="unit-default-checkbox" 
                                                ${u.is_default ? 'checked' : ''}
                                                ${isLocked ? 'disabled' : ''}
                                                data-unit-id="${u.id || ''}"
                                            >
                                            <span style="font-size: 0.875rem;">Default</span>
                                        </label>
                                        ${!isLocked ? `
                                            <button 
                                                type="button" 
                                                class="btn btn-outline btn-sm remove-unit-btn" 
                                                style="padding: 0.25rem 0.5rem; font-size: 0.75rem;"
                                                data-unit-id="${u.id || ''}"
                                                onclick="removeEditUnitRow(this)"
                                            >
                                                <i class="fas fa-trash"></i> Remove
                                            </button>
                                        ` : ''}
                                    </div>
                                    <input type="hidden" class="unit-id-input" value="${u.id || ''}">
                                </div>
                            `;
                            }).join('')}
                        ` : `
                            <p style="color: var(--text-secondary); padding: 0.75rem; background: var(--bg-color); border-radius: 0.25rem; text-align: center;">
                                No secondary units. Item uses base unit (${escapeHtml(item.base_unit)}) only.
                            </p>
                        `}
                    </div>
                    ${!isLocked ? `
                        <button 
                            type="button" 
                            class="btn btn-outline" 
                            onclick="addEditUnitRow('${itemId}', '${escapeHtml(item.base_unit)}')"
                            style="margin-top: 0.5rem;"
                        >
                            <i class="fas fa-plus"></i> Add Secondary Unit
                        </button>
                    ` : ''}
                    ${isLocked ? `
                        <div class="alert alert-info" style="margin-top: 0.5rem;">
                            <i class="fas fa-lock"></i>
                            Unit conversions cannot be modified after item has inventory transactions. 
                            View units using the <i class="fas fa-cubes"></i> button.
                        </div>
                    ` : ''}
                </div>
            </div>

            <!-- Unit cost (from ledger): derive per wholesale / retail / supplier -->
            <div class="form-section" id="editItemUnitCostSection"
                data-cost-wholesale="${(item.default_cost != null ? item.default_cost : 0)}"
                data-pack-size="${Math.max(1, parseInt(item.pack_size, 10) || 1)}"
                data-wups="${Math.max(0.0001, parseFloat(item.wholesale_units_per_supplier) || 1)}"
                data-wholesale-unit="${escapeHtml((item.wholesale_unit || item.base_unit || 'piece'))}"
                data-retail-unit="${escapeHtml((item.retail_unit || 'piece'))}"
                data-supplier-unit="${escapeHtml((item.supplier_unit || 'piece'))}">
                <div class="form-section-title">
                    <i class="fas fa-coins"></i> Unit Cost (from ledger)
                </div>
                <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 0.75rem;">
                    Cost per wholesale unit from inventory ledger. Select unit below to see equivalent cost per retail or supplier unit (e.g. 90 per packet → 0.9 per tablet if conversion is 100).
                </p>
                <div class="form-row" style="align-items: center; gap: 1rem;">
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label">Show cost per</label>
                        <select id="editItemUnitCostSelect" class="form-select" style="min-width: 140px;">
                            <option value="wholesale">Wholesale (${escapeHtml((item.wholesale_unit || item.base_unit || 'piece'))})</option>
                            <option value="retail">Retail (${escapeHtml((item.retail_unit || 'piece'))})</option>
                            <option value="supplier">Supplier (${escapeHtml((item.supplier_unit || 'piece'))})</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 0; flex: 1;">
                        <label class="form-label">&nbsp;</label>
                        <p style="margin: 0; font-size: 1.1rem;"><strong id="editItemUnitCostValue">—</strong></p>
                    </div>
                </div>
            </div>

            <!-- Pricing: DEPRECATED — cost from inventory_ledger only; not editable here -->

            <!-- VAT Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-receipt"></i> VAT Classification
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">VAT Rate (%)</label>
                        <input type="number" class="form-input" name="vat_rate" value="${item.vat_rate || 0}" step="0.01" min="0" max="100">
                    </div>
                    <div class="form-group">
                        <label class="form-label">VAT Category</label>
                        <select class="form-select" name="vat_category">
                            <option value="ZERO_RATED" ${(item.vat_category || 'ZERO_RATED') === 'ZERO_RATED' ? 'selected' : ''}>Zero Rated</option>
                            <option value="STANDARD_RATED" ${(item.vat_category || '') === 'STANDARD_RATED' ? 'selected' : ''}>Standard Rated (16%)</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- Status Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-toggle-on"></i> Status & Attributes
                </div>
                <div class="form-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="is_active" ${item.is_active ? 'checked' : ''}>
                        <span>Item is active</span>
                    </label>
                </div>
                <div class="form-group" style="margin-top: 1rem;">
                    <div class="checkbox-group">
                        <label class="checkbox-item">
                            <input type="checkbox" name="is_controlled" ${item.is_controlled ? 'checked' : ''}>
                            <span>Controlled Substance</span>
                        </label>
                        <label class="checkbox-item">
                            <input type="checkbox" name="is_cold_chain" ${item.is_cold_chain ? 'checked' : ''}>
                            <span>Cold Chain Required</span>
                        </label>
                    </div>
                </div>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button type="submit" form="editItemForm" class="btn btn-primary">
            <i class="fas fa-save"></i> Update Item
        </button>
    `;
    
    showModal('Edit Item', content, footer, 'modal-large');
    
    // Store has_transactions in modal for quick access during update (avoids extra API call)
    const modal = document.getElementById('modal');
    if (modal) {
        modal.setAttribute('data-has-transactions', hasTransactions.toString());
    }
    
    // Unit cost display: derive cost per selected unit (wholesale / retail / supplier)
    setTimeout(() => {
        const sel = document.getElementById('editItemUnitCostSelect');
        const section = document.getElementById('editItemUnitCostSection');
        if (sel && section) {
            updateUnitCostDisplay(sel, section);
            sel.addEventListener('change', function() {
                updateUnitCostDisplay(this, section);
            });
        }
    }, 0);

    // Add event listeners to existing unit name inputs for dynamic label updates
    setTimeout(() => {
        const allNameInputs = document.querySelectorAll('.unit-name-input');
        allNameInputs.forEach(input => {
            if (!input.hasAttribute('data-listener-added')) {
                input.setAttribute('data-listener-added', 'true');
                input.addEventListener('input', function() {
                    const row = this.closest('.unit-edit-row');
                    const nameDisplay = row?.querySelector('.unit-name-display');
                    if (nameDisplay) {
                        nameDisplay.textContent = this.value || this.getAttribute('value') || 'UNIT';
                    }
                });
            }
        });
    }, 100);
}

/**
 * Update the "Unit cost (from ledger)" display when user changes unit (wholesale / retail / supplier).
 * Cost is stored per wholesale unit; retail = cost_wholesale / pack_size, supplier = cost_wholesale * wholesale_units_per_supplier.
 */
function updateUnitCostDisplay(selectEl, sectionEl) {
    if (!selectEl || !sectionEl) return;
    const costWholesale = parseFloat(sectionEl.dataset.costWholesale || '0') || 0;
    const packSize = Math.max(1, parseInt(sectionEl.dataset.packSize, 10) || 1);
    const wups = Math.max(0.0001, parseFloat(sectionEl.dataset.wups) || 1);
    const unitNames = {
        wholesale: sectionEl.dataset.wholesaleUnit || 'piece',
        retail: sectionEl.dataset.retailUnit || 'piece',
        supplier: sectionEl.dataset.supplierUnit || 'piece'
    };
    const tier = selectEl.value;
    let cost, unitName;
    if (tier === 'wholesale') {
        cost = costWholesale;
        unitName = unitNames.wholesale;
    } else if (tier === 'retail') {
        cost = packSize > 0 ? costWholesale / packSize : 0;
        unitName = unitNames.retail;
    } else {
        cost = costWholesale * wups;
        unitName = unitNames.supplier;
    }
    const valueEl = document.getElementById('editItemUnitCostValue');
    if (valueEl) {
        valueEl.textContent = (typeof window.formatCurrency === 'function' ? window.formatCurrency(cost) : cost.toFixed(2)) + ' per ' + unitName;
    }
}

async function updateItem(event, itemId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    // Get has_transactions from the form data attribute (set when modal opens)
    // This avoids an extra API call
    const formElement = form.closest('.modal') || form;
    const hasTransactionsAttr = formElement.getAttribute('data-has-transactions');
    let hasTransactions = false;
    
    if (hasTransactionsAttr !== null) {
        hasTransactions = hasTransactionsAttr === 'true';
    } else {
        // Fallback: try to get from cached item data if available
        // This is a last resort - normally we set it when opening the modal
        try {
            const item = await API.items.get(itemId);
            hasTransactions = item.has_transactions || false;
        } catch (error) {
            console.warn('Could not fetch item for transaction check, assuming false:', error);
            hasTransactions = false;
        }
    }
    
    // Do NOT send deprecated price fields — cost from inventory_ledger only
    const updateData = {
        name: formData.get('name'),
        description: formData.get('description') || null,
        barcode: formData.get('barcode') || null,
        category: formData.get('category') || null,
        vat_rate: parseFloat(formData.get('vat_rate')) || 0,
        vat_category: formData.get('vat_category') || null,
        is_active: formData.has('is_active')
    };
    
    // Only include base_unit if item doesn't have transactions
    if (!hasTransactions && formData.get('base_unit')) {
        updateData.base_unit = formData.get('base_unit');
    }
    
    // Collect units data (only if not locked)
    if (!hasTransactions) {
        const units = [];
        const unitRows = document.querySelectorAll('.unit-edit-row');
        
        unitRows.forEach(row => {
            const unitId = row.querySelector('.unit-id-input')?.value || null;
            const unitName = row.querySelector('.unit-name-input')?.value?.trim();
            const multiplierInput = row.querySelector('.unit-multiplier-input');
            const multiplierValue = parseFloat(multiplierInput?.value);
            const isLarger = multiplierInput?.dataset.isLarger === 'true';
            const isDefault = row.querySelector('.unit-default-checkbox')?.checked || false;
            
            if (unitName && multiplierValue && multiplierValue > 0) {
                // Convert multiplier based on unit type
                // If isLarger: multiplier is already correct (e.g., 100 means 1 CARTON = 100 packets)
                // If not isLarger: we need to invert (e.g., if user enters 100, it means 1 packet = 100 tabs, so multiplier = 1/100 = 0.01)
                const multiplier = isLarger ? multiplierValue : (1 / multiplierValue);
                
                units.push({
                    id: unitId || null,
                    unit_name: unitName,
                    multiplier_to_base: multiplier,
                    is_default: isDefault
                });
            }
        });
        
        // Only include units if there are any (or if explicitly empty to remove all)
        updateData.units = units;
    }
    
    // SKU is never included (immutable)
    
    try {
        await API.items.update(itemId, updateData);
        showToast('Item updated successfully!', 'success');
        closeModal();
        
        // Reload current page - check which page we're on
        const currentHash = window.location.hash || '';
        const itemsPage = document.getElementById('items');
        const inventoryContainer = document.getElementById('itemsTableContainer');
        
        if (currentHash.includes('#inventory') || inventoryContainer) {
            // On inventory page - refresh the items view
            if (window.loadItemsData) {
                // Reset to initial state
                window.loadItemsData();
            }
            // Also reload inventory page to refresh everything
            if (window.loadInventory) {
                window.loadInventory();
            }
        } else if (currentHash.includes('#items') || itemsPage) {
            // On items page - reload items
            if (window.loadItems && itemsPage) {
                window.loadItems();
            }
        } else {
            // Fallback: try to reload inventory first (most common)
            if (window.loadInventory) {
                window.loadInventory();
            } else if (window.loadItems && itemsPage) {
                window.loadItems();
            }
        }
    } catch (error) {
        console.error('Error updating item:', error);
        const errorMsg = error.data?.detail || error.message || 'Error updating item';
        showToast(errorMsg, 'error');
    }
}

async function viewItemUnits(itemId) {
    // Fetch item from API (works from any page)
    let item;
    try {
        item = await API.items.get(itemId);
    } catch (error) {
        console.error('Error fetching item for units view:', error);
        showToast('Item not found', 'error');
        return;
    }
    
    const unitsList = (item.units || []).map(u => 
        `<li>${u.unit_name}: ${u.multiplier_to_base} ${item.base_unit}${u.is_default ? ' (Default)' : ''}</li>`
    ).join('');
    
    const content = `
        <div>
            <h4>${item.name}</h4>
            <p><strong>Base Unit:</strong> ${item.base_unit}</p>
            <h5>Unit Conversions:</h5>
            <ul>${unitsList}</ul>
        </div>
    `;
    
    showModal('Item Units', content, '<button class="btn btn-secondary" onclick="closeModal()">Close</button>');
}

// Add unit row function for edit modal
function addEditUnitRow(itemId, baseUnit) {
    const container = document.getElementById('unitsEditContainer');
    if (!container) return;
    
    // Check if container has the "no units" message
    const noUnitsMsg = container.querySelector('p');
    if (noUnitsMsg) {
        container.innerHTML = '';
    }
    
    const newRow = document.createElement('div');
    newRow.className = 'unit-edit-row';
    newRow.setAttribute('data-unit-id', '');
    newRow.style.cssText = 'display: flex; gap: 0.5rem; align-items: center; padding: 0.75rem; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 0.25rem; margin-bottom: 0.5rem;';
    
    newRow.innerHTML = `
        <div style="flex: 1;">
            <label class="form-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">Unit Name</label>
            <input 
                type="text" 
                class="form-input unit-name-input" 
                placeholder="e.g., TAB, CARTON"
                data-unit-id=""
            >
        </div>
        <div style="flex: 1;">
            <label class="form-label unit-conversion-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">
                1 <span class="unit-name-display">NEW_UNIT</span> = ? ${escapeHtml(baseUnit)}
            </label>
            <input 
                type="number" 
                class="form-input unit-multiplier-input" 
                value="1" 
                step="0.01" 
                min="0.01"
                placeholder="Enter rate"
                data-unit-id=""
                data-is-larger="true"
            >
        </div>
        <div style="display: flex; flex-direction: column; gap: 0.25rem; align-items: center; min-width: 120px;">
            <label class="checkbox-item" style="margin: 0;">
                <input 
                    type="checkbox" 
                    class="unit-default-checkbox" 
                    data-unit-id=""
                >
                <span style="font-size: 0.875rem;">Default</span>
            </label>
            <button 
                type="button" 
                class="btn btn-outline btn-sm remove-unit-btn" 
                style="padding: 0.25rem 0.5rem; font-size: 0.75rem;"
                data-unit-id=""
                onclick="removeEditUnitRow(this)"
            >
                <i class="fas fa-trash"></i> Remove
            </button>
        </div>
        <input type="hidden" class="unit-id-input" value="">
    `;
    
    container.appendChild(newRow);
    
    // Update unit name display when user types
    const nameInput = newRow.querySelector('.unit-name-input');
    const nameDisplay = newRow.querySelector('.unit-name-display');
    const baseUnitText = baseUnit;
    
    if (nameInput && nameDisplay) {
        nameInput.addEventListener('input', function() {
            const unitName = this.value || 'NEW_UNIT';
            nameDisplay.textContent = unitName;
        });
    }
}

// Remove unit row function for edit modal
function removeEditUnitRow(button) {
    const row = button.closest('.unit-edit-row');
    if (row) {
        row.remove();
        
        // If no units left, show message
        const container = document.getElementById('unitsEditContainer');
        if (container && container.querySelectorAll('.unit-edit-row').length === 0) {
            const baseUnit = document.querySelector('select[name="base_unit"]')?.value || 'base unit';
            container.innerHTML = `
                <p style="color: var(--text-secondary); padding: 0.75rem; background: var(--bg-color); border-radius: 0.25rem; text-align: center;">
                    No secondary units. Item uses base unit (${escapeHtml(baseUnit)}) only.
                </p>
            `;
        }
    }
}

// Export
window.loadItems = loadItems;
window.showAddItemModal = showAddItemModal;
window.showImportExcelModal = showImportExcelModal;
window.downloadItemTemplate = downloadItemTemplate;
window.handleFileSelect = handleFileSelect;
window.importExcelFile = importExcelFile;
window.addUnitRow = addUnitRow;
window.removeUnitRow = removeUnitRow;
window.saveItem = saveItem;
window.editItem = editItem;
window.updateItem = updateItem;
window.viewItemUnits = viewItemUnits;
window.filterItems = filterItems;
window.loadAllItems = loadAllItems;
window.clearItemsView = clearItemsView;
// Export unit editing functions (for edit modal)
window.addEditUnitRow = addEditUnitRow;
window.removeEditUnitRow = removeEditUnitRow;

