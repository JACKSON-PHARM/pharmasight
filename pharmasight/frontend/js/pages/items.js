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
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Base Unit</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Category</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Current Stock</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Last Supplier</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Last Unit Cost</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Default Cost</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
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
                        <input type="text" class="form-input" name="generic_name" placeholder="Enter generic name">
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

            <!-- Item Specifications Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-flask"></i> Specifications
                </div>
                <div class="form-group">
                    <label class="form-label">Ingredients/Composition</label>
                    <textarea class="form-textarea" name="ingredients" rows="3" placeholder="Enter active ingredients and composition"></textarea>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Strength</label>
                        <input type="text" class="form-input" name="strength" placeholder="Enter strength">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Base Unit/Unit Measure *</label>
                        <select class="form-select" name="base_unit" required>
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
                        <label class="form-label">Pack Size</label>
                        <input type="text" class="form-input" name="pack_size" placeholder="Enter pack size">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Standard Pack</label>
                        <input type="text" class="form-input" name="std_pack" placeholder="Standard packaging unit">
                    </div>
                </div>
                <div class="form-row">
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

            <!-- Pricing Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-dollar-sign"></i> Pricing
                </div>
                <div class="form-group">
                    <label class="form-label">Default Cost per Base Unit</label>
                    <input type="number" class="form-input" name="default_cost" step="0.01" min="0" value="0" placeholder="0.00">
                </div>
            </div>

            <!-- VAT/Tax Classification Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-receipt"></i> VAT/Tax Classification
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Is VATable? *</label>
                        <div style="display: flex; gap: 2rem; margin-top: 0.5rem;">
                            <label class="checkbox-item">
                                <input type="radio" name="is_vatable" value="true" checked>
                                <span>Yes</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="radio" name="is_vatable" value="false">
                                <span>No</span>
                            </label>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">VAT Code *</label>
                        <select class="form-select" name="vat_code" required>
                            <option value="ZERO_RATED" selected>ZERO_RATED (0%)</option>
                            <option value="STANDARD">STANDARD (16%)</option>
                            <option value="EXEMPT">EXEMPT</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">VAT Rate (%)</label>
                        <input type="number" class="form-input" name="vat_rate" step="0.01" min="0" max="100" value="0" placeholder="0.00">
                        <small style="color: var(--text-secondary); font-size: 0.85rem;">0% for zero-rated medicines, 16% for standard-rated items</small>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Price Includes VAT?</label>
                        <div style="display: flex; gap: 2rem; margin-top: 0.5rem;">
                            <label class="checkbox-item">
                                <input type="radio" name="price_includes_vat" value="true">
                                <span>Yes</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="radio" name="price_includes_vat" value="false" checked>
                                <span>No</span>
                            </label>
                        </div>
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
    
    // Auto-update VAT rate when VAT code changes
    setTimeout(() => {
        const vatCodeSelect = document.querySelector('#itemForm select[name="vat_code"]');
        const vatRateInput = document.querySelector('#itemForm input[name="vat_rate"]');
        
        if (vatCodeSelect && vatRateInput) {
            vatCodeSelect.addEventListener('change', (e) => {
                const vatCode = e.target.value;
                if (vatCode === 'STANDARD') {
                    vatRateInput.value = '16.00';
                } else if (vatCode === 'ZERO_RATED' || vatCode === 'EXEMPT') {
                    vatRateInput.value = '0.00';
                }
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
    
    // Build item data - map fields to our schema
    const itemData = {
        company_id: CONFIG.COMPANY_ID,
        name: formData.get('name'),
        generic_name: formData.get('generic_name') || null,
        sku: formData.get('sku') || null,
        barcode: formData.get('barcode') || null,
        category: formData.get('category') || null,
        base_unit: formData.get('base_unit'),
        default_cost: parseFloat(formData.get('default_cost') || 0),
        // VAT/Tax fields
        is_vatable: formData.get('is_vatable') === 'true',
        vat_code: formData.get('vat_code') || 'ZERO_RATED',
        vat_rate: parseFloat(formData.get('vat_rate') || 0),
        price_includes_vat: formData.get('price_includes_vat') === 'true',
        units: []
    };
    
    // Auto-set VAT rate based on VAT code
    if (itemData.vat_code === 'STANDARD') {
        itemData.vat_rate = 16.00;
    } else if (itemData.vat_code === 'ZERO_RATED') {
        itemData.vat_rate = 0.00;
    } else if (itemData.vat_code === 'EXEMPT') {
        itemData.vat_rate = 0.00;
    }
    
    // Collect units (breaking bulk)
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
    
    // Ensure base unit is included
    const hasBaseUnit = itemData.units.some(u => u.unit_name === itemData.base_unit);
    if (!hasBaseUnit) {
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
                sale_price: 0, // Will be calculated by pricing service
                purchase_price: itemData.default_cost,
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
    
    // Template headers exactly matching pharmasight_template.xlsx
    const headers = [
        'Item name*',
        'Item code',
        'Description',
        'Category',
        'Base Unit (x)',
        'Secondary Unit (y)',
        'Conversion Rate (n) (x = ny)',
        'Supplier',
        'markup_Margin',
        'Price_List_Retail_Price',
        'Price_List_Wholesale_Price',
        'Price_List_Trade_Price',
        'Price_List_Last_Cost',
        'Price_List_Average_Cost',
        'Price_List_Retail_Unit_Price',
        'Price_List_Wholesale_Unit_Price',
        'Price_List_Trade_Unit_Price',
        'Price_List_Tax_Code',
        'Price_List_Tax_Percentage',
        'Price_List_Tax_Description',
        'Price_List_Tax_Type',
        'Price_List_Price_Inclusive',
        'Current stock quantity',
        'Minimum stock quantity',
        'HSN',
        'Sale Discount',
        'Tax Rate',
        'Inclusive Of Tax',
        'Price_List_Min_Price',
        'Price_List_Special_Price',
        'Price_List_Has_Refill',
        'Price_List_Not_For_Sale',
        'Price_List_Is_Physical_Item',
        'Price_List_Min_Wholesale_Price',
        'Price_List_Min_Wholesale_Unit_Price',
        'Price_List_Min_Retail_Price',
        'Price_List_Min_Retail_Unit_Price',
        'Price_List_Min_Trade_Price',
        'Price_List_Min_Trade_Unit_Price'
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

function showImportExcelModal() {
    const content = `
        <div>
            <div class="alert alert-info">
                <i class="fas fa-info-circle"></i>
                <p><strong>Excel Import Instructions:</strong></p>
                <ol style="margin-top: 0.5rem; padding-left: 1.5rem;">
                    <li>Click "Download Template" to get the Excel template with required headers</li>
                    <li>Fill in your items (don't change the headers)</li>
                    <li>Select your filled file below and click Import</li>
                    <li><strong>Required:</strong> Item name*, Purchase price, Base Unit (x)</li>
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
                    <span id="excelRowCount">0</span> rows found. Ready to import?
                </p>
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

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const errorDiv = document.getElementById('excelError');
    const previewDiv = document.getElementById('excelPreview');
    const previewContent = document.getElementById('excelPreviewContent');
    const rowCount = document.getElementById('excelRowCount');
    const importBtn = document.getElementById('importExcelBtn');
    
    errorDiv.style.display = 'none';
    previewDiv.style.display = 'none';
    importBtn.disabled = true;
    excelFile = null;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            if (typeof XLSX === 'undefined') {
                throw new Error('XLSX library not loaded. Please refresh the page.');
            }
            
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, {type: 'array'});
            const sheetName = workbook.SheetNames[0];
            const worksheet = workbook.Sheets[sheetName];
            const jsonData = XLSX.utils.sheet_to_json(worksheet, {defval: ''});
            
            if (jsonData.length === 0) {
                throw new Error('No data found in Excel file');
            }
            
            excelFile = file; // Store file for upload
            
            // Show preview
            const previewRows = jsonData.slice(0, 5);
            const headers = Object.keys(jsonData[0]);
            
            let previewHTML = '<table style="width: 100%; font-size: 0.875rem;"><thead><tr>';
            headers.forEach(h => previewHTML += `<th style="padding: 0.5rem; border: 1px solid var(--border-color);">${h}</th>`);
            previewHTML += '</tr></thead><tbody>';
            
            previewRows.forEach(row => {
                previewHTML += '<tr>';
                headers.forEach(h => {
                    previewHTML += `<td style="padding: 0.5rem; border: 1px solid var(--border-color);">${row[h] || ''}</td>`;
                });
                previewHTML += '</tr>';
            });
            previewHTML += '</tbody></table>';
            
            previewContent.innerHTML = previewHTML;
            rowCount.textContent = jsonData.length;
            previewDiv.style.display = 'block';
            importBtn.disabled = false;
            
        } catch (error) {
            console.error('Excel parsing error:', error);
            errorDiv.style.display = 'block';
            errorDiv.innerHTML = `<strong>Error:</strong> ${error.message}`;
        }
    };
    
    reader.readAsArrayBuffer(file);
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
    
    // Add progress indicator
    let progressHTML = `
        <div id="importProgress" style="margin-top: 1rem; padding: 1rem; background: var(--bg-secondary); border-radius: 4px;">
            <div id="importStatus" style="font-size: 0.875rem; color: var(--text-secondary);">
                <i class="fas fa-spinner fa-spin"></i> Uploading and processing Excel file...
            </div>
        </div>
    `;
    modalBody.insertAdjacentHTML('beforeend', progressHTML);
    
    importBtn.disabled = true;
    importBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importing...';
    
    try {
        // Check import mode first
        const modeInfo = await API.excel.getMode(CONFIG.COMPANY_ID);
        const statusEl = document.getElementById('importStatus');
        if (statusEl) {
            statusEl.innerHTML = `<i class="fas fa-info-circle"></i> Mode: ${modeInfo.mode} ${modeInfo.has_live_transactions ? '(Live transactions detected - non-destructive)' : '(No live transactions - authoritative reset allowed)'}`;
        }
        
        // Upload file to backend
        const result = await API.excel.import(
            excelFile,
            CONFIG.COMPANY_ID,
            CONFIG.BRANCH_ID,
            CONFIG.USER_ID
        );
        
        // Show results
        const stats = result.stats || {};
        let message = `Import completed in ${result.mode} mode. `;
        message += `Items: ${stats.items_created || 0} created`;
        if (stats.items_updated) message += `, ${stats.items_updated} updated`;
        if (stats.items_skipped) message += `, ${stats.items_skipped} skipped`;
        if (stats.opening_balances_created) message += ` | Opening balances: ${stats.opening_balances_created} created`;
        if (stats.suppliers_created) message += ` | Suppliers: ${stats.suppliers_created} created`;
        
        if (stats.errors && stats.errors.length > 0) {
            console.warn('Import errors:', stats.errors);
            message += ` | ${stats.errors.length} errors (check console)`;
        }
        
        showToast(message, result.success ? 'success' : 'warning');
        closeModal();
        loadItems();
        
    } catch (error) {
        console.error('Excel import error:', error);
        const statusEl = document.getElementById('importStatus');
        if (statusEl) {
            statusEl.innerHTML = `<span style="color: var(--danger-color);"><i class="fas fa-exclamation-triangle"></i> Error: ${error.message}</span>`;
        }
        showToast(`Import failed: ${error.message}`, 'error');
    } finally {
        isImporting = false;
        importBtn.disabled = false;
        importBtn.innerHTML = '<i class="fas fa-upload"></i> Import Items';
    }
}

async function editItem(itemId) {
    // Fetch full item details from API (works from any page)
    let item;
    try {
        item = await API.items.get(itemId);
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
                        <input type="text" class="form-input" name="generic_name" value="${escapeHtml(item.generic_name || '')}" placeholder="Enter generic name">
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
                        Base Unit *
                        ${isLocked ? '<i class="fas fa-lock" style="color: #dc3545; margin-left: 0.25rem;" title="Cannot be modified after item has transactions"></i>' : ''}
                    </label>
                    <select 
                        class="form-select" 
                        name="base_unit" 
                        required
                        ${isLocked ? 'disabled style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                        title="${isLocked ? 'Base unit is locked because item has inventory transactions' : 'Base unit for this item'}"
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
                    <label class="form-label">Unit Conversions</label>
                    <p style="color: var(--text-secondary); font-size: 0.875rem; margin: 0.5rem 0;">
                        Base unit: <strong>${escapeHtml(item.base_unit)}</strong> (Price is per ${escapeHtml(item.base_unit)})
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

            <!-- Pricing Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-dollar-sign"></i> Pricing
                </div>
                <div class="form-group">
                    <label class="form-label">Default Cost per Base Unit</label>
                    <input type="number" class="form-input" name="default_cost" value="${item.default_cost || 0}" step="0.01" min="0" required>
                </div>
            </div>

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
                        <label class="form-label">VAT Code</label>
                        <select class="form-select" name="vat_code">
                            <option value="">Select VAT Code</option>
                            <option value="ZERO_RATED" ${item.vat_code === 'ZERO_RATED' ? 'selected' : ''}>Zero Rated</option>
                            <option value="STANDARD" ${item.vat_code === 'STANDARD' ? 'selected' : ''}>Standard (16%)</option>
                            <option value="EXEMPT" ${item.vat_code === 'EXEMPT' ? 'selected' : ''}>Exempt</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="price_includes_vat" ${item.price_includes_vat ? 'checked' : ''}>
                        <span>Price includes VAT</span>
                    </label>
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
    
    const updateData = {
        name: formData.get('name'),
        generic_name: formData.get('generic_name') || null,
        barcode: formData.get('barcode') || null,
        category: formData.get('category') || null,
        default_cost: parseFloat(formData.get('default_cost')) || 0,
        vat_rate: parseFloat(formData.get('vat_rate')) || 0,
        vat_code: formData.get('vat_code') || null,
        price_includes_vat: formData.has('price_includes_vat'),
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

