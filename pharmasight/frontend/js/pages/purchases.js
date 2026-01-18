// Purchases Page - Document Management (Purchase Orders, Invoices, Credit Notes)

// Immediate verification that script is executing
console.log('✅ purchases.js script loaded');
console.log('✅ Script execution started at:', new Date().toISOString());

let currentPurchaseSubPage = 'orders'; // 'orders', 'invoices', 'credit-notes', 'create'
let purchaseDocuments = [];
let currentDocument = null;
let documentItems = [];
let allSuppliers = [];

// Initialize purchases page
async function loadPurchases() {
    console.log('loadPurchases() called');
    const page = document.getElementById('purchases');
    if (!page) {
        console.error('Purchases page element not found!');
        return;
    }
    
    // Show the page
    document.querySelectorAll('.page').forEach(p => {
        p.classList.remove('active');
        p.style.display = 'none';
        p.style.visibility = 'hidden';
    });
    page.classList.add('active');
    page.style.display = 'block';
    page.style.visibility = 'visible';
    
    // Check CONFIG availability (defensive check)
    if (typeof window === 'undefined' || !window.CONFIG) {
        console.error('CONFIG not available! Waiting for config.js to load...');
        setTimeout(() => loadPurchases(), 500);
        return;
    }
    
    if (!window.CONFIG.COMPANY_ID || !window.CONFIG.BRANCH_ID) {
        console.warn('Company or Branch not configured');
        page.innerHTML = '<div class="card"><p>Please configure Company and Branch in Settings</p></div>';
        return;
    }
    
    console.log('Loading purchase sub-page:', currentPurchaseSubPage);
    // Load sub-page based on current selection (default to 'orders' if not set)
    const subPageToLoad = currentPurchaseSubPage || 'orders';
    await loadPurchaseSubPage(subPageToLoad);
}

// Load specific sub-page
async function loadPurchaseSubPage(subPage) {
    console.log('loadPurchaseSubPage() called with:', subPage);
    currentPurchaseSubPage = subPage;
    const page = document.getElementById('purchases');
    
    if (!page) {
        console.error('Purchases page element not found in loadPurchaseSubPage!');
        return;
    }
    
    // Ensure page is visible
    document.querySelectorAll('.page').forEach(p => {
        p.classList.remove('active');
        p.style.display = 'none';
        p.style.visibility = 'hidden';
    });
    page.classList.add('active');
    page.style.display = 'block';
    page.style.visibility = 'visible';
    
    switch(subPage) {
        case 'orders':
            await renderPurchaseOrdersPage();
            break;
        case 'create':
            await renderCreatePurchaseOrderPage();
            break;
        case 'invoices':
            await renderPurchaseInvoicesPage();
            break;
        case 'credit-notes':
            await renderCreditNotesPage();
            break;
        case 'suppliers':
            await renderSuppliersPage();
            break;
        default:
            await renderPurchaseOrdersPage();
    }
    
    // Update sub-nav active state
    updatePurchaseSubNavActiveState();
}

// =====================================================
// PAGE-SHELL FIRST PATTERN: Purchase Orders
// =====================================================

// Step 1: Render page shell (ALWAYS runs, regardless of data)
function renderPurchaseOrdersShell() {
    console.log('renderPurchaseOrdersShell() called - rendering page shell');
    const page = document.getElementById('purchases');
    if (!page) {
        console.error('Purchases page element not found in renderPurchaseOrdersShell!');
        return;
    }
    
    // Ensure page is visible before rendering
    page.style.display = 'block';
    page.style.visibility = 'visible';
    
    // Default to today's date
    const today = new Date().toISOString().split('T')[0];
    
    // Clear and render full page shell
    page.innerHTML = `
        <div class="card">
            <!-- Page Header -->
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice"></i> Purchase Orders
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="if(window.showPurchaseFilters) window.showPurchaseFilters()">
                        <i class="fas fa-filter"></i> Filters
                    </button>
                    <button class="btn btn-primary" onclick="if(window.createNewPurchaseOrder) window.createNewPurchaseOrder()">
                        <i class="fas fa-plus"></i> New Order
                    </button>
                </div>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <!-- Date Filter Bar -->
                <div style="margin-bottom: 1.5rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 50px;">From:</label>
                        <input type="date" 
                               class="form-input" 
                               id="filterDateFrom" 
                               placeholder="All dates"
                               onchange="if(window.applyDateFilter) window.applyDateFilter()"
                               style="width: 150px;">
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 30px;">To:</label>
                        <input type="date" 
                               class="form-input" 
                               id="filterDateTo" 
                               placeholder="All dates"
                               onchange="if(window.applyDateFilter) window.applyDateFilter()"
                               style="width: 150px;">
                    </div>
                    <button class="btn btn-outline" onclick="if(window.clearDateFilter) window.clearDateFilter()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                </div>
                
                <!-- Search Bar -->
                <div style="margin-bottom: 1.5rem;">
                    <input type="text" 
                           class="form-input" 
                           id="purchaseSearchInput" 
                           placeholder="Search by document number, supplier, reference..."
                           onkeyup="if(window.filterPurchaseDocuments) window.filterPurchaseDocuments()"
                           style="width: 100%; max-width: 500px; padding: 0.75rem;">
                </div>
                
                <!-- Table Container with Headers (ALWAYS rendered) -->
                <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto; position: relative;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <tr>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">DocNumber</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">DocDate</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">DocAmt</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Currency</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Acct</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">AcctRef</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">AcctName</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Branch</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">User</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="purchaseOrdersTableBody">
                            <!-- Loading state in tbody -->
                            <tr>
                                <td colspan="11" style="padding: 3rem; text-align: center;">
                                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading documents...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    
    console.log('✅ Purchase Orders shell rendered - page structure is now visible');
}

// Step 2: Fetch and render data (ONLY updates tbody)
async function fetchAndRenderPurchaseOrdersData() {
    console.log('fetchAndRenderPurchaseOrdersData() called - fetching data');
    const tbody = document.getElementById('purchaseOrdersTableBody');
    if (!tbody) {
        console.error('purchaseOrdersTableBody not found!');
        return;
    }
    
    try {
        // Fetch data
        await loadPurchaseDocuments('order');
        console.log('Documents loaded, count:', purchaseDocuments.length);
        
        // Render tbody content
        renderPurchaseOrdersTableBody();
        
    } catch (error) {
        console.error('Error fetching purchase orders data:', error);
        // Show error state in tbody (not replacing the whole page)
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                    <p style="color: var(--danger-color); margin-bottom: 0.5rem;">Error loading purchase orders</p>
                    <p style="color: var(--text-secondary); font-size: 0.875rem;">${error.message || 'Unknown error'}</p>
                    <button class="btn btn-outline" onclick="if(window.fetchAndRenderPurchaseOrdersData) window.fetchAndRenderPurchaseOrdersData()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </td>
            </tr>
        `;
    }
}

// Step 3: Render table body content (ONLY tbody, never replaces shell)
function renderPurchaseOrdersTableBody() {
    const tbody = document.getElementById('purchaseOrdersTableBody');
    if (!tbody) {
        console.error('purchaseOrdersTableBody not found in renderPurchaseOrdersTableBody!');
        return;
    }
    
    // Empty state: Show in tbody as a row
    if (purchaseDocuments.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-file-invoice" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No purchase orders found</p>
                    <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 1rem;">Get started by creating your first purchase order</p>
                    <button class="btn btn-primary" onclick="if(window.createNewPurchaseOrder) window.createNewPurchaseOrder()">
                        <i class="fas fa-plus"></i> Create Your First Purchase Order
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    // Render data rows
    const docType = 'order';
    const formattedDocs = purchaseDocuments.map(doc => ({
        docNumber: doc.order_number || doc.invoice_number || doc.grn_no || '—',
        docDate: doc.order_date || doc.invoice_date || doc.date_received || new Date(),
        docAmt: parseFloat(doc.total_amount || doc.total_inclusive || doc.total_cost || 0),
        currency: 'Kshs',
        acct: doc.supplier_id ? `SUP${String(doc.supplier_id).substring(0, 4).toUpperCase()}` : '—',
        acctRef: doc.reference || '—',
        acctName: doc.supplier_name || '—',
        branch: doc.branch_name || '—',
        curr: 'Kshs',
        status: doc.status || 'PENDING',
        doneBy: doc.created_by_name || '—', // Show user name
        id: doc.id
    }));
    
    tbody.innerHTML = formattedDocs.map(doc => {
        const statusClass = doc.status === 'RECEIVED' || doc.status === 'APPROVED' ? 'badge-success' : 
                          doc.status === 'CANCELLED' ? 'badge-danger' : 'badge-warning';
        const statusText = doc.status || 'PENDING';
        return `
            <tr style="cursor: pointer;" onclick="if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', '${docType}')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <strong style="color: var(--primary-color); cursor: pointer; text-decoration: underline;" 
                            onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', '${docType}')"
                            onmouseover="this.style.textDecoration='underline'; this.style.color='var(--primary-dark, #0056b3)'"
                            onmouseout="this.style.color='var(--primary-color)'">
                        ${doc.docNumber}
                    </strong>
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    ${formatDate(doc.docDate)}
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <strong>${formatCurrency(doc.docAmt)}</strong>
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.currency}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.acct}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.acctRef}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.acctName}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.branch}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <span class="badge ${statusClass}">${statusText}</span>
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    ${doc.doneBy || '—'}
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline" onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', '${docType}')" title="View">
                        <i class="fas fa-eye"></i>
                    </button>
                    ${statusText === 'PENDING' ? `
                    <button class="btn btn-outline" onclick="event.stopPropagation(); if(window.editPurchaseDocument) window.editPurchaseDocument('${doc.id}', '${docType}')" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-outline btn-danger" onclick="event.stopPropagation(); if(window.deletePurchaseOrder) window.deletePurchaseOrder('${doc.id}')" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                    ` : ''}
                </td>
            </tr>
        `;
    }).join('');
    
    console.log(`✅ Rendered ${formattedDocs.length} purchase order rows in tbody`);
}

// Main entry point: Render shell first, then fetch data
async function renderPurchaseOrdersPage() {
    console.log('renderPurchaseOrdersPage() called');
    
    try {
        // Ensure page element exists and is visible
        const page = document.getElementById('purchases');
        if (!page) {
            console.error('❌ Purchases page element not found in renderPurchaseOrdersPage!');
            return;
        }
        
        // Step 1: ALWAYS render shell first (synchronous)
        renderPurchaseOrdersShell();
        
        // Verify shell was rendered
        if (!page.innerHTML || page.innerHTML.trim() === '') {
            console.error('❌ Page shell was not rendered! Retrying...');
            // Retry once
            setTimeout(() => {
                renderPurchaseOrdersShell();
            }, 100);
        }
        
        // Step 2: Then fetch and render data (async)
        await fetchAndRenderPurchaseOrdersData();
    } catch (error) {
        console.error('❌ Error in renderPurchaseOrdersPage:', error);
        // Fallback: render shell even if there's an error
        const page = document.getElementById('purchases');
        if (page && (!page.innerHTML || page.innerHTML.trim() === '')) {
            renderPurchaseOrdersShell();
        }
    }
}

// =====================================================
// PAGE-SHELL FIRST PATTERN: Purchase Invoices
// =====================================================

function renderPurchaseInvoicesShell() {
    console.log('renderPurchaseInvoicesShell() called');
    const page = document.getElementById('purchases');
    if (!page) return;
    
    const today = new Date().toISOString().split('T')[0];
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice-dollar"></i> Purchase Invoices
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="if(window.showPurchaseFilters) window.showPurchaseFilters()">
                        <i class="fas fa-filter"></i> Filters
                    </button>
                    <button class="btn btn-primary" onclick="if(window.createNewPurchaseInvoice) window.createNewPurchaseInvoice()">
                        <i class="fas fa-plus"></i> New Invoice
                    </button>
                </div>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1.5rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 50px;">From:</label>
                        <input type="date" class="form-input" id="filterDateFrom" value="${today}" onchange="if(window.applyDateFilter) window.applyDateFilter()" style="width: 150px;">
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 30px;">To:</label>
                        <input type="date" class="form-input" id="filterDateTo" value="${today}" onchange="if(window.applyDateFilter) window.applyDateFilter()" style="width: 150px;">
                    </div>
                    <button class="btn btn-outline" onclick="if(window.clearDateFilter) window.clearDateFilter()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                </div>
                
                <div style="margin-bottom: 1.5rem;">
                    <input type="text" class="form-input" id="purchaseSearchInput" 
                           placeholder="Search by invoice number, supplier..." 
                           onkeyup="if(window.filterPurchaseDocuments) window.filterPurchaseDocuments()"
                           style="width: 100%; max-width: 500px; padding: 0.75rem;">
                </div>
                
                <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto; position: relative;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <tr>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Invoice Number</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Date</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Amount</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Supplier</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="purchaseInvoicesTableBody">
                            <tr>
                                <td colspan="6" style="padding: 3rem; text-align: center;">
                                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading invoices...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    console.log('✅ Purchase Invoices shell rendered');
}

async function fetchAndRenderPurchaseInvoicesData() {
    const tbody = document.getElementById('purchaseInvoicesTableBody');
    if (!tbody) return;
    
    try {
        await loadPurchaseDocuments('invoice');
        renderPurchaseInvoicesTableBody();
    } catch (error) {
        console.error('Error fetching invoices:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                    <p style="color: var(--danger-color);">Error loading invoices</p>
                    <button class="btn btn-outline" onclick="if(window.fetchAndRenderPurchaseInvoicesData) window.fetchAndRenderPurchaseInvoicesData()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </td>
            </tr>
        `;
    }
}

function renderPurchaseInvoicesTableBody() {
    const tbody = document.getElementById('purchaseInvoicesTableBody');
    if (!tbody) return;
    
    if (purchaseDocuments.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-file-invoice-dollar" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No purchase invoices found</p>
                    <button class="btn btn-primary" onclick="if(window.createNewPurchaseInvoice) window.createNewPurchaseInvoice()">
                        <i class="fas fa-plus"></i> Create Your First Purchase Invoice
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = purchaseDocuments.map(doc => {
        const statusClass = doc.status === 'PAID' ? 'badge-success' : 'badge-warning';
        return `
            <tr style="cursor: pointer;" onclick="if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', 'invoice')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong style="color: var(--primary-color);">${doc.invoice_number || '—'}</strong></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(doc.invoice_date || doc.created_at)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>${formatCurrency(doc.total_amount || 0)}</strong></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.supplier_name || '—'}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${statusClass}">${doc.status || 'PENDING'}</span></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline" onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', 'invoice')" title="View">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

async function renderPurchaseInvoicesPage() {
    renderPurchaseInvoicesShell();
    await fetchAndRenderPurchaseInvoicesData();
}

// =====================================================
// PAGE-SHELL FIRST PATTERN: Credit Notes
// =====================================================

function renderCreditNotesShell() {
    console.log('renderCreditNotesShell() called');
    const page = document.getElementById('purchases');
    if (!page) return;
    
    const today = new Date().toISOString().split('T')[0];
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice"></i> Credit Notes
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="if(window.showPurchaseFilters) window.showPurchaseFilters()">
                        <i class="fas fa-filter"></i> Filters
                    </button>
                    <button class="btn btn-primary" onclick="if(window.createNewCreditNote) window.createNewCreditNote()">
                        <i class="fas fa-plus"></i> New Credit Note
                    </button>
                </div>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1.5rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 50px;">From:</label>
                        <input type="date" class="form-input" id="filterDateFrom" value="${today}" onchange="if(window.applyDateFilter) window.applyDateFilter()" style="width: 150px;">
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 30px;">To:</label>
                        <input type="date" class="form-input" id="filterDateTo" value="${today}" onchange="if(window.applyDateFilter) window.applyDateFilter()" style="width: 150px;">
                    </div>
                    <button class="btn btn-outline" onclick="if(window.clearDateFilter) window.clearDateFilter()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                </div>
                
                <div style="margin-bottom: 1.5rem;">
                    <input type="text" class="form-input" id="purchaseSearchInput" 
                           placeholder="Search by credit note number, supplier..." 
                           onkeyup="if(window.filterPurchaseDocuments) window.filterPurchaseDocuments()"
                           style="width: 100%; max-width: 500px; padding: 0.75rem;">
                </div>
                
                <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto; position: relative;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <tr>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Credit Note #</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Date</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Amount</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Supplier</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="creditNotesTableBody">
                            <tr>
                                <td colspan="6" style="padding: 3rem; text-align: center;">
                                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading credit notes...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    console.log('✅ Credit Notes shell rendered');
}

async function fetchAndRenderCreditNotesData() {
    const tbody = document.getElementById('creditNotesTableBody');
    if (!tbody) return;
    
    try {
        await loadPurchaseDocuments('credit-note');
        renderCreditNotesTableBody();
    } catch (error) {
        console.error('Error fetching credit notes:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                    <p style="color: var(--danger-color);">Error loading credit notes</p>
                    <button class="btn btn-outline" onclick="if(window.fetchAndRenderCreditNotesData) window.fetchAndRenderCreditNotesData()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </td>
            </tr>
        `;
    }
}

function renderCreditNotesTableBody() {
    const tbody = document.getElementById('creditNotesTableBody');
    if (!tbody) return;
    
    if (purchaseDocuments.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-file-invoice" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No credit notes found</p>
                    <button class="btn btn-primary" onclick="if(window.createNewCreditNote) window.createNewCreditNote()">
                        <i class="fas fa-plus"></i> Create Your First Credit Note
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = purchaseDocuments.map(doc => {
        return `
            <tr style="cursor: pointer;" onclick="if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', 'credit-note')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong style="color: var(--primary-color);">${doc.credit_note_number || '—'}</strong></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(doc.date || doc.created_at)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>${formatCurrency(doc.total_amount || 0)}</strong></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.supplier_name || '—'}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><span class="badge badge-warning">${doc.status || 'PENDING'}</span></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline" onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', 'credit-note')" title="View">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

async function renderCreditNotesPage() {
    renderCreditNotesShell();
    await fetchAndRenderCreditNotesData();
}

// Load purchase documents from API
async function loadPurchaseDocuments(documentType = 'order') {
    try {
        if (!CONFIG.COMPANY_ID) {
            purchaseDocuments = [];
            return;
        }
        
        // Get filter values (default to all dates if not set - don't restrict to today)
        const dateFromEl = document.getElementById('filterDateFrom');
        const dateToEl = document.getElementById('filterDateTo');
        const dateFrom = dateFromEl?.value || null; // Don't default to today - show all orders
        const dateTo = dateToEl?.value || null;
        const supplierId = document.getElementById('filterSupplier')?.value || null;
        const status = document.getElementById('filterStatus')?.value || null;
        
        if (documentType === 'order') {
            // Load purchase orders
            const params = {
                company_id: CONFIG.COMPANY_ID
            };
            if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
            // Only add date filters if explicitly set
            if (dateFrom) params.date_from = dateFrom;
            if (dateTo) params.date_to = dateTo;
            if (supplierId) params.supplier_id = supplierId;
            if (status) params.status = status;
            
            purchaseDocuments = await API.purchases.listOrders(params);
        } else if (documentType === 'invoice') {
            // Load purchase invoices
            purchaseDocuments = await API.purchases.listInvoices(CONFIG.COMPANY_ID, CONFIG.BRANCH_ID);
        } else if (documentType === 'credit-note') {
            // Load credit notes
            purchaseDocuments = []; // TODO: Implement credit notes
        }
        
    } catch (error) {
        console.error('Error loading purchase documents:', error);
        showToast('Error loading documents', 'error');
        purchaseDocuments = [];
    }
}

// Filter documents (uses new pattern - only updates tbody)
function filterPurchaseDocuments() {
    const searchTerm = document.getElementById('purchaseSearchInput')?.value.toLowerCase() || '';
    // Filter the current documents array
    // TODO: Implement client-side filtering or re-fetch with search term
    // For now, just re-render the current page's table body
    switch(currentPurchaseSubPage) {
        case 'orders':
            renderPurchaseOrdersTableBody();
            break;
        case 'invoices':
            renderPurchaseInvoicesTableBody();
            break;
        case 'credit-notes':
            renderCreditNotesTableBody();
            break;
    }
}

// Show filters modal
function showPurchaseFilters() {
    const content = `
        <form id="purchaseFiltersForm">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Date From</label>
                    <input type="date" class="form-input" name="date_from" value="${new Date().toISOString().split('T')[0]}">
                </div>
                <div class="form-group">
                    <label class="form-label">Date To</label>
                    <input type="date" class="form-input" name="date_to" value="${new Date().toISOString().split('T')[0]}">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Supplier</label>
                <select class="form-select" name="supplier_id">
                    <option value="">All Suppliers</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Status</label>
                <select class="form-select" name="status">
                    <option value="">All Statuses</option>
                    <option value="pending">Pending</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                </select>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="applyPurchaseFilters()">Apply Filters</button>
    `;
    
    showModal('Filter Documents', content, footer);
}

// Apply filters (uses new pattern)
function applyPurchaseFilters() {
    // TODO: Implement filter application
    closeModal();
    const docType = currentPurchaseSubPage === 'orders' ? 'order' : 
                   currentPurchaseSubPage === 'invoices' ? 'invoice' : 'credit-note';
    loadPurchaseDocuments(docType).then(() => {
        // Re-render the appropriate table body
        switch(currentPurchaseSubPage) {
            case 'orders':
                renderPurchaseOrdersTableBody();
                break;
            case 'invoices':
                renderPurchaseInvoicesTableBody();
                break;
            case 'credit-notes':
                renderCreditNotesTableBody();
                break;
        }
    });
}

// Apply date filter (uses new pattern - only updates tbody)
async function applyDateFilter() {
    const docType = currentPurchaseSubPage === 'orders' ? 'order' : 
                   currentPurchaseSubPage === 'invoices' ? 'invoice' : 'credit-note';
    try {
        await loadPurchaseDocuments(docType);
        // Re-render the appropriate table body
        switch(currentPurchaseSubPage) {
            case 'orders':
                renderPurchaseOrdersTableBody();
                break;
            case 'invoices':
                renderPurchaseInvoicesTableBody();
                break;
            case 'credit-notes':
                renderCreditNotesTableBody();
                break;
        }
    } catch (error) {
        console.error('Error applying date filter:', error);
        showToast('Error applying filter', 'error');
    }
}

// Clear date filter (uses new pattern)
function clearDateFilter() {
    const today = new Date().toISOString().split('T')[0];
    const dateFromInput = document.getElementById('filterDateFrom');
    const dateToInput = document.getElementById('filterDateTo');
    if (dateFromInput) dateFromInput.value = today;
    if (dateToInput) dateToInput.value = today;
    applyDateFilter();
}

// Create new Purchase Order (Navigate to create page)
function createNewPurchaseOrder() {
    console.log('createNewPurchaseOrder() called');
    // Reset document state for new order
    currentDocument = { type: 'order', items: [] };
    documentItems = [];
    // Navigate to create page
    loadPurchaseSubPage('create');
}

// Export immediately after definition
if (typeof window !== 'undefined') {
    window.createNewPurchaseOrder = createNewPurchaseOrder;
}

// Create new Purchase Invoice
function createNewPurchaseInvoice() {
    currentDocument = { type: 'invoice', items: [] };
    documentItems = [];
    // TODO: Implement invoice creation page
    showToast('Purchase invoice creation coming soon', 'info');
    // For now, redirect to create page (will show order form - to be updated)
    loadPurchaseSubPage('create');
}

// Create new Credit Note
function createNewCreditNote() {
    currentDocument = { type: 'credit-note', items: [] };
    documentItems = [];
    // TODO: Implement credit note creation page
    showToast('Credit note creation coming soon', 'info');
    // For now, redirect to create page (will show order form - to be updated)
    loadPurchaseSubPage('create');
}

// Render Create Purchase Order Page (NOT a modal)
async function renderCreatePurchaseOrderPage() {
    console.log('renderCreatePurchaseOrderPage()');
    
    const page = document.getElementById('purchases');
    if (!page) {
        console.error('Purchases page element not found!');
        return;
    }
    
    // Check if we're editing an existing document
    const isEditMode = currentDocument && currentDocument.id;
    const orderId = currentDocument?.id || null;
    
    // If not editing, reset document state
    if (!isEditMode) {
        currentDocument = { type: 'order', items: [] };
        documentItems = [];
    }
    
    const today = new Date().toISOString().split('T')[0];
    
    // Prepare buttons for top bar based on mode
    const topButtonsHtml = isEditMode ? `
        <button type="button" class="btn btn-primary btn-save-order" onclick="if(window.updatePurchaseOrder) { const form = document.getElementById('purchaseDocumentForm'); if(form) updatePurchaseOrder({preventDefault:()=>{},target:form}, '${orderId}'); }">
            <i class="fas fa-save"></i> Save
        </button>
        <button type="button" class="btn btn-outline" onclick="showToast('Batch functionality coming soon', 'info')" title="Batch">
            <i class="fas fa-layer-group"></i> Batch
        </button>
        <button type="button" class="btn btn-outline" onclick="if(window.printPurchaseOrder) window.printPurchaseOrder('${orderId}')" title="Print">
            <i class="fas fa-print"></i> Print
        </button>
        <button type="button" class="btn btn-outline btn-danger" onclick="if(window.deletePurchaseOrder) window.deletePurchaseOrder('${orderId}')" title="Delete">
            <i class="fas fa-trash"></i> Delete
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadPurchaseSubPage('orders')">
            <i class="fas fa-arrow-left"></i> Back
        </button>
    ` : `
        <button type="submit" class="btn btn-primary" form="purchaseDocumentForm">
            <i class="fas fa-save"></i> Save
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadPurchaseSubPage('orders')">
            <i class="fas fa-arrow-left"></i> Back
        </button>
    `;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice"></i> ${isEditMode ? 'Edit' : 'Create'} Purchase Order
                    ${isEditMode && currentDocument.order_number ? `: ${currentDocument.order_number}` : ''}
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    ${topButtonsHtml}
                </div>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <form id="purchaseDocumentForm" ${isEditMode ? '' : 'onsubmit="savePurchaseDocument(event, \'order\')"'} >
                    <!-- Document Header -->
                    <div class="card" style="margin-bottom: 1.5rem;">
                        <div class="card-header">
                            <h4>Order Details</h4>
                        </div>
                        <div class="card-body">
                            <div class="form-row">
                                <div class="form-group" style="flex: 1;">
                                    <label class="form-label">Supplier *</label>
                                    <div style="position: relative;">
                                        <input type="text" 
                                               class="form-input" 
                                               id="supplierSearch" 
                                               placeholder="Search supplier by name..."
                                               autocomplete="off"
                                               required
                                               onkeyup="searchSuppliersInline(event)"
                                               onfocus="handleSupplierSearchFocus(event)"
                                               onblur="handleSupplierSearchBlur(event)">
                                        <input type="hidden" name="supplier_id" id="supplierId" required>
                                        <div id="supplierSearchDropdown" 
                                             style="position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid var(--border-color); border-radius: 0.25rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 1000; max-height: 300px; overflow-y: auto; display: none; margin-top: 0.25rem;">
                                        </div>
                                    </div>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Date *</label>
                                    <input type="date" class="form-input" name="document_date" 
                                           value="${today}" required>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">Reference</label>
                                    <input type="text" class="form-input" name="reference" placeholder="Order reference">
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Notes</label>
                                    <input type="text" class="form-input" name="notes" placeholder="Additional notes">
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table (Vyapar-style, table-driven) -->
                    <div class="card" style="margin-bottom: 1.5rem;">
                        <div class="card-header">
                            <h4>Items</h4>
                        </div>
                        <div class="card-body" id="transactionItemsContainer">
                            <!-- TransactionItemsTable component will render here -->
                        </div>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize TransactionItemsTable component
    initializeTransactionItemsTable();
    
    // Set form submit handler for edit mode (after form is rendered)
    if (isEditMode && orderId) {
        setTimeout(() => {
            const form = document.getElementById('purchaseDocumentForm');
            if (form) {
                form.onsubmit = (e) => {
                    e.preventDefault();
                    updatePurchaseOrder(e, orderId);
                };
            }
        }, 100);
    }
}

// Initialize TransactionItemsTable component
let transactionItemsTable = null;

function initializeTransactionItemsTable() {
    const container = document.getElementById('transactionItemsContainer');
    if (!container) {
        setTimeout(initializeTransactionItemsTable, 100);
        return;
    }
    
    // Convert existing documentItems to component format
    const items = documentItems.length > 0 
        ? documentItems.map(item => ({
            id: item.item_id,
            item_id: item.item_id,
            item_name: item.item_name,
            item_sku: item.item_sku,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price: item.unit_price,
            total: item.total,
            is_empty: false
        }))
        : [];
    
    // Create component instance with new API
    transactionItemsTable = new window.TransactionItemsTable({
        mountEl: container,
        mode: 'purchase',
        items: items,
        priceType: 'purchase_price',
        onItemsChange: (validItems) => {
            // Update documentItems
            documentItems = validItems.map(item => ({
                item_id: item.item_id,
                item_name: item.item_name,
                item_sku: item.item_sku,
                item_code: item.item_code || item.item_sku,
                unit_name: item.unit_name,
                quantity: item.quantity,
                unit_price: item.unit_price,
                discount_percent: item.discount_percent || 0,
                total: item.total
            }));
        },
        onTotalChange: (total) => {
            // Update total display (if needed elsewhere)
            console.log('Total changed:', total);
        },
        onItemCreate: (query, rowIndex, callback) => {
            // Show option to create item
            showToast(`To create item "${query}", please go to Items page`, 'info');
        }
    });
    
    // Expose to window for component callbacks
    window[`transactionTable_transactionItemsContainer`] = transactionItemsTable;
}

// Removed old item search functions - now handled by TransactionItemsTable component

// Search suppliers inline with API (lazy, query-based)
let supplierSearchTimeout;
let supplierSearchAbortController = null;
let supplierSearchCache = new Map(); // Cache recent searches
const CACHE_TTL = 30000; // 30 seconds cache TTL

async function searchSuppliersInline(event) {
    const query = event.target.value.trim();
    const dropdown = document.getElementById('supplierSearchDropdown');
    const hiddenInput = document.getElementById('supplierId');
    
    if (!dropdown || !hiddenInput) return;
    
    // Clear previous timeout
    clearTimeout(supplierSearchTimeout);
    
    // Abort previous request if still pending
    if (supplierSearchAbortController) {
        supplierSearchAbortController.abort();
    }
    
    if (query.length < 2) {
        dropdown.style.display = 'none';
        hiddenInput.value = '';
        return;
    }
    
    // Show loading state immediately
    dropdown.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--text-secondary);"><i class="fas fa-spinner fa-spin"></i> Searching...</div>';
    dropdown.style.display = 'block';
    
    // Check cache first
    const cacheKey = `${CONFIG.COMPANY_ID}:${query.toLowerCase()}`;
    const cached = supplierSearchCache.get(cacheKey);
    if (cached && (Date.now() - cached.timestamp) < CACHE_TTL) {
        renderSupplierSearchResults(cached.data, dropdown);
        return;
    }
    
    // Debounce API call (250ms for better responsiveness)
    supplierSearchTimeout = setTimeout(async () => {
        try {
            // Ensure CONFIG and API are available
            if (typeof CONFIG === 'undefined' || typeof API === 'undefined') {
                console.error('CONFIG or API not available in supplier search');
                dropdown.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--danger-color);">Configuration error. Please refresh the page.</div>';
                dropdown.style.display = 'block';
                return;
            }
            
            if (!CONFIG.COMPANY_ID) {
                dropdown.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--text-secondary);">Company not configured</div>';
                dropdown.style.display = 'block';
                return;
            }
            
            // Create new abort controller for this request
            supplierSearchAbortController = new AbortController();
            
            // Query API search endpoint (lightweight)
            console.log('🔍 [Supplier Search] Searching:', query, 'Company:', CONFIG.COMPANY_ID);
            const suppliers = await API.suppliers.search(query, CONFIG.COMPANY_ID, 10);
            console.log('✅ [Supplier Search] Suppliers found:', suppliers.length);
            
            // Cache results
            supplierSearchCache.set(cacheKey, {
                data: suppliers,
                timestamp: Date.now()
            });
            
            // Clean old cache entries (keep only last 20)
            if (supplierSearchCache.size > 20) {
                const oldestKey = supplierSearchCache.keys().next().value;
                supplierSearchCache.delete(oldestKey);
            }
            
            renderSupplierSearchResults(suppliers, dropdown);
        } catch (error) {
            if (error.name === 'AbortError') {
                return; // Request was aborted, ignore
            }
            console.error('❌ [Supplier Search] Error searching suppliers:', error);
            dropdown.innerHTML = `<div style="padding: 1rem; text-align: center; color: var(--danger-color);">Error: ${error.message || 'Failed to search suppliers'}</div>`;
            dropdown.style.display = 'block';
        }
    }, 250);
}

// Render supplier search results
function renderSupplierSearchResults(suppliers, dropdown) {
    if (suppliers.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--text-secondary);">No suppliers found</div>';
        dropdown.style.display = 'block';
        return;
    }
    
    // Render dropdown results
    dropdown.innerHTML = suppliers.map(supplier => {
        return `
            <div class="supplier-search-result" 
                 style="padding: 0.75rem; cursor: pointer; border-bottom: 1px solid var(--border-color); transition: background 0.2s;"
                 onmouseover="this.style.background='#f8f9fa'"
                 onmouseout="this.style.background='white'"
                 onclick="selectSupplier('${supplier.id}', '${escapeHtml(supplier.name)}')">
                <strong>${escapeHtml(supplier.name)}</strong>
            </div>
        `;
    }).join('');
    
    dropdown.style.display = 'block';
}

// Select supplier from search
function selectSupplier(supplierId, supplierName) {
    const searchInput = document.getElementById('supplierSearch');
    const hiddenInput = document.getElementById('supplierId');
    const dropdown = document.getElementById('supplierSearchDropdown');
    
    if (searchInput) searchInput.value = supplierName;
    if (hiddenInput) hiddenInput.value = supplierId;
    if (dropdown) dropdown.style.display = 'none';
    
    // Focus back on search input for quick entry
    if (searchInput) searchInput.focus();
}

// Removed handleItemSearchFocus/handleItemSearchBlur - now handled by TransactionItemsTable component

// Handle supplier search focus
function handleSupplierSearchFocus(event) {
    const query = event.target.value.trim();
    if (query.length >= 2) {
        const dropdown = document.getElementById('supplierSearchDropdown');
        if (dropdown && dropdown.innerHTML.trim() !== '') {
            dropdown.style.display = 'block';
        }
    }
}

// Handle supplier search blur (with delay to allow click)
function handleSupplierSearchBlur(event) {
    setTimeout(() => {
        const dropdown = document.getElementById('supplierSearchDropdown');
        if (dropdown) dropdown.style.display = 'none';
    }, 200);
}

// Removed old table rendering functions - now handled by TransactionItemsTable component

// Save purchase document
let isSavingDocument = false; // Flag to prevent duplicate submissions
let isDeletingOrder = false; // Flag to prevent duplicate delete operations

async function savePurchaseDocument(event, documentType) {
    console.log('savePurchaseDocument()');
    
    event.preventDefault();
    
    // Prevent duplicate submissions
    if (isSavingDocument) {
        showToast('Please wait, order is being saved...', 'warning');
        return;
    }
    
    const form = event.target;
    const submitButton = form.querySelector('button[type="submit"]');
    
    // Disable submit button and set flag
    isSavingDocument = true;
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    }
    
    const formData = new FormData(form);
    
    // Get items from component
    const items = transactionItemsTable ? transactionItemsTable.getItems() : [];
    
    if (items.length === 0) {
        isSavingDocument = false;
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = '<i class="fas fa-save"></i> Save Purchase Order';
        }
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
        isSavingDocument = false;
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = '<i class="fas fa-save"></i> Save Purchase Order';
        }
        showToast('Company and Branch must be configured', 'error');
        return;
    }
    
    try {
        const currentUserId = CONFIG.USER_ID || '29932846-bf01-4b4b-9e13-25cb27764c16';
        
        const documentData = {
            company_id: CONFIG.COMPANY_ID,
            branch_id: CONFIG.BRANCH_ID,
            supplier_id: formData.get('supplier_id'),
            order_date: formData.get('document_date') || new Date().toISOString().split('T')[0],
            reference: formData.get('reference') || null,
            notes: formData.get('notes') || null,
            status: 'PENDING',
            created_by: currentUserId,
            items: items.map(item => ({
                item_id: item.item_id,
                unit_name: item.unit_name,
                quantity: item.quantity,
                unit_price: item.unit_price,
                total_price: item.total
            }))
        };
        
        let result;
        if (documentType === 'order') {
            result = await API.purchases.createOrder(documentData);
        } else if (documentType === 'invoice') {
            result = await API.purchases.createInvoice(documentData);
        } else {
            showToast('Credit notes not yet implemented', 'info');
            return;
        }
        
        showToast(`${documentType === 'order' ? 'Purchase Order' : 'Purchase Invoice'} saved successfully!`, 'success');
        
        // Reset state
        documentItems = [];
        currentDocument = null;
        transactionItemsTable = null;
        isSavingDocument = false; // Reset flag
        
        // Navigate back
        if (documentType === 'order') {
            await loadPurchaseSubPage('orders');
        } else {
            await loadPurchaseSubPage('invoices');
        }
    } catch (error) {
        console.error('Error saving purchase document:', error);
        showToast(error.message || 'Error saving document', 'error');
        isSavingDocument = false; // Reset flag on error
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = '<i class="fas fa-save"></i> Save Purchase Order';
        }
    }
}

// View document
async function viewPurchaseDocument(docId, docType) {
    if (docType !== 'order') {
        showToast('Viewing this document type is not yet implemented', 'info');
        return;
    }
    
    try {
        const order = await API.purchases.getOrder(docId);
        
        const formatDate = (dateStr) => {
            if (!dateStr) return '—';
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
        };
        
        const formatCurrency = (amount) => {
            return new Intl.NumberFormat('en-KE', { style: 'currency', currency: 'KES' }).format(amount || 0);
        };
        
        // Use item details from response (already loaded by backend)
        const itemsHtml = (order.items || []).map(item => {
            const itemName = item.item_name || 'Item';
            const itemCode = item.item_code || '';
            return `
                <tr>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">
                        <div style="font-weight: 600;">${itemName}</div>
                        ${itemCode ? `<div style="font-size: 0.875rem; color: var(--text-secondary);">Code: ${itemCode}</div>` : ''}
                        ${item.item_category ? `<div style="font-size: 0.875rem; color: var(--text-secondary);">Category: ${item.item_category}</div>` : ''}
                    </td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: center;">${item.quantity || 0}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${item.unit_name || '—'}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">
                        ${formatCurrency(item.unit_price || 0)}
                        ${item.default_cost ? `<div style="font-size: 0.875rem; color: var(--text-secondary);">Cost: ${formatCurrency(item.default_cost)}</div>` : ''}
                    </td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align: right;">
                        <strong>${formatCurrency(item.total_price || 0)}</strong>
                    </td>
                </tr>
            `;
        }).join('');
        
        const content = `
            <div style="max-height: 70vh; overflow-y: auto;">
                <div style="margin-bottom: 1.5rem;">
                    <h4 style="margin-bottom: 1rem;">Purchase Order Details</h4>
                    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem;">
                        <div>
                            <strong>Order Number:</strong> ${order.order_number || '—'}
                        </div>
                        <div>
                            <strong>Date:</strong> ${formatDate(order.order_date)}
                        </div>
                        <div>
                            <strong>Supplier:</strong> ${order.supplier_name || '—'}
                        </div>
                        <div>
                            <strong>Branch:</strong> ${order.branch_name || '—'}
                        </div>
                        <div>
                            <strong>Reference:</strong> ${order.reference || '—'}
                        </div>
                        <div>
                            <strong>Status:</strong> <span class="badge ${order.status === 'PENDING' ? 'badge-warning' : order.status === 'RECEIVED' ? 'badge-success' : 'badge-danger'}">${order.status || 'PENDING'}</span>
                        </div>
                        <div>
                            <strong>Created By:</strong> ${order.created_by_name || '—'}
                        </div>
                        <div>
                            <strong>Total Amount:</strong> <strong style="font-size: 1.1rem;">${formatCurrency(order.total_amount || 0)}</strong>
                        </div>
                    </div>
                    ${order.notes ? `<div style="margin-top: 1rem;"><strong>Notes:</strong><br>${order.notes}</div>` : ''}
                </div>
                
                <div>
                    <h5 style="margin-bottom: 1rem;">Items</h5>
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: #f8f9fa;">
                                <th style="padding: 0.5rem; text-align: left; border-bottom: 2px solid var(--border-color);">Item</th>
                                <th style="padding: 0.5rem; text-align: center; border-bottom: 2px solid var(--border-color);">Qty</th>
                                <th style="padding: 0.5rem; text-align: left; border-bottom: 2px solid var(--border-color);">Unit</th>
                                <th style="padding: 0.5rem; text-align: right; border-bottom: 2px solid var(--border-color);">Unit Price</th>
                                <th style="padding: 0.5rem; text-align: right; border-bottom: 2px solid var(--border-color);">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${itemsHtml || '<tr><td colspan="5" style="text-align: center; padding: 1rem;">No items</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        
        const isPending = order.status === 'PENDING';
        const footer = `
            <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            ${isPending ? `
            <button class="btn btn-outline" onclick="closeModal(); if(window.editPurchaseDocument) window.editPurchaseDocument('${order.id}', 'order')" title="Edit">
                <i class="fas fa-edit"></i> Edit
            </button>
            <button class="btn btn-outline btn-danger" onclick="closeModal(); if(window.deletePurchaseOrder) window.deletePurchaseOrder('${order.id}')" title="Delete">
                <i class="fas fa-trash"></i> Delete
            </button>
            ` : ''}
            <button class="btn btn-primary" onclick="if(window.printPurchaseOrder) window.printPurchaseOrder('${order.id}')" title="Print">
                <i class="fas fa-print"></i> Print
            </button>
        `;
        
        showModal(`Purchase Order: ${order.order_number || '—'}`, content, footer, 'modal-large');
    } catch (error) {
        console.error('Error loading purchase order:', error);
        showToast(error.message || 'Error loading purchase order', 'error');
    }
}

// Edit document
async function editPurchaseDocument(docId, docType) {
    if (docType !== 'order') {
        showToast('Editing this document type is not yet implemented', 'info');
        return;
    }
    
    try {
        const order = await API.purchases.getOrder(docId);
        
        if (order.status !== 'PENDING') {
            showToast(`Cannot edit purchase order with status ${order.status}. Only PENDING orders can be edited.`, 'error');
            return;
        }
        
        // Use item details from response (already loaded by backend with item_name, item_code)
        // Set current document and items
        currentDocument = { 
            type: 'order', 
            id: order.id,
            order_number: order.order_number,
            supplier_id: order.supplier_id,
            supplier_name: order.supplier_name,
            order_date: order.order_date,
            reference: order.reference,
            notes: order.notes,
            status: order.status,
            ...order 
        };
        
        // Map items using backend response (item_name, item_code already included)
        documentItems = (order.items || []).map(item => ({
            item_id: item.item_id,
            item_name: item.item_name || 'Item',
            item_sku: item.item_code || '',
            item_code: item.item_code || '',
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price: item.unit_price,
            total: item.total_price,
            is_empty: false
        }));
        
        // Load the create page with existing data (will be pre-filled by the form initialization)
        await renderCreatePurchaseOrderPage();
        
        // After page renders, populate form with existing order data
        setTimeout(() => {
            const form = document.getElementById('purchaseDocumentForm');
            if (form) {
                if (order.supplier_id) {
                    const supplierIdInput = document.getElementById('supplierId');
                    const supplierSearch = document.getElementById('supplierSearch');
                    if (supplierIdInput) supplierIdInput.value = order.supplier_id;
                    if (supplierSearch && order.supplier_name) supplierSearch.value = order.supplier_name;
                }
                
                const dateInput = form.querySelector('input[name="document_date"]');
                if (dateInput && order.order_date) {
                    dateInput.value = new Date(order.order_date).toISOString().split('T')[0];
                }
                
                const referenceInput = form.querySelector('input[name="reference"]');
                if (referenceInput) referenceInput.value = order.reference || '';
                
                const notesInput = form.querySelector('input[name="notes"]');
                if (notesInput) notesInput.value = order.notes || '';
            }
            
            // Update TransactionItemsTable if it exists
            if (transactionItemsTable && documentItems.length > 0) {
                transactionItemsTable.items = transactionItemsTable.normalizeItems(documentItems);
                transactionItemsTable.render();
                transactionItemsTable.attachEventListeners();
            }
            
            // Ensure form submit handler is set for edit mode (reuse existing form variable from above)
            // form variable is already declared at line 1469, just reuse it
            if (form) {
                form.onsubmit = (e) => {
                    e.preventDefault();
                    updatePurchaseOrder(e, order.id);
                };
            }
        }, 300);
        
    } catch (error) {
        console.error('Error loading purchase order for editing:', error);
        showToast(error.message || 'Error loading purchase order', 'error');
    }
}

// Update purchase order
async function updatePurchaseOrder(event, orderId) {
    event.preventDefault();
    
    // Prevent duplicate submissions
    if (isSavingDocument) {
        showToast('Please wait, order is being saved...', 'warning');
        return;
    }
    
    const form = event.target;
    const submitButton = form.querySelector('button[type="submit"], .btn-save-order');
    
    // Disable submit button and set flag
    isSavingDocument = true;
    if (submitButton) {
        submitButton.disabled = true;
        const originalText = submitButton.innerHTML;
        submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    }
    
    const formData = new FormData(form);
    
    // Get items from component
    let validItems = [];
    if (transactionItemsTable && typeof transactionItemsTable.getItems === 'function') {
        validItems = transactionItemsTable.getItems();
    } else {
        validItems = documentItems.filter(item => item.item_id && item.item_id !== null);
    }
    
    if (validItems.length === 0) {
        isSavingDocument = false;
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = '<i class="fas fa-save"></i> Save';
        }
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    const orderData = {
        company_id: CONFIG.COMPANY_ID,
        branch_id: CONFIG.BRANCH_ID,
        supplier_id: formData.get('supplier_id'),
        order_date: formData.get('document_date'),
        reference: formData.get('reference') || null,
        notes: formData.get('notes') || null,
        status: 'PENDING',
        items: validItems.map(item => ({
            item_id: item.item_id,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price: item.unit_price
        })),
        created_by: CONFIG.USER_ID
    };
    
    try {
        const updatedOrder = await API.purchases.updateOrder(orderId, orderData);
        showToast('Purchase order updated successfully!', 'success');
        loadPurchaseSubPage('orders');
    } catch (error) {
        console.error('Error updating purchase order:', error);
        showToast(error.message || 'Error updating purchase order', 'error');
    }
}

// Delete purchase order
async function deletePurchaseOrder(orderId) {
    // Prevent duplicate delete operations
    if (isDeletingOrder) {
        showToast('Delete operation already in progress. Please wait...', 'warning');
        return;
    }
    
    if (!confirm('Are you sure you want to delete this purchase order? This action cannot be undone.')) {
        return;
    }
    
    // Set flag to prevent duplicate operations
    isDeletingOrder = true;
    
    try {
        await API.purchases.deleteOrder(orderId);
        showToast('Purchase order deleted successfully!', 'success');
        
        // Reset flag
        isDeletingOrder = false;
        
        // Refresh the orders list
        await fetchAndRenderPurchaseOrdersData();
        
        // If modal is open, close it
        const modal = document.getElementById('modalOverlay');
        if (modal && modal.style.display !== 'none') {
            closeModal();
        }
    } catch (error) {
        console.error('Error deleting purchase order:', error);
        isDeletingOrder = false; // Reset flag on error
        
        // Handle 404 (order already deleted) gracefully
        if (error.status === 404 || error.message.includes('404') || error.message.includes('Not Found')) {
            showToast('Purchase order not found. It may have already been deleted.', 'info');
            // Still refresh the list in case it was deleted by another process
            await fetchAndRenderPurchaseOrdersData();
        } else {
            showToast(error.message || 'Error deleting purchase order', 'error');
        }
    }
}

// Print purchase order
async function printPurchaseOrder(orderId) {
    try {
        const order = await API.purchases.getOrder(orderId);
        
        const formatDate = (dateStr) => {
            if (!dateStr) return '—';
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
        };
        
        const formatCurrency = (amount) => {
            return new Intl.NumberFormat('en-KE', { style: 'currency', currency: 'KES' }).format(amount || 0);
        };
        
        // Create print-friendly HTML
        const printContent = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Purchase Order ${order.order_number}</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    .header { text-align: center; margin-bottom: 30px; }
                    .header h1 { margin: 0; color: #333; }
                    .info-section { margin-bottom: 30px; }
                    .info-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
                    .info-item { margin: 5px 0; }
                    .info-label { font-weight: bold; }
                    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                    th { background: #f8f9fa; padding: 10px; text-align: left; border-bottom: 2px solid #333; }
                    td { padding: 8px; border-bottom: 1px solid #ddd; }
                    .text-right { text-align: right; }
                    .text-center { text-align: center; }
                    .total-row { font-weight: bold; background: #f8f9fa; }
                    .footer { margin-top: 40px; text-align: center; font-size: 0.9em; color: #666; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>PURCHASE ORDER</h1>
                    <p>${order.order_number || '—'}</p>
                </div>
                
                <div class="info-section">
                    <div class="info-grid">
                        <div class="info-item">
                            <span class="info-label">Date:</span> ${formatDate(order.order_date)}
                        </div>
                        <div class="info-item">
                            <span class="info-label">Supplier:</span> ${order.supplier_name || '—'}
                        </div>
                        <div class="info-item">
                            <span class="info-label">Branch:</span> ${order.branch_name || '—'}
                        </div>
                        <div class="info-item">
                            <span class="info-label">Reference:</span> ${order.reference || '—'}
                        </div>
                        <div class="info-item">
                            <span class="info-label">Status:</span> ${order.status || 'PENDING'}
                        </div>
                        <div class="info-item">
                            <span class="info-label">Created By:</span> ${order.created_by_name || '—'}
                        </div>
                    </div>
                    ${order.notes ? `<div class="info-item" style="margin-top: 15px;"><span class="info-label">Notes:</span> ${order.notes}</div>` : ''}
                </div>
                
                <table>
                    <thead>
                        <tr>
                            <th>Item Name</th>
                            <th class="text-center">Qty</th>
                            <th>Unit</th>
                            <th class="text-right">Unit Price</th>
                            <th class="text-right">Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${(order.items || []).map(item => `
                            <tr>
                                <td>${item.item_name || 'Item'}${item.item_code ? ` (${item.item_code})` : ''}</td>
                                <td class="text-center">${item.quantity || 0}</td>
                                <td>${item.unit_name || '—'}</td>
                                <td class="text-right">${formatCurrency(item.unit_price || 0)}</td>
                                <td class="text-right">${formatCurrency(item.total_price || 0)}</td>
                            </tr>
                        `).join('')}
                        <tr class="total-row">
                            <td colspan="4" class="text-right"><strong>Total:</strong></td>
                            <td class="text-right"><strong>${formatCurrency(order.total_amount || 0)}</strong></td>
                        </tr>
                    </tbody>
                </table>
                
                <div class="footer">
                    <p>Generated on ${new Date().toLocaleString('en-KE')}</p>
                </div>
            </body>
            </html>
        `;
        
        // Open print window
        const printWindow = window.open('', '_blank');
        printWindow.document.write(printContent);
        printWindow.document.close();
        printWindow.focus();
        
        // Wait for content to load, then print
        setTimeout(() => {
            printWindow.print();
        }, 250);
        
    } catch (error) {
        console.error('Error printing purchase order:', error);
        showToast(error.message || 'Error printing purchase order', 'error');
    }
}

// Update sub-nav active state
function updatePurchaseSubNavActiveState() {
    const subNavItemsContainer = document.getElementById('subNavItems');
    if (!subNavItemsContainer) {
        setTimeout(updatePurchaseSubNavActiveState, 50);
        return;
    }
    
    // When on 'create' page, don't highlight any sub-nav item (it's not a list page)
    if (currentPurchaseSubPage === 'create') {
        subNavItemsContainer.querySelectorAll('.sub-nav-item').forEach(subItem => {
            subItem.classList.remove('active');
        });
        return;
    }
    
    // For list pages (orders, invoices, credit-notes, suppliers), highlight active one
    subNavItemsContainer.querySelectorAll('.sub-nav-item').forEach(subItem => {
        const page = subItem.dataset.page;
        const subPage = subItem.dataset.subPage;
        
        if (page === 'purchases' && subPage === currentPurchaseSubPage) {
            subItem.classList.add('active');
        } else {
            subItem.classList.remove('active');
        }
    });
}

// Show create supplier modal
function showCreateSupplierModal() {
    const content = `
        <form id="createSupplierForm" onsubmit="createSupplier(event)">
            <div class="form-group">
                <label class="form-label">Supplier Name *</label>
                <input type="text" class="form-input" name="name" required placeholder="Enter supplier name">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">PIN</label>
                    <input type="text" class="form-input" name="pin" placeholder="Tax PIN">
                </div>
                <div class="form-group">
                    <label class="form-label">Phone</label>
                    <input type="text" class="form-input" name="phone" placeholder="Phone number">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Email</label>
                <input type="email" class="form-input" name="email" placeholder="Email address">
            </div>
            <div class="form-group">
                <label class="form-label">Contact Person</label>
                <input type="text" class="form-input" name="contact_person" placeholder="Contact person name">
            </div>
            <div class="form-group">
                <label class="form-label">Address</label>
                <textarea class="form-textarea" name="address" rows="2" placeholder="Supplier address"></textarea>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="createSupplierForm">
            <i class="fas fa-save"></i> Create Supplier
        </button>
    `;
    
    showModal('Create New Supplier', content, footer);
}

// Create supplier
async function createSupplier(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const supplierData = {
        company_id: CONFIG.COMPANY_ID,
        name: formData.get('name'),
        pin: formData.get('pin') || null,
        phone: formData.get('phone') || null,
        email: formData.get('email') || null,
        contact_person: formData.get('contact_person') || null,
        address: formData.get('address') || null
    };
    
    try {
        const supplier = await API.suppliers.create(supplierData);
        showToast('Supplier created successfully!', 'success');
        
        // Update supplier search input if on create page
        const supplierSearch = document.getElementById('supplierSearch');
        const supplierIdInput = document.getElementById('supplierId');
        if (supplierSearch && supplierIdInput) {
            supplierSearch.value = supplier.name;
            supplierIdInput.value = supplier.id;
        }
        
        closeModal();
    } catch (error) {
        console.error('Error creating supplier:', error);
        showToast(error.message || 'Error creating supplier', 'error');
    }
}

// Switch purchase sub-page
function switchPurchaseSubPage(subPage) {
    loadPurchaseSubPage(subPage);
}

// Export immediately after definition
if (typeof window !== 'undefined') {
    window.loadPurchaseSubPage = loadPurchaseSubPage;
    window.switchPurchaseSubPage = switchPurchaseSubPage;
}

// Export functions to window IMMEDIATELY
// Export as functions are defined (not waiting for IIFE at end)
if (typeof window !== 'undefined') {
    // Export immediately when script loads
    window.loadPurchases = loadPurchases;
    window.loadPurchaseSubPage = loadPurchaseSubPage;
    window.switchPurchaseSubPage = switchPurchaseSubPage;
    window.createNewPurchaseOrder = createNewPurchaseOrder;
    window.createNewPurchaseInvoice = createNewPurchaseInvoice;
    window.createNewCreditNote = createNewCreditNote;
    window.updatePurchaseSubNavActiveState = updatePurchaseSubNavActiveState;
    window.showCreateSupplierModal = showCreateSupplierModal;
    window.createSupplier = createSupplier;
    window.applyDateFilter = applyDateFilter;
    window.clearDateFilter = clearDateFilter;
    window.applyPurchaseFilters = applyPurchaseFilters;
    window.renderSuppliersPage = renderSuppliersPage;
    window.filterSuppliers = filterSuppliers;
    window.editSupplier = editSupplier;
    window.savePurchaseDocument = savePurchaseDocument;
    window.filterPurchaseDocuments = filterPurchaseDocuments;
    window.showPurchaseFilters = showPurchaseFilters;
    window.viewPurchaseDocument = viewPurchaseDocument;
    window.editPurchaseDocument = editPurchaseDocument;
    window.deletePurchaseOrder = deletePurchaseOrder;
    window.updatePurchaseOrder = updatePurchaseOrder;
    window.printPurchaseOrder = printPurchaseOrder;
    // New Page-Shell First pattern functions
    window.fetchAndRenderPurchaseOrdersData = fetchAndRenderPurchaseOrdersData;
    window.fetchAndRenderPurchaseInvoicesData = fetchAndRenderPurchaseInvoicesData;
    window.fetchAndRenderCreditNotesData = fetchAndRenderCreditNotesData;
    window.renderPurchaseOrdersTableBody = renderPurchaseOrdersTableBody;
    window.renderPurchaseInvoicesTableBody = renderPurchaseInvoicesTableBody;
    window.renderCreditNotesTableBody = renderCreditNotesTableBody;
    window.searchSuppliersInline = searchSuppliersInline;
    window.handleSupplierSearchFocus = handleSupplierSearchFocus;
    window.handleSupplierSearchBlur = handleSupplierSearchBlur;
    window.selectSupplier = selectSupplier;
    window.renderCreatePurchaseOrderPage = renderCreatePurchaseOrderPage;
    window.initializeTransactionItemsTable = initializeTransactionItemsTable;
    
    console.log('✓ Purchases functions exported to window');
}

// Render suppliers page
async function renderSuppliersPage() {
    console.log('renderSuppliersPage() called');
    const page = document.getElementById('purchases');
    if (!page) {
        console.error('Purchases page element not found!');
        return;
    }
    
    // Render page shell
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-truck"></i> Suppliers
                </h3>
                <button class="btn btn-primary" onclick="if(window.showCreateSupplierModal) window.showCreateSupplierModal()">
                    <i class="fas fa-plus"></i> New Supplier
                </button>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1.5rem;">
                    <input type="text" 
                           class="form-input" 
                           id="supplierSearchInput" 
                           placeholder="Search suppliers by name, phone, email..." 
                           onkeyup="if(window.filterSuppliers) window.filterSuppliers()"
                           style="width: 100%; max-width: 500px; padding: 0.75rem;">
                </div>
                
                <div id="suppliersTable">
                    <div class="spinner"></div>
                </div>
            </div>
        </div>
    `;
    
    // Load suppliers from API
    await loadSuppliers();
    
    // Render table
    renderSuppliersTable();
}

// Load suppliers from API
async function loadSuppliers() {
    try {
        if (!window.CONFIG || !window.CONFIG.COMPANY_ID) {
            console.warn('Company ID not configured');
            allSuppliers = [];
            return;
        }
        
        if (!window.API || !window.API.suppliers || !window.API.suppliers.list) {
            console.error('API.suppliers.list not available');
            allSuppliers = [];
            return;
        }
        
        console.log('Loading suppliers for company:', window.CONFIG.COMPANY_ID);
        allSuppliers = await window.API.suppliers.list(window.CONFIG.COMPANY_ID);
        console.log('✅ Loaded suppliers:', allSuppliers.length);
    } catch (error) {
        console.error('❌ Error loading suppliers:', error);
        console.error('Error details:', error.message);
        allSuppliers = [];
    }
}

// Render suppliers table
function renderSuppliersTable() {
    const container = document.getElementById('suppliersTable');
    if (!container) return;
    
    if (!allSuppliers || allSuppliers.length === 0) {
        container.innerHTML = `
            <div class="text-center" style="padding: 3rem;">
                <i class="fas fa-truck" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                <p style="color: var(--text-secondary);">No suppliers found</p>
                <p style="color: var(--text-secondary); font-size: 0.875rem;">Click "New Supplier" to create your first supplier</p>
            </div>
        `;
        return;
    }
    
    const searchTerm = document.getElementById('supplierSearchInput')?.value.toLowerCase() || '';
    const filtered = allSuppliers.filter(supplier => {
        if (!searchTerm) return true;
        const name = (supplier.name || '').toLowerCase();
        const phone = (supplier.phone || '').toLowerCase();
        const email = (supplier.email || '').toLowerCase();
        const contactPerson = (supplier.contact_person || '').toLowerCase();
        return name.includes(searchTerm) || phone.includes(searchTerm) || 
               email.includes(searchTerm) || contactPerson.includes(searchTerm);
    });
    
    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="text-center" style="padding: 3rem;">
                <i class="fas fa-truck" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                <p style="color: var(--text-secondary);">No suppliers found</p>
                <p style="color: var(--text-secondary); font-size: 0.875rem;">Click "New Supplier" to create your first supplier</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = `
        <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto; position: relative;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <tr>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Name</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Contact Person</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Phone</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Email</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">PIN</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Credit Terms</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${filtered.map(supplier => `
                        <tr>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                <strong>${escapeHtml(supplier.name)}</strong>
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                ${escapeHtml(supplier.contact_person || '—')}
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                ${escapeHtml(supplier.phone || '—')}
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                ${escapeHtml(supplier.email || '—')}
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                ${escapeHtml(supplier.pin || '—')}
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                ${supplier.credit_terms ? `${supplier.credit_terms} days` : '—'}
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                <span class="badge ${supplier.is_active ? 'badge-success' : 'badge-danger'}">
                                    ${supplier.is_active ? 'Active' : 'Inactive'}
                                </span>
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                <button class="btn btn-outline" onclick="editSupplier('${supplier.id}')" title="Edit">
                                    <i class="fas fa-edit"></i>
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

// Filter suppliers
function filterSuppliers() {
    renderSuppliersTable();
}

// Helper function for HTML escaping
function escapeHtml(text) {
    if (!text) return '—';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Edit supplier (placeholder)
function editSupplier(supplierId) {
    // TODO: Implement supplier editing
    showToast('Supplier editing coming soon', 'info');
}

// Verify exports at end of file (after all exports are done)
if (typeof window !== 'undefined') {
    // This runs after the main export block at line 1827-1867
    console.log('✓ Purchases functions final verification');
    console.log('  - window.loadPurchases:', typeof window.loadPurchases);
    console.log('  - window.createNewPurchaseOrder:', typeof window.createNewPurchaseOrder);
    console.log('  - window.loadPurchaseSubPage:', typeof window.loadPurchaseSubPage);
}