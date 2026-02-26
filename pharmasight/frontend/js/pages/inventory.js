// Inventory Management Page with Sidebar Navigation

let currentInventorySubPage = 'items'; // items, batch, expiry, movement, stock

/** Last valuation result for Current Stock export (CSV/Excel/Print). */
let lastCurrentStockValuation = null;

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
async function loadInventory(optionalSubPage) {
    console.log('loadInventory called', optionalSubPage != null ? 'subPage=' + optionalSubPage : '');
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
        
        // Respect URL subpage so Current Stock (and others) persist and aren't overwritten by hashchange
        const validSubPages = ['items', 'batch', 'expiry', 'movement', 'stock', 'branch-orders', 'branch-transfers', 'branch-receipts'];
        if (optionalSubPage && validSubPages.includes(optionalSubPage)) {
            currentInventorySubPage = optionalSubPage;
        } else {
            currentInventorySubPage = 'items';
        }
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
            case 'branch-orders':
                return renderBranchOrdersSubPage();
            case 'branch-transfers':
                return renderBranchTransfersSubPage();
            case 'branch-receipts':
                return renderBranchReceiptsSubPage();
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
                    <button class="btn btn-outline" onclick="clearForReimport()" id="clearForReimportBtn" title="Clear all company data (items, inventory, sales, purchases, etc.) so you can run a fresh Excel import. Schema is kept.">
                        <i class="fas fa-broom"></i> Clear data
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
    try {
        switch(currentInventorySubPage) {
            case 'items':
                await loadItemsData();
                break;
            case 'batch':
                await loadBatchTrackingData();
                break;
            case 'branch-orders':
                if (branchOrdersView === 'create') await initBranchOrderCreatePage();
                else if (branchOrdersView === 'view' && branchOrderViewId) await loadBranchOrderViewPage(branchOrderViewId);
                else await loadBranchOrdersData();
                break;
            case 'branch-transfers':
                if (branchTransfersView === 'create') await initBranchTransferCreatePage();
                else if (branchTransfersView === 'view' && branchTransferViewId) await loadBranchTransferViewPage(branchTransferViewId);
                else await loadBranchTransfersData();
                break;
            case 'branch-receipts':
                if (branchReceiptsView === 'view' && branchReceiptViewId) await loadBranchReceiptViewPage(branchReceiptViewId);
                else await loadBranchReceiptsData();
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
    } catch (err) {
        console.error('Error loading inventory sub-page data:', err);
        if (currentInventorySubPage === 'stock') {
            var container = document.getElementById('currentStockContainer');
            if (container) {
                container.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Failed to load. ' + (err && err.message ? escapeHtml(err.message) : 'Unknown error') + '</div>';
            }
        }
    }
}

// ============================================
// BRANCH INVENTORY (Orders, Transfers, Receipts)
// ============================================
let branchOrdersList = [];
let branchTransfersList = [];
let branchReceiptsList = [];
let branchSettingsCache = null; // { allow_manual_transfer, allow_manual_receipt } for current branch
var branchOrdersView = 'list'; // 'list' | 'create' | 'view'
var branchOrderViewId = null;
var branchTransfersView = 'list'; // 'list' | 'create' | 'view'
var branchTransferViewId = null;
var branchReceiptsView = 'list'; // 'list' | 'view'
var branchReceiptViewId = null;
var currentBranchName = '';

function formatDate(d) {
    if (!d) return '—';
    const dt = typeof d === 'string' ? new Date(d) : d;
    return isNaN(dt.getTime()) ? '—' : dt.toLocaleDateString();
}

async function getBranchSettingsForCurrentBranch() {
    const bid = CONFIG.BRANCH_ID;
    if (!bid) return { allow_manual_transfer: true, allow_manual_receipt: true };
    try {
        const s = await API.branch.getSettings(bid);
        branchSettingsCache = s;
        return s;
    } catch (e) {
        return { allow_manual_transfer: true, allow_manual_receipt: true };
    }
}

function renderBranchOrdersSubPage() {
    if (branchOrdersView === 'create') return renderBranchOrderCreatePage();
    if (branchOrdersView === 'view') return renderBranchOrderViewPage();
    const today = new Date().toISOString().split('T')[0];
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-list-alt"></i> Branch Orders</h3>
                <button class="btn btn-primary" onclick="if(window.openBranchOrderCreate) window.openBranchOrderCreate()">
                    <i class="fas fa-plus"></i> New Order
                </button>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
                    <label>From</label>
                    <input type="date" id="branchOrdersDateFrom" class="form-input" value="${today}" style="width: 140px;">
                    <label>To</label>
                    <input type="date" id="branchOrdersDateTo" class="form-input" value="${today}" style="width: 140px;">
                    <select id="branchOrdersStatus" class="form-input" style="width: 140px;">
                        <option value="">All</option>
                        <option value="DRAFT">Draft</option>
                        <option value="BATCHED">Batched</option>
                    </select>
                    <button class="btn btn-primary" onclick="if(window.loadBranchOrdersData) window.loadBranchOrdersData()">Apply</button>
                </div>
                <div class="table-container" style="max-height: calc(100vh - 320px); overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 10;">
                            <tr>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Document #</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Date</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Status</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">From (Ordering)</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">To (Supplying)</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Total units</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Created by</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="branchOrdersTableBody">
                            <tr><td colspan="8" style="padding: 2rem; text-align: center;"><div class="spinner"></div> Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function renderBranchOrderCreatePage() {
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-plus-circle"></i> Create Branch Order</h3>
                <button class="btn btn-outline" onclick="if(window.showBranchOrdersList) window.showBranchOrdersList()">
                    <i class="fas fa-arrow-left"></i> Back to list
                </button>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <p style="margin-bottom: 1rem; color: var(--text-secondary);">Ordering branch (this branch) requests stock from the supplying branch. Add items manually or fetch from the Order Book.</p>
                <div class="form-group" style="margin-bottom: 1rem;">
                    <label class="form-label">Ordering branch (requesting)</label>
                    <div class="form-input" style="background: var(--bg-secondary, #f8f9fa); cursor: default;" id="branchOrderOrderingBranchName">—</div>
                </div>
                <div class="form-group" style="margin-bottom: 1rem;">
                    <label class="form-label">Supplying branch (sending) *</label>
                    <div id="branchOrderSupplyingBranchWrap"><span style="color: var(--text-secondary);">Loading branches...</span></div>
                </div>
                <div class="form-group" style="margin-bottom: 0.5rem;">
                    <label class="form-label">Items</label>
                    <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 0.5rem;">When you batch this order, items will be added to the Order Book and marked as converted (Branch Order).</p>
                    <div id="branchOrderTableMount"></div>
                </div>
                <div style="margin-top: 1.5rem; display: flex; gap: 0.5rem;">
                    <button type="button" class="btn btn-primary" id="branchOrderSaveDraftBtn" onclick="if(window.saveBranchOrderDraft) window.saveBranchOrderDraft()">
                        <i class="fas fa-save"></i> Save as draft
                    </button>
                    <button type="button" class="btn btn-outline" onclick="if(window.showBranchOrdersList) window.showBranchOrdersList()">Cancel</button>
                </div>
            </div>
        </div>
    `;
}

function renderBranchOrderViewPage() {
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-list-alt"></i> Branch Order</h3>
                <button class="btn btn-outline" onclick="if(window.showBranchOrdersList) window.showBranchOrdersList()"><i class="fas fa-arrow-left"></i> Back to list</button>
            </div>
            <div class="card-body" style="padding: 1.5rem;" id="branchOrderViewContent">
                <div style="text-align: center; padding: 2rem;"><div class="spinner"></div> Loading...</div>
            </div>
        </div>
    `;
}

function renderBranchTransfersSubPage() {
    if (branchTransfersView === 'create') return renderBranchTransferCreatePage();
    if (branchTransfersView === 'view') return renderBranchTransferViewPage();
    const today = new Date().toISOString().split('T')[0];
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-truck-loading"></i> Branch Transfers</h3>
                <div id="branchTransfersHeaderButtons">
                    <span style="color: var(--text-secondary); font-size: 0.875rem;">Loading...</span>
                </div>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
                    <label>From</label>
                    <input type="date" id="branchTransfersDateFrom" class="form-input" value="${today}" style="width: 140px;">
                    <label>To</label>
                    <input type="date" id="branchTransfersDateTo" class="form-input" value="${today}" style="width: 140px;">
                    <select id="branchTransfersStatus" class="form-input" style="width: 140px;">
                        <option value="">All</option>
                        <option value="DRAFT">Draft</option>
                        <option value="COMPLETED">Completed</option>
                    </select>
                    <button class="btn btn-primary" onclick="if(window.loadBranchTransfersData) window.loadBranchTransfersData()">Apply</button>
                </div>
                <div class="table-container" style="max-height: calc(100vh - 320px); overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 10;">
                            <tr>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Document #</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Date</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Status</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">From (Supplying)</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">To (Receiving)</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Total units</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Created by</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="branchTransfersTableBody">
                            <tr><td colspan="8" style="padding: 2rem; text-align: center;"><div class="spinner"></div> Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function renderBranchTransferCreatePage() {
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-truck-loading"></i> Create Branch Transfer</h3>
                <button class="btn btn-outline" onclick="if(window.showBranchTransfersList) window.showBranchTransfersList()"><i class="fas fa-arrow-left"></i> Back to list</button>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <p style="margin-bottom: 1rem; color: var(--text-secondary);">Create a transfer from this branch (supplying) to receiving branch. Cost is set on Complete (FEFO).</p>
                <div id="branchTransferCreateFormWrap"><span style="color: var(--text-secondary);">Loading...</span></div>
                <div id="branchTransferTableMount" style="margin-top: 1rem;"></div>
                <div style="margin-top: 1rem;"><button class="btn btn-primary" id="branchTransferSaveDraftBtn" onclick="if(window.saveBranchTransferDraft) window.saveBranchTransferDraft()"><i class="fas fa-save"></i> Save as draft</button> <button class="btn btn-outline" onclick="if(window.showBranchTransfersList) window.showBranchTransfersList()">Cancel</button></div>
            </div>
        </div>
    `;
}

function renderBranchTransferViewPage() {
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-truck-loading"></i> Branch Transfer</h3>
                <button class="btn btn-outline" onclick="if(window.showBranchTransfersList) window.showBranchTransfersList()"><i class="fas fa-arrow-left"></i> Back to list</button>
            </div>
            <div class="card-body" style="padding: 1.5rem;" id="branchTransferViewContent">
                <div style="text-align: center; padding: 2rem;"><div class="spinner"></div> Loading...</div>
            </div>
        </div>
    `;
}

function renderBranchReceiptsSubPage() {
    if (branchReceiptsView === 'view') return renderBranchReceiptViewPage();
    const today = new Date().toISOString().split('T')[0];
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-clipboard-check"></i> Branch Receipts</h3>
                <div id="branchReceiptsHeaderButtons">
                    <span style="color: var(--text-secondary); font-size: 0.875rem;">Loading...</span>
                </div>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
                    <label>From</label>
                    <input type="date" id="branchReceiptsDateFrom" class="form-input" value="${today}" style="width: 140px;">
                    <label>To</label>
                    <input type="date" id="branchReceiptsDateTo" class="form-input" value="${today}" style="width: 140px;">
                    <select id="branchReceiptsStatus" class="form-input" style="width: 140px;">
                        <option value="">All</option>
                        <option value="PENDING">Pending</option>
                        <option value="RECEIVED">Received</option>
                    </select>
                    <button class="btn btn-primary" onclick="if(window.loadBranchReceiptsData) window.loadBranchReceiptsData()">Apply</button>
                </div>
                <div class="table-container" style="max-height: calc(100vh - 320px); overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 10;">
                            <tr>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Document #</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Date</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Status</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Receiving branch</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Total units</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="branchReceiptsTableBody">
                            <tr><td colspan="6" style="padding: 2rem; text-align: center;"><div class="spinner"></div> Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function renderBranchReceiptViewPage() {
    return `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-clipboard-check"></i> Branch Receipt</h3>
                <button class="btn btn-outline" onclick="if(window.showBranchReceiptsList) window.showBranchReceiptsList()"><i class="fas fa-arrow-left"></i> Back to list</button>
            </div>
            <div class="card-body" style="padding: 1.5rem;" id="branchReceiptViewContent">
                <div style="text-align: center; padding: 2rem;"><div class="spinner"></div> Loading...</div>
            </div>
        </div>
    `;
}

async function loadBranchOrdersData() {
    const tbody = document.getElementById('branchOrdersTableBody');
    if (!tbody) return;
    try {
        const statusFilter = document.getElementById('branchOrdersStatus');
        const params = {};
        if (statusFilter && statusFilter.value) params.status = statusFilter.value;
        if (CONFIG.BRANCH_ID) params.ordering_branch_id = CONFIG.BRANCH_ID;
        const list = await API.branchInventory.getOrders(params);
        branchOrdersList = Array.isArray(list) ? list : [];
        const fromEl = document.getElementById('branchOrdersDateFrom');
        const toEl = document.getElementById('branchOrdersDateTo');
        const fromDate = fromEl ? fromEl.value : null;
        const toDate = toEl ? toEl.value : null;
        let filtered = branchOrdersList;
        if (fromDate || toDate) {
            filtered = branchOrdersList.filter(o => {
                const d = (o.created_at || '').split('T')[0];
                if (fromDate && d < fromDate) return false;
                if (toDate && d > toDate) return false;
                return true;
            });
        }
        const totalUnits = (order) => (order.lines || []).reduce((sum, l) => sum + parseFloat(l.quantity || 0), 0);
        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="padding: 2rem; text-align: center; color: var(--text-secondary);">No branch orders found.</td></tr>';
            return;
        }
        tbody.innerHTML = filtered.map(o => {
            const status = o.status || 'DRAFT';
            const badge = status === 'BATCHED' ? 'badge-success' : 'badge-warning';
            const units = totalUnits(o);
            return `<tr style="cursor: pointer;" onclick="if(window.openBranchOrderView) window.openBranchOrderView('${o.id}')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(o.order_number || o.id).toString().substring(0, 20)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(o.created_at)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${badge}">${status}</span></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(o.ordering_branch_name || '—')}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(o.supplying_branch_name || '—')}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${units}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">—</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline btn-sm" onclick="event.stopPropagation(); if(window.openBranchOrderView) window.openBranchOrderView('${o.id}')"><i class="fas fa-eye"></i></button>
                </td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('loadBranchOrdersData', e);
        tbody.innerHTML = '<tr><td colspan="8" style="padding: 2rem; text-align: center; color: var(--danger-color);">' + (e.message || 'Failed to load') + '</td></tr>';
    }
}

async function loadBranchTransfersData() {
    const tbody = document.getElementById('branchTransfersTableBody');
    if (!tbody) return;
    const headerBtns = document.getElementById('branchTransfersHeaderButtons');
    try {
        await getBranchSettingsForCurrentBranch();
        if (headerBtns) {
            const allowManual = (branchSettingsCache && branchSettingsCache.allow_manual_transfer !== false);
            headerBtns.innerHTML = allowManual
                ? '<button class="btn btn-primary" onclick="if(window.openBranchTransferCreate) window.openBranchTransferCreate()"><i class="fas fa-plus"></i> New Transfer</button>'
                : '<span style="color: var(--text-secondary); font-size: 0.875rem;">Create from Pending Branch Orders only</span>';
        }
        const params = {};
        const statusFilter = document.getElementById('branchTransfersStatus');
        if (statusFilter && statusFilter.value) params.status = statusFilter.value;
        if (CONFIG.BRANCH_ID) params.supplying_branch_id = CONFIG.BRANCH_ID;
        const list = await API.branchInventory.getTransfers(params);
        branchTransfersList = Array.isArray(list) ? list : [];
        const fromEl = document.getElementById('branchTransfersDateFrom');
        const toEl = document.getElementById('branchTransfersDateTo');
        const fromDate = fromEl ? fromEl.value : null;
        const toDate = toEl ? toEl.value : null;
        let filtered = branchTransfersList;
        if (fromDate || toDate) {
            filtered = branchTransfersList.filter(t => {
                const d = (t.created_at || '').split('T')[0];
                if (fromDate && d < fromDate) return false;
                if (toDate && d > toDate) return false;
                return true;
            });
        }
        const totalUnits = (t) => (t.lines || []).reduce((sum, l) => sum + parseFloat(l.quantity || 0), 0);
        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="padding: 2rem; text-align: center; color: var(--text-secondary);">No branch transfers found.</td></tr>';
            return;
        }
        tbody.innerHTML = filtered.map(t => {
            const status = t.status || 'DRAFT';
            const badge = status === 'COMPLETED' ? 'badge-success' : 'badge-warning';
            const units = totalUnits(t);
            return `<tr style="cursor: pointer;" onclick="if(window.openBranchTransferView) window.openBranchTransferView('${t.id}')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(t.transfer_number || t.id).toString().substring(0, 20)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(t.created_at)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${badge}">${status}</span></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(t.supplying_branch_name || '—')}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(t.receiving_branch_name || '—')}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${units}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">—</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline btn-sm" onclick="event.stopPropagation(); if(window.openBranchTransferView) window.openBranchTransferView('${t.id}')"><i class="fas fa-eye"></i></button>
                </td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('loadBranchTransfersData', e);
        tbody.innerHTML = '<tr><td colspan="8" style="padding: 2rem; text-align: center; color: var(--danger-color);">' + (e.message || 'Failed to load') + '</td></tr>';
        if (headerBtns) headerBtns.innerHTML = '';
    }
}

async function loadBranchReceiptsData() {
    const tbody = document.getElementById('branchReceiptsTableBody');
    if (!tbody) return;
    const headerBtns = document.getElementById('branchReceiptsHeaderButtons');
    try {
        await getBranchSettingsForCurrentBranch();
        if (headerBtns) {
            const allowManual = (branchSettingsCache && branchSettingsCache.allow_manual_receipt !== false);
            headerBtns.innerHTML = allowManual
                ? '<button class="btn btn-primary" onclick="if(window.openBranchReceiptCreate) window.openBranchReceiptCreate()"><i class="fas fa-plus"></i> New Receipt</button>'
                : '<span style="color: var(--text-secondary); font-size: 0.875rem;">Create from Pending Transfers only</span>';
        }
        const params = {};
        if (CONFIG.BRANCH_ID) params.receiving_branch_id = CONFIG.BRANCH_ID;
        const statusFilter = document.getElementById('branchReceiptsStatus');
        if (statusFilter && statusFilter.value) params.status = statusFilter.value;
        const list = await API.branchInventory.getReceipts(params);
        branchReceiptsList = Array.isArray(list) ? list : [];
        const fromEl = document.getElementById('branchReceiptsDateFrom');
        const toEl = document.getElementById('branchReceiptsDateTo');
        const fromDate = fromEl ? fromEl.value : null;
        const toDate = toEl ? toEl.value : null;
        let filtered = branchReceiptsList;
        if (fromDate || toDate) {
            filtered = branchReceiptsList.filter(r => {
                const d = (r.created_at || '').split('T')[0];
                if (fromDate && d < fromDate) return false;
                if (toDate && d > toDate) return false;
                return true;
            });
        }
        const totalUnits = (r) => (r.lines || []).reduce((sum, l) => sum + parseFloat(l.quantity || 0), 0);
        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--text-secondary);">No branch receipts found.</td></tr>';
            return;
        }
        tbody.innerHTML = filtered.map(r => {
            const status = r.status || 'PENDING';
            const badge = status === 'RECEIVED' ? 'badge-success' : 'badge-warning';
            const units = totalUnits(r);
            return `<tr style="cursor: pointer;" onclick="if(window.openBranchReceiptView) window.openBranchReceiptView('${r.id}')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(r.receipt_number || r.id).toString().substring(0, 20)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(r.created_at)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${badge}">${status}</span></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${(r.receiving_branch_name || '—')}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${units}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline btn-sm" onclick="event.stopPropagation(); if(window.openBranchReceiptView) window.openBranchReceiptView('${r.id}')"><i class="fas fa-eye"></i></button>
                </td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('loadBranchReceiptsData', e);
        tbody.innerHTML = '<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--danger-color);">' + (e.message || 'Failed to load') + '</td></tr>';
        if (headerBtns) headerBtns.innerHTML = '';
    }
}

let branchOrderTableInstance = null;

function showBranchOrdersList() {
    branchOrdersView = 'list';
    branchOrderViewId = null;
    renderInventoryPage();
}

function openBranchOrderCreate() {
    branchOrdersView = 'create';
    // Full-page create: re-render entire inventory area so create form is main content (no modal)
    renderInventoryPage();
}

async function initBranchOrderCreatePage() {
    var orderingNameEl = document.getElementById('branchOrderOrderingBranchName');
    var supplyingWrap = document.getElementById('branchOrderSupplyingBranchWrap');
    var mount = document.getElementById('branchOrderTableMount');
    if (!mount || !supplyingWrap) return;
    try {
        var branches = await API.branch.list(CONFIG.COMPANY_ID);
        var currentId = CONFIG.BRANCH_ID;
        var currentBranch = branches.find(function (b) { return b.id === currentId; });
        currentBranchName = currentBranch ? (currentBranch.name || 'Current branch') : 'Current branch';
        if (orderingNameEl) orderingNameEl.textContent = currentBranchName;
        var supplyingBranches = branches.filter(function (b) { return b.id !== currentId; });
        var supplyingOpts = supplyingBranches.map(function (b) {
            return '<option value="' + b.id + '">' + (typeof escapeHtml === 'function' ? escapeHtml(b.name) : b.name) + '</option>';
        }).join('');
        supplyingWrap.innerHTML = '<select id="branchOrderSupplyingBranch" class="form-input" style="width: 100%; max-width: 400px;"><option value="">— Select supplying branch —</option>' + supplyingOpts + '</select>';
        mount.innerHTML = '';
        branchOrderTableInstance = new window.TransactionItemsTable({
            mountEl: mount,
            mode: 'branch_order',
            useAddRow: true,
            canEdit: true,
            items: [],
            onAddItem: function (item) {
                if (!item || !item.item_id) return;
                var items = branchOrderTableInstance.getItems().filter(function (i) { return i.item_id && !i.is_empty; });
                var existing = items.filter(function (i) { return i.item_id === item.item_id && (i.unit_name || '') === (item.unit_name || ''); });
                if (existing.length) {
                    existing[0].quantity = (parseFloat(existing[0].quantity) || 0) + (parseFloat(item.quantity) || 1);
                } else {
                    items.push({ item_id: item.item_id, item_name: item.item_name, item_code: item.item_code, item_sku: item.item_sku, unit_name: item.unit_name || '', quantity: item.quantity || 1, unit_price: 0, total: 0, is_empty: false });
                }
                branchOrderTableInstance.setItems(items);
                branchOrderTableInstance.addRowItem = null;
                branchOrderTableInstance.editingRowIndex = null;
                branchOrderTableInstance.render();
                branchOrderTableInstance.attachEventListeners();
            },
            onItemCreate: function (query, rowIndex, callback) {
                window._transactionItemCreateCallback = callback;
                window._transactionItemCreateRowIndex = rowIndex;
                if (query) window._transactionItemCreateName = query;
                if (typeof showAddItemModal === 'function') {
                    showAddItemModal();
                    setTimeout(function () {
                        var nameInput = document.querySelector('#itemForm input[name="name"]');
                        if (nameInput && query) nameInput.value = query;
                    }, 100);
                } else {
                    if (window.showToast) showToast('To create item, go to Items page', 'info');
                }
            }
        });
    } catch (e) {
        console.error('initBranchOrderCreatePage', e);
        if (orderingNameEl) orderingNameEl.textContent = 'Current branch';
        supplyingWrap.innerHTML = '<span style="color: var(--danger-color);">Failed to load branches.</span>';
        if (window.showToast) showToast(e.message || 'Failed to load form', 'error');
    }
}

async function saveBranchOrderDraft() {
    var orderingId = CONFIG.BRANCH_ID;
    var supplyingSelect = document.getElementById('branchOrderSupplyingBranch');
    var supplyingId = supplyingSelect ? supplyingSelect.value : null;
    if (!orderingId) {
        if (window.showToast) showToast('Current branch required', 'error');
        return;
    }
    if (!supplyingId) {
        if (window.showToast) showToast('Select supplying branch', 'error');
        return;
    }
    if (orderingId === supplyingId) {
        if (window.showToast) showToast('Ordering and supplying branch must be different', 'error');
        return;
    }
    var items = branchOrderTableInstance ? branchOrderTableInstance.getItems() : [];
    var valid = items.filter(function (i) { return i.item_id && (parseFloat(i.quantity) || 0) > 0; });
    if (valid.length === 0) {
        if (window.showToast) showToast('Add at least one item with quantity', 'error');
        return;
    }
    var lines = valid.map(function (i) {
        return { item_id: i.item_id, unit_name: i.unit_name || 'piece', quantity: parseFloat(i.quantity) || 1 };
    });
    try {
        await API.branchInventory.createOrder({ ordering_branch_id: orderingId, supplying_branch_id: supplyingId, lines: lines });
        if (window.showToast) showToast('Branch order saved as draft', 'success');
        showBranchOrdersList();
    } catch (e) {
        console.error('saveBranchOrderDraft', e);
        if (window.showToast) showToast(e.message || (e.detail && (typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail))) || 'Failed to save', 'error');
    }
}

function openBranchOrderView(id) {
    branchOrdersView = 'view';
    branchOrderViewId = id;
    renderInventoryPage();
}

async function loadBranchOrderViewPage(orderId) {
    var container = document.getElementById('branchOrderViewContent');
    if (!container) return;
    try {
        var order = await API.branchInventory.getOrder(orderId);
        var status = order.status || 'DRAFT';
        var canBatch = status === 'DRAFT' && order.lines && order.lines.length > 0;
        var rows = (order.lines || []).map(function (l) {
            return '<tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.item_name || '—') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.unit_name || '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">' + (l.quantity != null ? l.quantity : '—') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">' + (l.fulfilled_qty != null ? l.fulfilled_qty : '0') + '</td></tr>';
        }).join('');
        container.innerHTML =
            '<div style="margin-bottom: 1rem;">' +
            '<p><strong>Document:</strong> ' + (order.order_number || order.id) + ' &nbsp; <span class="badge ' + (status === 'BATCHED' ? 'badge-success' : 'badge-warning') + '">' + status + '</span></p>' +
            '<p><strong>From (ordering):</strong> ' + (order.ordering_branch_name || '—') + ' &nbsp; <strong>To (supplying):</strong> ' + (order.supplying_branch_name || '—') + '</p>' +
            '</div>' +
            '<div class="table-container" style="max-height: 40vh;"><table style="width: 100%; border-collapse: collapse;">' +
            '<thead><tr><th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color);">Item</th><th>Unit</th><th style="text-align: right;">Qty</th><th style="text-align: right;">Fulfilled</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
            (canBatch ? '<div style="margin-top: 1rem;"><button class="btn btn-primary" id="branchOrderBatchBtn"><i class="fas fa-check-double"></i> Batch order</button></div>' : '');
        if (canBatch) document.getElementById('branchOrderBatchBtn').onclick = function () { batchBranchOrder(orderId); };
    } catch (e) {
        console.error('loadBranchOrderViewPage', e);
        container.innerHTML = '<div class="alert alert-danger">' + (e.message || 'Failed to load order') + '</div>';
        if (window.showToast) showToast(e.message || 'Failed to load order', 'error');
    }
}

async function batchBranchOrder(orderId) {
    try {
        await API.branchInventory.batchOrder(orderId);
        if (window.showToast) showToast('Order batched successfully. Items added to Order Book as Branch Order.', 'success');
        showBranchOrdersList();
    } catch (e) {
        console.error('batchBranchOrder', e);
        if (window.showToast) showToast(e.message || (e.detail && (typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail))) || 'Failed to batch', 'error');
    }
}

let branchTransferTableInstance = null;
let branchTransferFromOrderId = null;

function showBranchTransfersList() {
    branchTransfersView = 'list';
    branchTransferViewId = null;
    renderInventoryPage();
}

function openBranchTransferCreate() {
    branchTransfersView = 'create';
    branchTransferViewId = null;
    // Full-page create: re-render entire inventory area so create form is main content (no modal)
    renderInventoryPage();
}

async function initBranchTransferCreatePage() {
    var formWrap = document.getElementById('branchTransferCreateFormWrap');
    var mount = document.getElementById('branchTransferTableMount');
    if (!formWrap || !mount) return;
    try {
        await getBranchSettingsForCurrentBranch();
        var allowManual = branchSettingsCache && branchSettingsCache.allow_manual_transfer !== false;
        var supplyingBranchId = CONFIG.BRANCH_ID;
        if (!supplyingBranchId) {
            formWrap.innerHTML = '<p class="alert alert-warning">Select current branch first.</p>';
            return;
        }
        var pending = await API.branchInventory.getPendingOrdersForSupply(supplyingBranchId);
        pending = Array.isArray(pending) ? pending : [];
        var branches = await API.branch.list(CONFIG.COMPANY_ID);
        var receivingOpts = branches.filter(function (b) { return b.id !== supplyingBranchId; }).map(function (b) { return '<option value="' + b.id + '">' + (typeof escapeHtml === 'function' ? escapeHtml(b.name) : b.name) + '</option>'; }).join('');
        var orderOpts = '<option value="">-- Select order --</option>' + pending.map(function (o) {
            return '<option value="' + o.id + '">' + (o.order_number || o.id) + ' (to ' + (o.ordering_branch_name || '') + ')</option>';
        }).join('');
        formWrap.innerHTML =
            '<div class="form-group"><label class="form-label">Create from</label><select id="branchTransferSource" class="form-input" style="width: 100%; max-width: 400px;">' +
            '<option value="order">From Pending Branch Order</option>' + (allowManual ? '<option value="manual">Manual</option>' : '') +
            '</select></div>' +
            '<div id="branchTransferOrderGroup" class="form-group"><label class="form-label">Pending order</label><select id="branchTransferOrderId" class="form-input" style="width: 100%; max-width: 400px;">' + orderOpts + '</select></div>' +
            '<div id="branchTransferManualGroup" class="form-group" style="display: none;"><label class="form-label">Receiving branch</label><select id="branchTransferReceivingBranch" class="form-input" style="width: 100%; max-width: 400px;">' + receivingOpts + '</select></div>' +
            '<div class="form-group"><label class="form-label">Items</label></div>';
        branchTransferFromOrderId = null;
        document.getElementById('branchTransferSource').onchange = function () {
            var isOrder = this.value === 'order';
            document.getElementById('branchTransferOrderGroup').style.display = isOrder ? 'block' : 'none';
            document.getElementById('branchTransferManualGroup').style.display = isOrder ? 'none' : 'block';
            if (isOrder && document.getElementById('branchTransferOrderId')) document.getElementById('branchTransferOrderId').dispatchEvent(new Event('change'));
            else initBranchTransferTable([]);
        };
        document.getElementById('branchTransferOrderId').onchange = function () {
            var orderId = this.value;
            if (!orderId) { initBranchTransferTable([]); return; }
            API.branchInventory.getOrder(orderId).then(function (order) {
                branchTransferFromOrderId = orderId;
                var items = (order.lines || []).map(function (l) {
                    return { item_id: l.item_id, item_name: l.item_name, unit_name: l.unit_name || 'piece', quantity: parseFloat(l.quantity) || 1, unit_price: 0, total: 0, branch_order_line_id: l.id, is_empty: false };
                });
                initBranchTransferTable(items);
            }).catch(function (e) {
                if (window.showToast) showToast(e.message || 'Failed to load order', 'error');
                initBranchTransferTable([]);
            });
        };
        if (pending.length && document.getElementById('branchTransferOrderId')) document.getElementById('branchTransferOrderId').dispatchEvent(new Event('change'));
        else initBranchTransferTable([]);
    } catch (e) {
        console.error('initBranchTransferCreatePage', e);
        formWrap.innerHTML = '<p class="alert alert-danger">' + (e.message || 'Failed to load') + '</p>';
        if (window.showToast) showToast(e.message || 'Failed to open form', 'error');
    }
}

function initBranchTransferTable(items) {
    var mount = document.getElementById('branchTransferTableMount');
    if (!mount) return;
    mount.innerHTML = '';
    branchTransferTableInstance = new window.TransactionItemsTable({
        mountEl: mount,
        mode: 'branch_transfer',
        useAddRow: true,
        canEdit: true,
        items: items,
        onAddItem: function (item) {
            if (!item || !item.item_id) return;
            var list = branchTransferTableInstance.getItems().filter(function (i) { return i.item_id && !i.is_empty; });
            var existing = list.filter(function (i) { return i.item_id === item.item_id && (i.unit_name || '') === (item.unit_name || ''); });
            if (existing.length) existing[0].quantity = (parseFloat(existing[0].quantity) || 0) + (parseFloat(item.quantity) || 1);
            else list.push({ item_id: item.item_id, item_name: item.item_name, item_code: item.item_code, unit_name: item.unit_name || '', quantity: item.quantity || 1, unit_price: 0, total: 0, is_empty: false });
            branchTransferTableInstance.setItems(list);
            branchTransferTableInstance.addRowItem = null;
            branchTransferTableInstance.editingRowIndex = null;
            branchTransferTableInstance.render();
            branchTransferTableInstance.attachEventListeners();
        },
        onItemCreate: function (query, rowIndex, callback) {
            window._transactionItemCreateCallback = callback;
            if (typeof showAddItemModal === 'function') showAddItemModal();
            else if (window.showToast) showToast('Create item from Items page', 'info');
        }
    });
}

async function saveBranchTransferDraft() {
    var supplyingId = CONFIG.BRANCH_ID;
    if (!supplyingId) { if (window.showToast) showToast('Current branch required', 'error'); return; }
    var receivingId;
    var orderId = null;
    if (document.getElementById('branchTransferSource').value === 'order') {
        orderId = document.getElementById('branchTransferOrderId').value;
        if (!orderId) { if (window.showToast) showToast('Select a pending order', 'error'); return; }
        var order = await API.branchInventory.getOrder(orderId);
        receivingId = order.ordering_branch_id;
    } else {
        receivingId = document.getElementById('branchTransferReceivingBranch').value;
        if (!receivingId || receivingId === supplyingId) {
            if (window.showToast) showToast('Select a different receiving branch', 'error');
            return;
        }
    }
    var items = branchTransferTableInstance ? branchTransferTableInstance.getItems() : [];
    var valid = items.filter(function (i) { return i.item_id && (parseFloat(i.quantity) || 0) > 0; });
    if (valid.length === 0) { if (window.showToast) showToast('Add at least one item', 'error'); return; }
    var lines = valid.map(function (i) {
        return {
            branch_order_line_id: i.branch_order_line_id || null,
            item_id: i.item_id,
            unit_name: i.unit_name || 'piece',
            quantity: parseFloat(i.quantity) || 1,
            unit_cost: parseFloat(i.unit_price) || 0
        };
    });
    try {
        await API.branchInventory.createTransfer({
            supplying_branch_id: supplyingId,
            receiving_branch_id: receivingId,
            branch_order_id: orderId || undefined,
            lines: lines
        });
        if (window.showToast) showToast('Transfer saved as draft', 'success');
        showBranchTransfersList();
    } catch (e) {
        console.error('saveBranchTransferDraft', e);
        if (window.showToast) showToast(e.message || (e.detail && (typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail))) || 'Failed to save', 'error');
    }
}

function openBranchTransferView(id) {
    branchTransfersView = 'view';
    branchTransferViewId = id;
    renderInventoryPage();
}

async function loadBranchTransferViewPage(transferId) {
    var container = document.getElementById('branchTransferViewContent');
    if (!container) return;
    try {
        var transfer = await API.branchInventory.getTransfer(transferId);
        var status = transfer.status || 'DRAFT';
        var canComplete = status === 'DRAFT' && transfer.lines && transfer.lines.length > 0;
        var rows = (transfer.lines || []).map(function (l) {
            return '<tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.item_name || '—') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.unit_name || '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">' + (l.quantity != null ? l.quantity : '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">' + (l.unit_cost != null ? l.unit_cost : '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.batch_number || '—') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.expiry_date || '—') + '</td></tr>';
        }).join('');
        container.innerHTML =
            '<div style="margin-bottom: 1rem;">' +
            '<p><strong>Document:</strong> ' + (transfer.transfer_number || transfer.id) + ' &nbsp; <span class="badge ' + (status === 'COMPLETED' ? 'badge-success' : 'badge-warning') + '">' + status + '</span></p>' +
            '<p><strong>From:</strong> ' + (transfer.supplying_branch_name || '—') + ' &nbsp; <strong>To:</strong> ' + (transfer.receiving_branch_name || '—') + '</p></div>' +
            '<div class="table-container" style="max-height: 40vh;"><table style="width: 100%; border-collapse: collapse;">' +
            '<thead><tr><th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color);">Item</th><th>Unit</th><th style="text-align: right;">Qty</th><th style="text-align: right;">Cost</th><th>Batch</th><th>Expiry</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
            (canComplete ? '<div style="margin-top: 1rem;"><button class="btn btn-primary" id="branchTransferCompleteBtn"><i class="fas fa-check-double"></i> Complete transfer</button></div>' : '');
        if (canComplete) document.getElementById('branchTransferCompleteBtn').onclick = function () { completeBranchTransfer(transferId); };
    } catch (e) {
        console.error('loadBranchTransferViewPage', e);
        container.innerHTML = '<div class="alert alert-danger">' + (e.message || 'Failed to load transfer') + '</div>';
        if (window.showToast) showToast(e.message || 'Failed to load transfer', 'error');
    }
}

async function completeBranchTransfer(transferId) {
    try {
        await API.branchInventory.completeTransfer(transferId);
        if (window.showToast) showToast('Transfer completed; stock deducted and receipt created for receiving branch.', 'success');
        showBranchTransfersList();
    } catch (e) {
        console.error('completeBranchTransfer', e);
        if (window.showToast) showToast(e.message || (e.detail && (typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail))) || 'Failed to complete', 'error');
    }
}

function openBranchReceiptCreate() {
    if (window.showToast) showToast('Receipts are created when a transfer is completed. Open a pending receipt below to confirm receipt.', 'info');
}

function showBranchReceiptsList() {
    branchReceiptsView = 'list';
    branchReceiptViewId = null;
    renderInventoryPage();
}

function openBranchReceiptView(id) {
    branchReceiptsView = 'view';
    branchReceiptViewId = id;
    renderInventoryPage();
}

async function loadBranchReceiptViewPage(receiptId) {
    var container = document.getElementById('branchReceiptViewContent');
    if (!container) return;
    try {
        var receipt = await API.branchInventory.getReceipt(receiptId);
        var status = receipt.status || 'PENDING';
        var canReceive = status === 'PENDING' && receipt.lines && receipt.lines.length > 0;
        var rows = (receipt.lines || []).map(function (l) {
            return '<tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.item_name || '—') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.unit_name || '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">' + (l.quantity != null ? l.quantity : '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">' + (l.unit_cost != null ? l.unit_cost : '') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.batch_number || '—') + '</td><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + (l.expiry_date || '—') + '</td></tr>';
        }).join('');
        container.innerHTML =
            '<div style="margin-bottom: 1rem;">' +
            '<p><strong>Document:</strong> ' + (receipt.receipt_number || receipt.id) + ' &nbsp; <span class="badge ' + (status === 'RECEIVED' ? 'badge-success' : 'badge-warning') + '">' + status + '</span></p>' +
            '<p><strong>Receiving branch:</strong> ' + (receipt.receiving_branch_name || '—') + '</p></div>' +
            '<div class="table-container" style="max-height: 40vh;"><table style="width: 100%; border-collapse: collapse;">' +
            '<thead><tr><th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color);">Item</th><th>Unit</th><th style="text-align: right;">Qty</th><th style="text-align: right;">Cost</th><th>Batch</th><th>Expiry</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
            (canReceive ? '<div style="margin-top: 1rem;"><button class="btn btn-primary" id="branchReceiptConfirmBtn"><i class="fas fa-check"></i> Confirm receipt</button></div>' : '');
        if (canReceive) document.getElementById('branchReceiptConfirmBtn').onclick = function () { confirmBranchReceipt(receiptId); };
    } catch (e) {
        console.error('loadBranchReceiptViewPage', e);
        container.innerHTML = '<div class="alert alert-danger">' + (e.message || 'Failed to load receipt') + '</div>';
        if (window.showToast) showToast(e.message || 'Failed to load receipt', 'error');
    }
}

async function confirmBranchReceipt(receiptId) {
    try {
        await API.branchInventory.receiveReceipt(receiptId);
        if (window.showToast) showToast('Receipt confirmed; stock added to this branch.', 'success');
        showBranchReceiptsList();
    } catch (e) {
        console.error('confirmBranchReceipt', e);
        if (window.showToast) showToast(e.message || (e.detail && (typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail))) || 'Failed to confirm', 'error');
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
        const currentStockDisplay = (data && data.stock_display) ? String(data.stock_display) : (data && data.current_stock != null ? String(data.current_stock) + ' ' + (data.base_unit || '') : '—');

        const content = `
            <div style="margin-bottom: 1rem; padding: 0.75rem; background: var(--bg-secondary, #f5f5f5); border-radius: 6px;">
                <strong>${escapeHtml(itemName)}</strong>
                <div style="margin-top: 0.5rem; font-size: 0.9rem; color: var(--text-secondary, #666);">Current stock: <strong>${escapeHtml(currentStockDisplay)}</strong> — adjustments add to or reduce this balance.</div>
            </div>
            <div class="form-group">
                <label>Unit (Box, Packet, Sachet, etc.)</label>
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
            <div class="form-group" id="adjustBatchGroup">
                <label>Batch / Lot number <span id="adjustBatchRequired" style="color: var(--danger-color, #dc3545);">*</span></label>
                <input type="text" id="adjustStockBatch" class="form-input" maxlength="200" placeholder="e.g. BATCH-2024-001">
            </div>
            <div class="form-group" id="adjustExpiryGroup">
                <label>Expiry date <span id="adjustExpiryRequired" style="color: var(--danger-color, #dc3545);">*</span></label>
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
        // When Add is selected, batch and expiry are required
        const directionRadios = document.querySelectorAll('input[name="adjustDirection"]');
        const batchInput = document.getElementById('adjustStockBatch');
        const expiryInput = document.getElementById('adjustStockExpiry');
        const batchReq = document.getElementById('adjustBatchRequired');
        const expiryReq = document.getElementById('adjustExpiryRequired');
        function toggleAddRequired() {
            const addChecked = document.querySelector('input[name="adjustDirection"][value="add"]:checked');
            const isAdd = !!addChecked;
            if (batchInput) batchInput.required = isAdd;
            if (expiryInput) expiryInput.required = isAdd;
            if (batchReq) batchReq.style.visibility = isAdd ? 'visible' : 'hidden';
            if (expiryReq) expiryReq.style.visibility = isAdd ? 'visible' : 'hidden';
        }
        toggleAddRequired();
        directionRadios.forEach(function (r) {
            if (r) r.addEventListener('change', toggleAddRequired);
        });
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
    const batchEl = document.getElementById('adjustStockBatch');
    const expiryEl = document.getElementById('adjustStockExpiry');
    if (dir === 'add') {
        if (!batchEl || !batchEl.value.trim()) {
            if (typeof showToast === 'function') showToast('Batch number is required when adding stock.', 'warning');
            else alert('Batch number is required when adding stock.');
            return;
        }
        if (!expiryEl || !expiryEl.value) {
            if (typeof showToast === 'function') showToast('Expiry date is required when adding stock.', 'warning');
            else alert('Expiry date is required when adding stock.');
            return;
        }
    }
    const unit_cost = costEl ? parseFloat(costEl.value) : null;
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
        const res = await API.items.adjustStock(itemId, payload);
        if (typeof closeModal === 'function') closeModal();
        const msg = (res && res.message) ? res.message : 'Stock adjusted successfully.';
        if (typeof showToast === 'function') showToast(msg, 'success');
        else alert(msg);
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
    return `
        <div class="batch-tracking-page">
            <h2 style="margin-bottom: 1rem;"><i class="fas fa-layer-group"></i> Batch Tracking</h2>
            <p style="color: var(--text-secondary); margin-bottom: 1rem;">View batch movement by item and batch. Select date range, item, and batch, then click Apply. Export to CSV or PDF below the report.</p>
            <div id="inventoryBatchTrackingContainer" class="item-movement-report-wrapper"></div>
        </div>
    `;
}

function renderExpiryReportSubPage() {
    return '<div><h2>Expiry Report</h2><p>Expiry report functionality coming soon...</p></div>';
}

function renderItemMovementSubPage() {
    return '<div id="inventoryMovementContainer" class="item-movement-report-wrapper"></div>';
}

function renderCurrentStockSubPage() {
    const branchId = getBranchIdForStock();
    const branchIdStr = branchId ? (typeof branchId === 'string' ? branchId : branchId.id || branchId) : '';
    const today = new Date().toISOString().slice(0, 10);
    return `
        <div>
            <h2 style="margin-bottom: 1rem;"><i class="fas fa-chart-bar"></i> Current Stock / Valuation</h2>
            <p style="color: var(--text-secondary); margin-bottom: 1rem;">Stock on hand for the selected branch. Choose options and click Apply to load.</p>
            <div class="card" style="margin-bottom: 1.5rem;">
                <div style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end;">
                    <div class="form-group" style="margin-bottom: 0;">
                        <label>Branch</label>
                        <select id="currentStockBranch" class="form-input" style="min-width: 200px;">
                            <option value="">Loading branches…</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label>Date (snapshot)</label>
                        <input type="date" id="currentStockDate" class="form-input" value="${today}">
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label>Valuation</label>
                        <select id="currentStockValuation" class="form-input">
                            <option value="last_cost">Last unit cost</option>
                            <option value="selling_price">Selling price</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label>Items</label>
                        <select id="currentStockFilter" class="form-input">
                            <option value="true">With stock only</option>
                            <option value="false">All items</option>
                        </select>
                    </div>
                    <button type="button" class="btn btn-primary" id="currentStockApplyBtn"><i class="fas fa-check"></i> Apply</button>
                    <div style="display: flex; gap: 0.5rem; align-items: center; margin-left: auto;">
                        <span style="color: var(--text-secondary); font-size: 0.875rem;">Export</span>
                        <button type="button" class="btn btn-outline btn-sm" id="currentStockExportCsvBar" title="Export as CSV"><i class="fas fa-file-csv"></i> CSV</button>
                        <button type="button" class="btn btn-outline btn-sm" id="currentStockExportExcelBar" title="Export for Excel"><i class="fas fa-file-excel"></i> Excel</button>
                        <button type="button" class="btn btn-outline btn-sm" id="currentStockPrintBar" title="Print or save as PDF"><i class="fas fa-print"></i> Print / PDF</button>
                    </div>
                </div>
            </div>
            <div id="currentStockContainer">
                <p style="text-align: center; color: var(--text-secondary);">Select branch and click Apply to load stock.</p>
            </div>
        </div>
    `;
}

async function loadBatchTrackingData() {
    const container = document.getElementById('inventoryBatchTrackingContainer');
    if (!container) return;
    const branchId = typeof getBranchIdForStock === 'function' ? getBranchIdForStock() : null;
    if (!branchId) {
        container.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> Select a branch first (top bar or Settings → Branches → Set as Current).</div>';
        return;
    }
    if (typeof window.renderMovementReportInto === 'function') {
        window.renderMovementReportInto(container, 'batch');
    } else {
        container.innerHTML = '<div class="alert alert-info">Batch tracking report is loading. If this message persists, refresh the page.</div>';
    }
}

async function loadExpiryReportData() {
    // TODO
}

async function loadItemMovementData() {
    const container = document.getElementById('inventoryMovementContainer');
    if (container && typeof window.renderItemMovementReportInto === 'function') {
        window.renderItemMovementReportInto(container);
    }
}

async function loadCurrentStockData() {
    const container = document.getElementById('currentStockContainer');
    const branchSelect = document.getElementById('currentStockBranch');
    const applyBtn = document.getElementById('currentStockApplyBtn');
    if (!container) return;

    if (branchSelect && branchSelect.options.length === 1 && branchSelect.options[0].value === '') {
        try {
            if (!CONFIG.COMPANY_ID) {
                branchSelect.innerHTML = '<option value="">No company selected</option>';
            } else {
                const branches = await API.branch.list(CONFIG.COMPANY_ID);
                const sessionBranchId = getBranchIdForStock();
                const sid = sessionBranchId ? (typeof sessionBranchId === 'string' ? sessionBranchId : (sessionBranchId.id || sessionBranchId)) : null;
                branchSelect.innerHTML = (branches || []).map(function (b) {
                    const bid = b.id || b.branch_id;
                    return '<option value="' + (bid || '') + '"' + (sid && String(bid) === String(sid) ? ' selected' : '') + '>' + escapeHtml(b.name || b.branch_name || 'Branch') + '</option>';
                }).join('') || '<option value="">No branches</option>';
            }
        } catch (e) {
            console.warn('Failed to load branches for Current Stock:', e);
            branchSelect.innerHTML = '<option value="">Failed to load branches</option>';
        }
    }

    if (applyBtn && !applyBtn._bound) {
        applyBtn._bound = true;
        applyBtn.addEventListener('click', function () { runCurrentStockValuation(); });
    }
    var csvBar = document.getElementById('currentStockExportCsvBar');
    var excelBar = document.getElementById('currentStockExportExcelBar');
    var printBar = document.getElementById('currentStockPrintBar');
    if (csvBar) csvBar.onclick = function () { exportCurrentStockCsv(); };
    if (excelBar) excelBar.onclick = function () { exportCurrentStockExcel(); };
    if (printBar) printBar.onclick = function () { printCurrentStock(); };

    var bid = branchSelect && branchSelect.value ? branchSelect.value : getBranchIdForStock();
    if (bid) {
        bid = typeof bid === 'string' ? bid : (bid && (bid.id || bid));
        runCurrentStockValuation(bid);
    } else {
        container.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> Select a branch and click Apply to load current stock.</div>';
    }
}

async function runCurrentStockValuation(overrideBranchId) {
    const container = document.getElementById('currentStockContainer');
    const branchSelect = document.getElementById('currentStockBranch');
    const dateEl = document.getElementById('currentStockDate');
    const valuationEl = document.getElementById('currentStockValuation');
    const filterEl = document.getElementById('currentStockFilter');
    const applyBtn = document.getElementById('currentStockApplyBtn');
    if (!container) return;
    var branchId = overrideBranchId || (branchSelect && branchSelect.value);
    if (!branchId) {
        container.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> Select a branch and click Apply.</div>';
        return;
    }
    if (applyBtn) applyBtn.disabled = true;
    container.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div><p style="text-align: center; color: var(--text-secondary);">Loading…</p>';
    var useValuationApi = typeof API !== 'undefined' && API.inventory && typeof API.inventory.getValuation === 'function';
    try {
        if (useValuationApi) {
            var params = {
                branch_id: branchId,
                as_of_date: dateEl && dateEl.value ? dateEl.value : new Date().toISOString().slice(0, 10),
                valuation: valuationEl && valuationEl.value ? valuationEl.value : 'last_cost',
                stock_only: !(filterEl && filterEl.value === 'false')
            };
            var res = await API.inventory.getValuation(params);
            var rows = (res && res.rows) ? res.rows : [];
            var totalValue = (res && res.total_value != null) ? res.total_value : 0;
            var totalItems = (res && res.total_items != null) ? res.total_items : rows.length;
            if (rows.length === 0) {
                lastCurrentStockValuation = null;
                container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items match the criteria. Try "All items" or another branch.</p>';
            } else {
                lastCurrentStockValuation = {
                    rows: rows,
                    total_value: totalValue,
                    total_items: totalItems,
                    branch_name: (res && res.branch_name) ? res.branch_name : '',
                    as_of_date: (res && res.as_of_date) ? res.as_of_date : '',
                    valuation: (res && res.valuation) ? res.valuation : 'last_cost'
                };
                var tableRows = rows.map(function (row) {
                    return '<tr><td>' + escapeHtml(row.item_name || '—') + '</td><td>' + escapeHtml(row.stock_display || (formatNumber(row.stock) + ' ' + (row.base_unit || ''))) + '</td><td style="text-align: right;">' + formatNumber(row.unit_cost) + '</td><td style="text-align: right;">' + formatNumber(row.value) + '</td></tr>';
                }).join('');
                container.innerHTML =
                    '<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem;">' +
                    '<span style="color: var(--text-secondary); font-size: 0.875rem;">Export</span>' +
                    '<div>' +
                    '<button type="button" class="btn btn-outline btn-sm" id="currentStockExportCsv"><i class="fas fa-file-csv"></i> CSV</button> ' +
                    '<button type="button" class="btn btn-outline btn-sm" id="currentStockExportExcel"><i class="fas fa-file-excel"></i> Excel</button> ' +
                    '<button type="button" class="btn btn-outline btn-sm" id="currentStockPrint"><i class="fas fa-print"></i> Print / PDF</button>' +
                    '</div></div>' +
                    '<div class="table-container" style="max-height: 60vh; overflow-y: auto;" id="currentStockTableWrap">' +
                    '<table style="width: 100%; border-collapse: collapse;">' +
                    '<thead style="position: sticky; top: 0; background: white; z-index: 1;">' +
                    '<tr><th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>' +
                    '<th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Stock</th>' +
                    '<th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Unit cost</th>' +
                    '<th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Value</th></tr>' +
                    '</thead><tbody>' + tableRows + '</tbody></table></div>' +
                    '<p style="margin-top: 0.75rem; color: var(--text-secondary);">' + totalItems + ' item(s) · Total value: <strong>' + formatNumber(totalValue) + ' KES</strong></p>';
                var csvBtn = document.getElementById('currentStockExportCsv');
                var excelBtn = document.getElementById('currentStockExportExcel');
                var printBtn = document.getElementById('currentStockPrint');
                if (csvBtn) csvBtn.onclick = function () { exportCurrentStockCsv(); };
                if (excelBtn) excelBtn.onclick = function () { exportCurrentStockExcel(); };
                if (printBtn) printBtn.onclick = function () { printCurrentStock(); };
            }
        } else {
            var list = await API.inventory.getAllStock(branchId);
            if (!list || list.length === 0) {
                container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No stock on hand at this branch.</p>';
            } else {
                var simpleRows = list.map(function (row) {
                    return '<tr><td>' + escapeHtml(row.item_name || '—') + '</td><td style="text-align: right;">' + formatNumber(row.stock) + ' ' + escapeHtml(row.base_unit || '') + '</td></tr>';
                }).join('');
                container.innerHTML =
                    '<div class="table-container" style="max-height: 60vh; overflow-y: auto;">' +
                    '<table style="width: 100%; border-collapse: collapse;">' +
                    '<thead style="position: sticky; top: 0; background: white; z-index: 1;">' +
                    '<tr><th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>' +
                    '<th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Quantity</th></tr>' +
                    '</thead><tbody>' + simpleRows + '</tbody></table></div>' +
                    '<p style="margin-top: 0.75rem; color: var(--text-secondary);">' + list.length + ' item(s) with stock</p>';
            }
        }
    } catch (err) {
        console.error('Current stock valuation failed:', err);
        var msg = (err && (err.message || (err.detail && (typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail))))) || (typeof err === 'string' ? err : (err && typeof err === 'object' ? JSON.stringify(err) : String(err)));
        if (msg.indexOf('fetch') !== -1 || msg.indexOf('Network') !== -1) {
            msg += ' Please check if the backend server is running on ' + (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL ? CONFIG.API_BASE_URL : 'http://localhost:8000') + '.';
        }
        container.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Failed to load current stock. ' + escapeHtml(msg) + '</div>';
    } finally {
        if (applyBtn) applyBtn.disabled = false;
    }
}

// --- Current Stock export (CSV, Excel, Print/PDF) ---
function exportCurrentStockCsv() {
    if (!lastCurrentStockValuation || !lastCurrentStockValuation.rows || lastCurrentStockValuation.rows.length === 0) {
        if (typeof showToast === 'function') showToast('No data to export. Click Apply to load stock first.', 'warning');
        return;
    }
    var escapeCsv = function (v) {
        if (v == null) return '';
        var s = String(v);
        if (s.indexOf(',') >= 0 || s.indexOf('"') >= 0 || s.indexOf('\n') >= 0) return '"' + s.replace(/"/g, '""') + '"';
        return s;
    };
    var headers = ['Item', 'Stock', 'Unit cost', 'Value'];
    var rows = lastCurrentStockValuation.rows.map(function (r) {
        var stockD = (r.stock_display != null) ? r.stock_display : (formatNumber(r.stock) + ' ' + (r.base_unit || ''));
        return [r.item_name || '—', stockD, r.unit_cost, r.value].map(escapeCsv).join(',');
    });
    var csv = [headers.map(escapeCsv).join(','), rows.join('\n')].join('\n');
    var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'current-stock-' + (lastCurrentStockValuation.as_of_date || new Date().toISOString().slice(0, 10)) + '.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    if (typeof showToast === 'function') showToast('CSV exported.', 'success');
}

function exportCurrentStockExcel() {
    if (!lastCurrentStockValuation || !lastCurrentStockValuation.rows || lastCurrentStockValuation.rows.length === 0) {
        if (typeof showToast === 'function') showToast('No data to export. Click Apply to load stock first.', 'warning');
        return;
    }
    var escapeCsv = function (v) {
        if (v == null) return '';
        var s = String(v);
        if (s.indexOf(',') >= 0 || s.indexOf('"') >= 0 || s.indexOf('\n') >= 0) return '"' + s.replace(/"/g, '""') + '"';
        return s;
    };
    var headers = ['Item', 'Stock', 'Unit cost', 'Value'];
    var rows = lastCurrentStockValuation.rows.map(function (r) {
        var stockD = (r.stock_display != null) ? r.stock_display : (formatNumber(r.stock) + ' ' + (r.base_unit || ''));
        return [r.item_name || '—', stockD, r.unit_cost, r.value].map(escapeCsv).join(',');
    });
    var csv = '\uFEFF' + [headers.map(escapeCsv).join(','), rows.join('\n')].join('\n');
    var blob = new Blob([csv], { type: 'application/vnd.ms-excel;charset=utf-8;' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'current-stock-' + (lastCurrentStockValuation.as_of_date || new Date().toISOString().slice(0, 10)) + '.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    if (typeof showToast === 'function') showToast('Excel (CSV) exported. Open in Excel if needed.', 'success');
}

function printCurrentStock() {
    var wrap = document.getElementById('currentStockTableWrap');
    if (wrap) {
        var prevTitle = document.title;
        document.title = 'Current Stock / Valuation - ' + (lastCurrentStockValuation && lastCurrentStockValuation.branch_name ? lastCurrentStockValuation.branch_name : 'PharmaSight');
        window.print();
        document.title = prevTitle;
    } else {
        if (typeof showToast === 'function') showToast('No table to print. Click Apply to load stock first.', 'warning');
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
            if (typeof exportCurrentStockCsv === 'function') {
                window.exportCurrentStockCsv = exportCurrentStockCsv;
                window.exportCurrentStockExcel = exportCurrentStockExcel;
                window.printCurrentStock = printCurrentStock;
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
            // Branch inventory
            window.loadBranchOrdersData = loadBranchOrdersData;
            window.loadBranchTransfersData = loadBranchTransfersData;
            window.loadBranchReceiptsData = loadBranchReceiptsData;
            window.openBranchOrderCreate = openBranchOrderCreate;
            window.openBranchOrderView = openBranchOrderView;
            window.openBranchTransferCreate = openBranchTransferCreate;
            window.openBranchTransferView = openBranchTransferView;
            window.openBranchReceiptCreate = openBranchReceiptCreate;
            window.openBranchReceiptView = openBranchReceiptView;
            window.showBranchOrdersList = showBranchOrdersList;
            window.saveBranchOrderDraft = saveBranchOrderDraft;
            window.batchBranchOrder = batchBranchOrder;
            window.saveBranchTransferDraft = saveBranchTransferDraft;
            window.showBranchTransfersList = showBranchTransfersList;
            window.showBranchReceiptsList = showBranchReceiptsList;
            window.completeBranchTransfer = completeBranchTransfer;
            window.confirmBranchReceipt = confirmBranchReceipt;
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
