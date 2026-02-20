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
        case 'create-invoice':
            await renderCreateSupplierInvoicePage();
            break;
        case 'invoices':
            await renderSupplierInvoicesPage();
            break;
        case 'credit-notes':
            await renderCreditNotesPage();
            break;
        case 'suppliers':
            await renderSuppliersPage();
            break;
        case 'order-book':
            await renderOrderBookPage();
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
        // Silently return if we're not on the orders page (prevents error when on invoices page)
        if (currentPurchaseSubPage !== 'orders') {
            return;
        }
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
        const isPending = statusText === 'PENDING';
        const rowClickHandler = isPending && window.editPurchaseDocument
            ? `if(window.editPurchaseDocument) window.editPurchaseDocument('${doc.id}', '${docType}')`
            : `if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', '${docType}')`;
        const linkClickHandler = isPending && window.editPurchaseDocument
            ? `event.stopPropagation(); if(window.editPurchaseDocument) window.editPurchaseDocument('${doc.id}', '${docType}'); return false;`
            : `event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', '${docType}'); return false;`;
        return `
            <tr style="cursor: pointer;" onclick="${rowClickHandler}">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <strong style="color: var(--primary-color); cursor: pointer; text-decoration: underline;" 
                            onclick="${linkClickHandler}"
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
// PAGE-SHELL FIRST PATTERN: Supplier Invoices
// =====================================================

function renderSupplierInvoicesShell() {
    console.log('renderSupplierInvoicesShell() called');
    const page = document.getElementById('purchases');
    if (!page) return;
    
    const today = new Date().toISOString().split('T')[0];
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice-dollar"></i> Supplier Invoices
                    <span style="font-size: 0.875rem; color: var(--text-secondary); margin-left: 0.5rem; font-weight: normal;">
                        (Receiving Documents - Add Stock)
                    </span>
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="if(window.showPurchaseFilters) window.showPurchaseFilters()">
                        <i class="fas fa-filter"></i> Filters
                    </button>
                    <button class="btn btn-primary" onclick="if(window.createNewSupplierInvoice) window.createNewSupplierInvoice()">
                        <i class="fas fa-plus"></i> New Supplier Invoice
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
                           placeholder="Search by supplier invoice number, supplier..." 
                           onkeyup="if(window.filterPurchaseDocuments) window.filterPurchaseDocuments()"
                           style="width: 100%; max-width: 500px; padding: 0.75rem;">
                </div>
                
                <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto; position: relative;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <tr>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Supplier Invoice #</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Date</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Total</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Paid</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Balance</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Supplier</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="supplierInvoicesTableBody">
                            <tr>
                                <td colspan="6" style="padding: 3rem; text-align: center;">
                                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading supplier invoices...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    console.log('✅ Supplier Invoices shell rendered');
}

async function fetchAndRenderSupplierInvoicesData() {
    const tbody = document.getElementById('supplierInvoicesTableBody');
    if (!tbody) return;
    
    try {
        await loadPurchaseDocuments('invoice');
        renderSupplierInvoicesTableBody();
    } catch (error) {
        console.error('Error fetching invoices:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                    <p style="color: var(--danger-color);">Error loading invoices</p>
                    <button class="btn btn-outline" onclick="if(window.fetchAndRenderSupplierInvoicesData) window.fetchAndRenderSupplierInvoicesData()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </td>
            </tr>
        `;
    }
}

function renderSupplierInvoicesTableBody() {
    const tbody = document.getElementById('supplierInvoicesTableBody');
    if (!tbody) return;
    
    if (purchaseDocuments.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-file-invoice-dollar" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No supplier invoices found</p>
                    <button class="btn btn-primary" onclick="if(window.createNewSupplierInvoice) window.createNewSupplierInvoice()">
                        <i class="fas fa-plus"></i> Create Your First Supplier Invoice
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = purchaseDocuments.map(doc => {
        const docStatus = doc.status || 'DRAFT';
        const paymentStatus = doc.payment_status || 'UNPAID';
        const total = parseFloat(doc.total_inclusive || doc.total_amount || 0);
        const paid = parseFloat(doc.amount_paid || 0);
        const balance = parseFloat(doc.balance || (total - paid));
        
        // Status badge colors
        const docStatusClass = docStatus === 'BATCHED' ? 'badge-success' : 'badge-warning';
        const paymentStatusClass = paymentStatus === 'PAID' ? 'badge-success' : 
                                   paymentStatus === 'PARTIAL' ? 'badge-info' : 'badge-danger';
        
        return `
            <tr style="cursor: pointer;" onclick="if(window.viewSupplierInvoice) window.viewSupplierInvoice('${doc.id}')">
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <a href="#" onclick="event.stopPropagation(); if(window.viewSupplierInvoice) window.viewSupplierInvoice('${doc.id}'); return false;" 
                       style="color: var(--primary-color); font-weight: 600; text-decoration: none;">
                        ${doc.invoice_number || '—'}
                    </a>
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(doc.invoice_date || doc.created_at)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>${formatCurrency(total)}</strong></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatCurrency(paid)}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong style="color: ${balance > 0 ? 'var(--danger-color)' : 'var(--success-color)'}">${formatCurrency(balance)}</strong></td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${doc.supplier_name || '—'}</td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    <span class="badge ${docStatusClass}" title="Document: ${docStatus}">${docStatus}</span>
                    <span class="badge ${paymentStatusClass}" title="Payment: ${paymentStatus}" style="margin-left: 0.25rem;">${paymentStatus}</span>
                </td>
                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                    ${docStatus === 'DRAFT' ? `
                        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); if(window.batchSupplierInvoice) window.batchSupplierInvoice('${doc.id}')" title="Batch Invoice (Add Stock)">
                            <i class="fas fa-boxes"></i> Batch
                        </button>
                    ` : ''}
                    <button class="btn btn-outline btn-sm" onclick="event.stopPropagation(); if(window.updateInvoicePayment) window.updateInvoicePayment('${doc.id}', ${total}, ${paid})" title="Update Payment">
                        <i class="fas fa-money-bill-wave"></i>
                    </button>
                    <button class="btn btn-outline btn-sm" onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', 'invoice')" title="View">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

async function renderSupplierInvoicesPage() {
    renderSupplierInvoicesShell();
    await fetchAndRenderSupplierInvoicesData();
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
            // Load supplier invoices (these are receiving documents that ADD STOCK)
            const params = {
                company_id: CONFIG.COMPANY_ID
            };
            if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
            if (dateFrom) params.date_from = dateFrom;
            if (dateTo) params.date_to = dateTo;
            if (supplierId) params.supplier_id = supplierId;
            
            purchaseDocuments = await API.purchases.listInvoices(params);
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

// Clear date filters to show all invoices (used when navigating from stock take)
function clearPurchaseDateFilters() {
    console.log('[PURCHASES] Clearing date filters to show all invoices');
    const dateFromEl = document.getElementById('filterDateFrom');
    const dateToEl = document.getElementById('filterDateTo');
    if (dateFromEl) {
        dateFromEl.value = '';
        console.log('[PURCHASES] Cleared dateFrom filter');
    }
    if (dateToEl) {
        dateToEl.value = '';
        console.log('[PURCHASES] Cleared dateTo filter');
    }
    
    // Reload invoices without date filters
    if (currentPurchaseSubPage === 'invoices') {
        console.log('[PURCHASES] Reloading invoices without date filters');
        setTimeout(() => {
            fetchAndRenderSupplierInvoicesData();
        }, 300);
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
            const ordersTbody = document.getElementById('purchaseOrdersTableBody');
            if (ordersTbody) {
                renderPurchaseOrdersTableBody();
            }
            break;
        case 'invoices':
            const invoicesTbody = document.getElementById('supplierInvoicesTableBody');
            if (invoicesTbody) {
                renderSupplierInvoicesTableBody();
            }
            break;
        case 'credit-notes':
            const creditNotesTbody = document.getElementById('creditNotesTableBody');
            if (creditNotesTbody) {
                renderCreditNotesTableBody();
            }
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
                renderSupplierInvoicesTableBody();
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
                renderSupplierInvoicesTableBody();
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

// Create new Supplier Invoice (RECEIVING document - ADDS STOCK)
function createNewSupplierInvoice() {
    currentDocument = { type: 'invoice', items: [] };
    documentItems = [];
    // Navigate to create page with invoice mode
    loadPurchaseSubPage('create-invoice');
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
    
    // Get order status for button visibility
    const orderStatus = currentDocument?.status || 'PENDING';
    const canEdit = orderStatus === 'PENDING';
    
    // Prepare buttons for top bar based on mode and status
    const topButtonsHtml = isEditMode ? `
        ${canEdit ? `
            <button type="button" class="btn btn-primary btn-save-order" onclick="if(window.updatePurchaseOrder) { const form = document.getElementById('purchaseDocumentForm'); if(form) updatePurchaseOrder({preventDefault:()=>{},target:form}, '${orderId}'); }">
                <i class="fas fa-save"></i> Update Order
            </button>
            <button type="button" class="btn btn-outline btn-danger" onclick="if(window.deletePurchaseOrder) window.deletePurchaseOrder('${orderId}')" title="Delete Order (Only for PENDING)">
                <i class="fas fa-trash"></i> Delete
            </button>
        ` : `
            <button type="button" class="btn btn-outline btn-danger" disabled title="Cannot delete order with status ${orderStatus}">
                <i class="fas fa-trash"></i> Delete (Disabled)
            </button>
            <span style="color: var(--text-secondary); font-size: 0.875rem; align-self: center; margin-left: 0.5rem;">
                Order is ${orderStatus} - cannot be edited or deleted
            </span>
        `}
        <button type="button" class="btn btn-outline" onclick="if(window.printPurchaseOrder) window.printPurchaseOrder('${orderId}')" title="Print">
            <i class="fas fa-print"></i> Print
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadPurchaseSubPage('orders')">
            <i class="fas fa-arrow-left"></i> Back
        </button>
    ` : `
        <button type="submit" class="btn btn-primary" form="purchaseDocumentForm">
            <i class="fas fa-save"></i> Save Order
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadPurchaseSubPage('orders')">
            <i class="fas fa-arrow-left"></i> Back
        </button>
    `;
    
    page.innerHTML = `
        <div class="card" id="purchaseOrderDocumentCard" style="transform-origin: top left; transition: transform 0.2s;">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border-color); position: sticky; top: 0; background: white; z-index: 10;">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <h3 class="card-title" style="margin: 0; font-size: 1.25rem;">
                        <i class="fas fa-file-invoice"></i> ${isEditMode ? 'Edit' : 'Create'} Purchase Order
                        ${isEditMode && currentDocument.order_number ? `: ${currentDocument.order_number}` : ''}
                    </h3>
                    <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                        <button type="button" class="btn btn-outline btn-sm" onclick="zoomDocumentView('out')" title="Zoom Out (Ctrl + Mouse Wheel)">
                            <i class="fas fa-search-minus"></i>
                        </button>
                        <span id="documentZoomLevel" style="min-width: 60px; text-align: center;">100%</span>
                        <button type="button" class="btn btn-outline btn-sm" onclick="zoomDocumentView('in')" title="Zoom In (Ctrl + Mouse Wheel)">
                            <i class="fas fa-search-plus"></i>
                        </button>
                        <button type="button" class="btn btn-outline btn-sm" onclick="zoomDocumentView('reset')" title="Reset Zoom">
                            <i class="fas fa-undo"></i>
                        </button>
                    </div>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    ${topButtonsHtml}
                </div>
            </div>
            
            <div class="card-body" style="padding: 1rem; max-height: calc(100vh - 200px); overflow-y: auto;">
                <form id="purchaseDocumentForm" ${isEditMode ? '' : 'onsubmit="savePurchaseDocument(event, \'order\')"'} >
                    <!-- Document Header -->
                    <div class="card" style="margin-bottom: 1rem;">
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
                                               ${canEdit ? '' : 'disabled'}
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
                                           value="${today}" 
                                           ${canEdit ? '' : 'disabled'}
                                           required>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">Reference</label>
                                    <input type="text" class="form-input" name="reference" 
                                           placeholder="Order reference"
                                           ${canEdit ? '' : 'disabled'}>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Notes</label>
                                    <input type="text" class="form-input" name="notes" 
                                           placeholder="Additional notes"
                                           ${canEdit ? '' : 'disabled'}>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table (Vyapar-style, table-driven) -->
                    <div class="card" style="margin-bottom: 1rem;">
                        <div class="card-header" style="padding: 0.75rem 1rem;">
                            <h4 style="margin: 0; font-size: 1rem;">Items</h4>
                        </div>
                        <div class="card-body" id="transactionItemsContainer" style="padding: 0.5rem;">
                            <!-- TransactionItemsTable component will render here -->
                        </div>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize TransactionItemsTable component with edit permission
    initializeTransactionItemsTable(canEdit);
    
    // Set up zoom functionality
    setupDocumentZoom();
    
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

// Render Create Supplier Invoice Page (RECEIVING document - ADDS STOCK)
async function renderCreateSupplierInvoicePage() {
    console.log('renderCreatePurchaseInvoicePage()');
    
    const page = document.getElementById('purchases');
    if (!page) {
        console.error('Purchases page element not found!');
        return;
    }
    
    // Check if we're in edit mode
    const isEditMode = currentDocument && currentDocument.mode === 'edit' && currentDocument.invoiceId;
    let invoiceData = isEditMode ? currentDocument.invoiceData : null;
    
    // Initialize document state
    if (!currentDocument) {
        currentDocument = { type: 'invoice', items: [] };
    }
    
    // If edit mode, load invoice data if not already loaded
    if (isEditMode && !invoiceData) {
        try {
            invoiceData = await API.purchases.getInvoice(currentDocument.invoiceId);
            currentDocument.invoiceData = invoiceData;
        } catch (error) {
            console.error('Error loading invoice for edit:', error);
            showToast('Error loading invoice data', 'error');
            // Fall back to create mode
            currentDocument = { type: 'invoice', items: [] };
            documentItems = [];
            invoiceData = null;
        }
    }
    
    // Populate items from invoice (whether just loaded or already in currentDocument)
    if (isEditMode && invoiceData && invoiceData.items && invoiceData.items.length > 0) {
        documentItems = invoiceData.items.map(item => {
            let batches = null;
            if (item.batch_data) {
                try {
                    batches = JSON.parse(item.batch_data);
                } catch (e) {
                    console.warn('Error parsing batch_data:', e);
                }
            }
            return {
                item_id: item.item_id,
                item_name: item.item_name || item.item?.name || 'Item',
                item_sku: item.item_code || item.item?.sku || '',
                item_code: item.item_code || item.item?.sku || '',
                quantity: parseFloat(item.quantity),
                unit_name: item.unit_name,
                unit_price: parseFloat(item.unit_cost_exclusive),
                tax_percent: parseFloat(item.vat_rate),
                discount_percent: 0,
                total: parseFloat(item.line_total_inclusive),
                batches: batches
            };
        });
    } else if (!isEditMode) {
        // Initialize empty items array for new invoice
        documentItems = [];
    }
    
    const today = invoiceData ? invoiceData.invoice_date : new Date().toISOString().split('T')[0];
    const supplierId = invoiceData ? invoiceData.supplier_id : '';
    const supplierName = invoiceData ? invoiceData.supplier_name : '';
    const supplierInvoiceNumber = invoiceData ? invoiceData.reference : '';
    const reference = invoiceData ? invoiceData.reference : '';
    
    page.innerHTML = `
        <div class="card" id="supplierInvoiceDocumentCard" style="transform-origin: top left; transition: transform 0.2s;">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border-color); position: sticky; top: 0; background: white; z-index: 10;">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <h3 class="card-title" style="margin: 0; font-size: 1.25rem;">
                        <i class="fas fa-file-invoice"></i> ${isEditMode && invoiceData && invoiceData.invoice_number ? `Edit Supplier Invoice: ${invoiceData.invoice_number}` : 'Create Supplier Invoice'}
                        <span style="font-size: 0.875rem; color: var(--text-secondary); margin-left: 0.5rem;">
                            (Receiving Document - Adds Stock)
                        </span>
                    </h3>
                    <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                        <button type="button" class="btn btn-outline btn-sm" onclick="zoomDocumentView('out', 'supplierInvoiceDocumentCard')" title="Zoom Out (Ctrl + Mouse Wheel)">
                            <i class="fas fa-search-minus"></i>
                        </button>
                        <span id="supplierInvoiceZoomLevel" style="min-width: 60px; text-align: center;">100%</span>
                        <button type="button" class="btn btn-outline btn-sm" onclick="zoomDocumentView('in', 'supplierInvoiceDocumentCard')" title="Zoom In (Ctrl + Mouse Wheel)">
                            <i class="fas fa-search-plus"></i>
                        </button>
                        <button type="button" class="btn btn-outline btn-sm" onclick="zoomDocumentView('reset', 'supplierInvoiceDocumentCard')" title="Reset Zoom">
                            <i class="fas fa-undo"></i>
                        </button>
                    </div>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    ${isEditMode && invoiceData ? `
                        ${invoiceData.status === 'DRAFT' ? `
                            <button type="button" class="btn btn-primary" onclick="if(window.batchSupplierInvoice) window.batchSupplierInvoice('${invoiceData.id}')" title="Batch Invoice (Add Stock)">
                                <i class="fas fa-boxes"></i> Batch Invoice
                            </button>
                            <button type="button" class="btn btn-outline btn-danger" onclick="if(window.deleteSupplierInvoice) window.deleteSupplierInvoice('${invoiceData.id}')" title="Delete Invoice (Only for DRAFT)">
                                <i class="fas fa-trash"></i> Delete
                            </button>
                        ` : `
                            <button type="button" class="btn btn-outline btn-danger" disabled title="Cannot delete BATCHED invoice (stock already added)">
                                <i class="fas fa-trash"></i> Delete (Disabled)
                            </button>
                            <span style="color: var(--text-secondary); font-size: 0.875rem; align-self: center; margin-left: 0.5rem;">
                                Invoice is BATCHED - cannot be deleted
                            </span>
                        `}
                    ` : ''}
                    <button type="submit" class="btn btn-primary" form="purchaseInvoiceForm" ${isEditMode && invoiceData && invoiceData.status === 'BATCHED' ? 'disabled title="BATCHED invoices cannot be updated"' : ''}>
                        <i class="fas fa-save"></i> ${isEditMode ? 'Update' : 'Save'} Invoice
                    </button>
                    <button type="button" class="btn btn-secondary" onclick="loadPurchaseSubPage('invoices')">
                        <i class="fas fa-arrow-left"></i> Back
                    </button>
                </div>
            </div>
            
            <div class="card-body" style="padding: 1rem; max-height: calc(100vh - 200px); overflow-y: auto;">
                <form id="purchaseInvoiceForm" onsubmit="savePurchaseDocument(event, 'invoice')">
                    <!-- Document Header -->
                    <div class="card" style="margin-bottom: 1rem;">
                        <div class="card-header">
                            <h4>Invoice Details</h4>
                        </div>
                        <div class="card-body">
                            <div class="form-row">
                                <div class="form-group" style="flex: 1;">
                                    <label class="form-label">Supplier *</label>
                                    <div style="position: relative;">
                                        <input type="text" 
                                               class="form-input" 
                                               id="supplierSearchInvoice" 
                                               placeholder="Search supplier by name..."
                                               autocomplete="off"
                                               required
                                               onkeyup="searchSuppliersInline(event, 'supplierSearchInvoice', 'supplierIdInvoice', 'supplierSearchDropdownInvoice')"
                                               onfocus="handleSupplierSearchFocus(event)"
                                               onblur="handleSupplierSearchBlur(event)">
                                        <input type="hidden" name="supplier_id" id="supplierIdInvoice" required>
                                        <div id="supplierSearchDropdownInvoice" 
                                             style="position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid var(--border-color); border-radius: 0.25rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 1000; max-height: 300px; overflow-y: auto; display: none; margin-top: 0.25rem;">
                                        </div>
                                    </div>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Invoice Date *</label>
                                    <input type="date" class="form-input" name="document_date" 
                                           value="${today}" required>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">Supplier's Invoice Number</label>
                                    <input type="text" class="form-input" name="supplier_invoice_number" 
                                           value="${supplierInvoiceNumber || ''}"
                                           placeholder="Enter supplier's invoice number (optional)">
                                    <small style="color: var(--text-secondary); font-size: 0.75rem; display: block; margin-top: 0.25rem;">
                                        Optional: Invoice number from your supplier. System will auto-generate our document number.
                                    </small>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Reference / Comments</label>
                                    <input type="text" class="form-input" name="reference" 
                                           value="${reference || ''}"
                                           placeholder="Optional reference or comments">
                                </div>
                            </div>
                            <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0.25rem 0 0 0;">
                                VAT is per item (from item master). Total VAT is the sum of each line&apos;s VAT.
                            </p>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table (Vyapar-style, table-driven) -->
                    <div class="card" style="margin-bottom: 1rem;">
                        <div class="card-header" style="padding: 0.75rem 1rem;">
                            <h4 style="margin: 0; font-size: 1rem;">Items Received</h4>
                            <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0.25rem 0 0 0;">
                                Use "Manage Batches" button to distribute items across multiple batches
                            </p>
                        </div>
                        <div class="card-body" id="transactionItemsContainerInvoice" style="padding: 0.5rem;">
                            <!-- TransactionItemsTable component will render here -->
                        </div>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize TransactionItemsTable component for invoice
    initializeTransactionItemsTableForInvoice();
    
    // Set up zoom functionality for Supplier Invoice
    setupDocumentZoom('supplierInvoiceDocumentCard', 'supplierInvoiceZoomLevel');
    
    // If in edit mode, populate supplier field
    if (isEditMode && invoiceData && supplierId) {
        setTimeout(() => {
            const supplierSearchInput = document.getElementById('supplierSearchInvoice');
            const supplierHiddenInput = document.getElementById('supplierIdInvoice');
            if (supplierSearchInput && supplierHiddenInput) {
                supplierSearchInput.value = supplierName || '';
                supplierHiddenInput.value = supplierId;
            }
        }, 100);
    }
}

// Initialize TransactionItemsTable component for Invoice
function initializeTransactionItemsTableForInvoice() {
    const container = document.getElementById('transactionItemsContainerInvoice');
    if (!container) {
        setTimeout(initializeTransactionItemsTableForInvoice, 100);
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
            batches: item.batches || [],
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
                total: item.total,
                batches: item.batches || []
            }));
            
            // Auto-save when items change (if in edit mode and invoice is DRAFT)
            if (currentDocument && currentDocument.mode === 'edit' && currentDocument.invoiceId) {
                const invoiceData = currentDocument.invoiceData;
                if (invoiceData && invoiceData.status === 'DRAFT' && validItems.length > 0) {
                    // Debounce auto-save to avoid too many requests
                    clearTimeout(window.autoSaveTimeout);
                    window.autoSaveTimeout = setTimeout(() => {
                        autoSaveInvoice();
                    }, 2000); // Auto-save 2 seconds after last change
                }
            }
        },
        onTotalChange: (total) => {
            console.log('Total changed:', total);
        },
        onItemCreate: (query, rowIndex, callback) => {
            window._transactionItemCreateCallback = callback;
            window._transactionItemCreateRowIndex = rowIndex;
            if (query) {
                window._transactionItemCreateName = query;
            }
            if (typeof showAddItemModal === 'function') {
                showAddItemModal();
                setTimeout(() => {
                    const nameInput = document.querySelector('#itemForm input[name="name"]');
                    if (nameInput && query) {
                        nameInput.value = query;
                    }
                }, 100);
            } else {
                showToast(`To create item "${query}", please go to Items page`, 'info');
            }
        }
    });
    
    // Expose to window for component callbacks
    window[`transactionTable_transactionItemsContainerInvoice`] = transactionItemsTable;
}

// Initialize TransactionItemsTable component
let transactionItemsTable = null;

function initializeTransactionItemsTable(canEdit = true) {
    const container = document.getElementById('transactionItemsContainer');
    if (!container) {
        setTimeout(() => initializeTransactionItemsTable(canEdit), 100);
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
    // Set context to 'purchase_order' for Purchase Order specific fields
    transactionItemsTable = new window.TransactionItemsTable({
        mountEl: container,
        mode: 'purchase',
        context: 'purchase_order', // Enable PO-specific fields (last order date, last supply date, etc.)
        items: items,
        priceType: 'purchase_price',
        canEdit: canEdit, // Pass edit permission to component
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
            
            // Auto-save when items change (if in edit mode and order is PENDING)
            if (currentDocument && currentDocument.id && currentDocument.status === 'PENDING') {
                // Debounce auto-save to avoid too many requests
                clearTimeout(window.autoSaveOrderTimeout);
                window.autoSaveOrderTimeout = setTimeout(() => {
                    autoSavePurchaseOrder();
                }, 2000); // Auto-save 2 seconds after last change
            }
        },
        onTotalChange: (total) => {
            // Update total display (if needed elsewhere)
            console.log('Total changed:', total);
        },
        onItemCreate: (query, rowIndex, callback) => {
            // Store callback for when item is created
            window._transactionItemCreateCallback = callback;
            window._transactionItemCreateRowIndex = rowIndex;
            // Pre-fill item name if provided
            if (query) {
                window._transactionItemCreateName = query;
            }
            // Use the existing item creation modal from items page
            if (typeof showAddItemModal === 'function') {
                showAddItemModal();
                // Pre-fill the name field if query is provided
                setTimeout(() => {
                    const nameInput = document.querySelector('#itemForm input[name="name"]');
                    if (nameInput && query) {
                        nameInput.value = query;
                    }
                }, 100);
            } else {
                showToast(`To create item "${query}", please go to Items page`, 'info');
            }
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

async function searchSuppliersInline(event, searchInputId = 'supplierSearch', hiddenInputId = 'supplierId', dropdownId = 'supplierSearchDropdown') {
    const query = event.target.value.trim();
    const dropdown = document.getElementById(dropdownId);
    const hiddenInput = document.getElementById(hiddenInputId);
    
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
        renderSupplierSearchResults(cached.data, dropdown, searchInputId, hiddenInputId, dropdownId);
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
            
            renderSupplierSearchResults(suppliers, dropdown, searchInputId, hiddenInputId, dropdownId);
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
function renderSupplierSearchResults(suppliers, dropdown, searchInputId = 'supplierSearch', hiddenInputId = 'supplierId', dropdownId = 'supplierSearchDropdown') {
    if (suppliers.length === 0) {
        dropdown.innerHTML = `
            <div style="padding: 1rem; text-align: center; color: var(--text-secondary);">
                <p style="margin: 0 0 0.5rem 0;">No suppliers found</p>
                <a href="#" onclick="event.preventDefault(); closeSupplierDropdown('${dropdownId}'); showCreateSupplierModal(); return false;" 
                   style="color: var(--primary-color); font-weight: 600; text-decoration: none;">
                    <i class="fas fa-plus"></i> Create New Supplier
                </a>
            </div>
        `;
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
                 onclick="selectSupplier('${supplier.id}', '${escapeHtml(supplier.name)}', '${searchInputId}', '${hiddenInputId}', '${dropdownId}')">
                <strong>${escapeHtml(supplier.name)}</strong>
            </div>
        `;
    }).join('');
    
    dropdown.style.display = 'block';
}

// Close supplier dropdown (used when opening Create Supplier modal from "no results")
function closeSupplierDropdown(dropdownId) {
    const dropdown = document.getElementById(dropdownId);
    if (dropdown) dropdown.style.display = 'none';
}

// Select supplier from search (works with both order and invoice forms)
function selectSupplier(supplierId, supplierName, searchInputId = 'supplierSearch', hiddenInputId = 'supplierId', dropdownId = 'supplierSearchDropdown') {
    const searchInput = document.getElementById(searchInputId);
    const hiddenInput = document.getElementById(hiddenInputId);
    const dropdown = document.getElementById(dropdownId);
    
    if (searchInput) searchInput.value = supplierName;
    if (hiddenInput) hiddenInput.value = supplierId;
    if (dropdown) dropdown.style.display = 'none';
    
    // Focus back on search input for quick entry
    if (searchInput) searchInput.focus();
}

// Removed handleItemSearchFocus/handleItemSearchBlur - now handled by TransactionItemsTable component

// Handle supplier search focus (works with both order and invoice forms)
function handleSupplierSearchFocus(event) {
    const inputId = event.target.id;
    const dropdownId = inputId.includes('Invoice') ? 'supplierSearchDropdownInvoice' : 'supplierSearchDropdown';
    const query = event.target.value.trim();
    if (query.length >= 2) {
        const dropdown = document.getElementById(dropdownId);
        if (dropdown && dropdown.innerHTML.trim() !== '') {
            dropdown.style.display = 'block';
        }
    }
}

// Handle supplier search blur (with delay to allow click) - works with both forms
function handleSupplierSearchBlur(event) {
    const inputId = event.target.id;
    const dropdownId = inputId.includes('Invoice') ? 'supplierSearchDropdownInvoice' : 'supplierSearchDropdown';
    setTimeout(() => {
        const dropdown = document.getElementById(dropdownId);
        if (dropdown) dropdown.style.display = 'none';
    }, 200);
}

// Create PO from Order Book modal: re-show supplier results on focus when user has typed 2+ chars
function handlePOFromBookSupplierFocus(event) {
    if (event.target.id !== 'poFromBookSupplierSearch') return;
    const q = (event.target.value || '').trim();
    if (q.length >= 2 && typeof searchSuppliersInline === 'function') {
        searchSuppliersInline(event, 'poFromBookSupplierSearch', 'poFromBookSupplierId', 'poFromBookSupplierDropdown');
    }
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
            items: items.map(item => {
                const itemData = {
                    item_id: item.item_id,
                    unit_name: item.unit_name,
                    quantity: item.quantity,
                    unit_price: item.unit_price,
                    total_price: item.total
                };
                
                // Include batch distribution if available
                if (item.batches && Array.isArray(item.batches) && item.batches.length > 0) {
                    itemData.batches = item.batches.map(batch => ({
                        batch_number: batch.batch_number || '',
                        expiry_date: batch.expiry_date || null,
                        quantity: parseFloat(batch.quantity) || 0,
                        unit_cost: parseFloat(batch.unit_cost) || 0
                    }));
                }
                
                return itemData;
            })
        };
        
        let result;
        if (documentType === 'order') {
            // Purchase Order: Just a request document, NO STOCK EFFECT
            result = await API.purchases.createOrder(documentData);
            showToast('Purchase Order saved successfully! (No stock added)', 'success');
        } else if (documentType === 'invoice') {
            // Supplier Invoice: RECEIVING document that ADDS STOCK
            // Validate supplier_id
            const supplierId = formData.get('supplier_id');
            if (!supplierId) {
                isSavingDocument = false;
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.innerHTML = '<i class="fas fa-save"></i> Save & Add Stock';
                }
                showToast('Please select a supplier', 'error');
                return;
            }
            
            // Convert items to invoice format with batch support
            const invoiceData = {
                company_id: CONFIG.COMPANY_ID,
                branch_id: CONFIG.BRANCH_ID,
                supplier_id: supplierId,
                supplier_invoice_number: formData.get('supplier_invoice_number') || null,  // Supplier's invoice number (external)
                reference: formData.get('reference') || null,  // Additional reference/comments
                invoice_date: formData.get('document_date') || new Date().toISOString().split('T')[0],
                linked_grn_id: formData.get('linked_grn_id') || null,
                vat_rate: 0,  // Display only; total VAT = sum of line VATs (item-based)
                created_by: currentUserId,
                items: items.map(item => {
                    // VAT is item-based (from item master). Total VAT = sum of line VATs.
                    const itemData = {
                        item_id: item.item_id,
                        unit_name: item.unit_name,
                        quantity: item.quantity,
                        unit_cost_exclusive: item.unit_price, // Supplier invoice uses exclusive cost
                        vat_rate: item.tax_percent != null && item.tax_percent !== '' ? Number(item.tax_percent) : 0
                    };
                    
                    // Include batch distribution if available
                    if (item.batches && Array.isArray(item.batches) && item.batches.length > 0) {
                        itemData.batches = item.batches.map(batch => ({
                            batch_number: batch.batch_number || '',
                            expiry_date: batch.expiry_date || null,
                            quantity: parseFloat(batch.quantity) || 0,
                            unit_cost: parseFloat(batch.unit_cost) || 0
                        }));
                    }
                    
                    return itemData;
                })
            };
            
            console.log('📤 [Supplier Invoice] Submitting invoice data:', {
                supplier_id: invoiceData.supplier_id,
                invoice_number: invoiceData.invoice_number,
                items_count: invoiceData.items.length,
                items: invoiceData.items.map(item => ({
                    item_id: item.item_id,
                    quantity: item.quantity,
                    has_batches: !!(item.batches && item.batches.length > 0)
                }))
            });
            
            // Check if we're updating an existing invoice
            const isEditMode = currentDocument && currentDocument.mode === 'edit' && currentDocument.invoiceId;
            
            let result;
            if (isEditMode) {
                // Update existing invoice
                result = await API.purchases.updateInvoice(currentDocument.invoiceId, invoiceData);
                console.log('✅ [Supplier Invoice] Invoice updated:', result);
                showToast('Supplier Invoice updated successfully!', 'success');
            } else {
                // Create new invoice
                result = await API.purchases.createInvoice(invoiceData);
                console.log('✅ [Supplier Invoice] Invoice saved as DRAFT:', result);
                console.log('📄 [Supplier Invoice] Invoice number:', result?.invoice_number || 'NOT ASSIGNED');
                
                // Store invoice ID and number for auto-save
                if (result && result.id) {
                    currentDocument.invoiceId = result.id;
                    currentDocument.status = result.status || 'DRAFT';
                    currentDocument.invoiceNumber = result.invoice_number; // Store invoice number
                    currentDocument.mode = 'edit'; // Switch to edit mode after first save
                }
                
                if (result && result.invoice_number) {
                    showToast(`Supplier Invoice ${result.invoice_number} saved as DRAFT! Click "Batch Invoice" to add stock to inventory.`, 'success');
                } else {
                    showToast('Supplier Invoice saved as DRAFT! (Note: Invoice number not assigned - check branch code)', 'warning');
                }
            }
        } else {
            showToast('Credit notes not yet implemented', 'info');
            return;
        }
        
        // Reset state
        documentItems = [];
        currentDocument = null;
        transactionItemsTable = null;
        isSavingDocument = false; // Reset flag
        
        // Navigate back and refresh data
        if (documentType === 'order') {
            await loadPurchaseSubPage('orders');
            // Refresh orders list
            await fetchAndRenderPurchaseOrdersData();
        } else if (documentType === 'invoice') {
            // Navigate to invoices page
            await loadPurchaseSubPage('invoices');
            // Explicitly refresh invoices list to ensure new invoice appears
            await fetchAndRenderSupplierInvoicesData();
        }
    } catch (error) {
        console.error('❌ Error saving purchase document:', error);
        console.error('Error details:', {
            message: error.message,
            status: error.status,
            data: error.data
        });
        
        // Show detailed error message
        let errorMessage = error.message || 'Error saving document';
        if (error.data && error.data.detail) {
            if (typeof error.data.detail === 'string') {
                errorMessage = error.data.detail;
            } else if (Array.isArray(error.data.detail)) {
                errorMessage = error.data.detail.map(e => e.msg || e.loc?.join('.') + ': ' + e.msg).join(', ');
            }
        }
        
        showToast(errorMessage, 'error');
        isSavingDocument = false; // Reset flag on error
        if (submitButton) {
            const buttonText = documentType === 'order' ? 'Save Purchase Order' : 'Save & Add Stock';
            submitButton.disabled = false;
            submitButton.innerHTML = `<i class="fas fa-save"></i> ${buttonText}`;
        }
    }
}

// View document
async function viewPurchaseDocument(docId, docType) {
    if (docType === 'invoice') {
        await viewSupplierInvoice(docId);
        return;
    }
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

// Auto-save purchase order (called from onItemsChange debounce) – no toast on success to avoid noise
async function autoSavePurchaseOrder() {
    if (!currentDocument || !currentDocument.id || currentDocument.type !== 'order' || currentDocument.status !== 'PENDING') {
        return;
    }
    const form = document.getElementById('purchaseDocumentForm');
    if (!form) return;
    const syntheticEvent = { preventDefault: function() {}, target: form };
    await updatePurchaseOrder(syntheticEvent, currentDocument.id);
}

// Delete purchase order
async function deletePurchaseOrder(orderId) {
    // Prevent duplicate delete operations
    if (isDeletingOrder) {
        showToast('Delete operation already in progress. Please wait...', 'warning');
        return;
    }
    
    // First check if order is PENDING
    try {
        const order = await API.purchases.getOrder(orderId);
        if (order.status !== 'PENDING') {
            showToast(`Cannot delete order with status ${order.status}. Only PENDING orders can be deleted.`, 'error');
            return;
        }
    } catch (error) {
        console.error('Error checking order status:', error);
        showToast('Error checking order status', 'error');
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
        
        // Clear auto-save timeout if any
        clearTimeout(window.autoSaveOrderTimeout);
        
        // Reset flag
        isDeletingOrder = false;
        
        // If we're on the edit page, navigate back to orders list
        if (currentDocument && currentDocument.id === orderId) {
            currentDocument = null;
            documentItems = [];
            await loadPurchaseSubPage('orders');
        } else {
            // Refresh the orders list
            await fetchAndRenderPurchaseOrdersData();
        }
        
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

// View/Edit Supplier Invoice - Navigate to create page (seamless edit experience)
async function viewSupplierInvoice(invoiceId) {
    try {
        const invoice = await API.purchases.getInvoice(invoiceId);
        const isDraft = invoice.status === 'DRAFT';
        
        if (!isDraft) {
            // For BATCHED invoices, show read-only view with payment update option
            showToast('This invoice is already batched. Only payment can be updated.', 'info');
            // TODO: Could show a read-only view or payment update modal
            return;
        }
        
        // For DRAFT invoices, navigate to edit page (same as create page)
        currentDocument = { 
            type: 'invoice', 
            invoiceId: invoiceId, 
            mode: 'edit',
            invoiceData: invoice  // Store invoice data to populate form
        };
        
        // Navigate to create page (will load as edit mode)
        await loadPurchaseSubPage('create-invoice');
    } catch (error) {
        console.error('Error loading supplier invoice:', error);
        showToast(error.message || 'Error loading invoice', 'error');
    }
}

// Edit Supplier Invoice (only DRAFT) - Same as view, navigates to create page
async function editSupplierInvoice(invoiceId) {
    await viewSupplierInvoice(invoiceId);
}

// Delete Supplier Invoice (only DRAFT)
async function deleteSupplierInvoice(invoiceId) {
    // First check if invoice is DRAFT
    try {
        const invoice = await API.purchases.getInvoice(invoiceId);
        if (invoice.status !== 'DRAFT') {
            showToast(`Cannot delete invoice with status ${invoice.status}. Only DRAFT invoices can be deleted.`, 'error');
            return;
        }
    } catch (error) {
        console.error('Error checking invoice status:', error);
        showToast('Error checking invoice status', 'error');
        return;
    }
    
    if (!confirm('Are you sure you want to delete this invoice? This action cannot be undone.')) {
        return;
    }
    
    try {
        await API.purchases.deleteInvoice(invoiceId);
        showToast('Invoice deleted successfully', 'success');
        
        // Clear auto-save timeout if any
        clearTimeout(window.autoSaveTimeout);
        
        // If we're on the edit page, navigate back to invoices list
        if (currentDocument && currentDocument.mode === 'edit' && currentDocument.invoiceId === invoiceId) {
            currentDocument = null;
            documentItems = [];
            await loadPurchaseSubPage('invoices');
        } else {
            // Refresh invoices list
            await fetchAndRenderSupplierInvoicesData();
        }
    } catch (error) {
        console.error('Error deleting invoice:', error);
        showToast(error.message || 'Error deleting invoice', 'error');
    }
}

// Auto-save invoice when changes occur
async function autoSaveInvoice() {
    if (!currentDocument || !currentDocument.invoiceId || !currentDocument.invoiceData) {
        return;
    }
    
    const invoiceData = currentDocument.invoiceData;
    if (invoiceData.status !== 'DRAFT') {
        return; // Only auto-save DRAFT invoices
    }
    
    const form = document.getElementById('purchaseInvoiceForm');
    if (!form) {
        return;
    }
    
    // Prevent auto-save if manual save is in progress
    if (isSavingDocument) {
        return;
    }
    
    const formData = new FormData(form);
    const items = transactionItemsTable ? transactionItemsTable.getItems() : [];
    
    if (items.length === 0) {
        return; // Don't auto-save empty invoices
    }
    
    try {
        const supplierId = formData.get('supplier_id');
        if (!supplierId) {
            return; // Don't auto-save without supplier
        }
        
        const invoiceUpdateData = {
            company_id: CONFIG.COMPANY_ID,
            branch_id: CONFIG.BRANCH_ID,
            supplier_id: supplierId,
            supplier_invoice_number: formData.get('supplier_invoice_number') || null,
            reference: formData.get('reference') || null,
            invoice_date: formData.get('document_date') || new Date().toISOString().split('T')[0],
            linked_grn_id: formData.get('linked_grn_id') || null,
            vat_rate: 0,  // Display only; total VAT = sum of line VATs (item-based)
            items: items.map(item => {
                const itemData = {
                    item_id: item.item_id,
                    unit_name: item.unit_name,
                    quantity: item.quantity,
                    unit_cost_exclusive: item.unit_price,
                    vat_rate: item.tax_percent != null && item.tax_percent !== '' ? Number(item.tax_percent) : 0
                };
                
                if (item.batches && Array.isArray(item.batches) && item.batches.length > 0) {
                    itemData.batches = item.batches.map(batch => ({
                        batch_number: batch.batch_number || '',
                        expiry_date: batch.expiry_date || null,
                        quantity: parseFloat(batch.quantity) || 0,
                        unit_cost: parseFloat(batch.unit_cost) || 0
                    }));
                }
                
                return itemData;
            })
        };
        
        await API.purchases.updateInvoice(currentDocument.invoiceId, invoiceUpdateData);
        console.log('✅ [Auto-save] Invoice updated automatically');
        // Don't show toast for auto-save to avoid annoying the user
    } catch (error) {
        console.error('❌ [Auto-save] Error auto-saving invoice:', error);
        // Don't show error toast for auto-save failures
    }
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
        
        // Update supplier search input (order form or invoice form, whichever is visible)
        const supplierSearch = document.getElementById('supplierSearch');
        const supplierIdInput = document.getElementById('supplierId');
        const supplierSearchInvoice = document.getElementById('supplierSearchInvoice');
        const supplierIdInvoice = document.getElementById('supplierIdInvoice');
        if (supplierSearchInvoice && supplierIdInvoice) {
            supplierSearchInvoice.value = supplier.name;
            supplierIdInvoice.value = supplier.id;
        }
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

// Batch supplier invoice (add stock to inventory)
async function batchSupplierInvoice(invoiceId) {
    if (!confirm('Are you sure you want to batch this invoice? This will add stock to inventory and cannot be undone.')) {
        return;
    }
    
    try {
        const result = await API.purchases.batchInvoice(invoiceId);
        showToast('Invoice batched successfully! Stock has been added to inventory.', 'success');
        // Reload invoices list
        await fetchAndRenderSupplierInvoicesData();
        // If user was on the edit/view page for this invoice, re-render so Batch button disappears
        if (typeof currentDocument !== 'undefined' && currentDocument && currentDocument.invoiceId === invoiceId) {
            currentDocument.status = result?.status || 'BATCHED';
            const updated = await API.purchases.getInvoice(invoiceId);
            if (updated) {
                currentDocument.invoiceData = updated;
                await renderCreateSupplierInvoicePage();
            }
        }
    } catch (error) {
        console.error('Error batching invoice:', error);
        showToast(error.message || 'Error batching invoice', 'error');
    }
}

// Update invoice payment
async function updateInvoicePayment(invoiceId, totalAmount, currentPaid) {
    const amountPaid = prompt(`Enter amount paid:\n\nTotal: ${formatCurrency(totalAmount)}\nCurrent Paid: ${formatCurrency(currentPaid)}\nBalance: ${formatCurrency(totalAmount - currentPaid)}`, currentPaid);
    
    if (amountPaid === null) return; // User cancelled
    
    const paid = parseFloat(amountPaid);
    if (isNaN(paid) || paid < 0) {
        showToast('Invalid amount', 'error');
        return;
    }
    
    if (paid > totalAmount) {
        showToast('Amount paid cannot exceed total amount', 'error');
        return;
    }
    
    try {
        const result = await API.purchases.updateInvoicePayment(invoiceId, paid);
        showToast('Payment updated successfully!', 'success');
        // Reload invoices list
        await fetchAndRenderSupplierInvoicesData();
    } catch (error) {
        console.error('Error updating payment:', error);
        showToast(error.message || 'Error updating payment', 'error');
    }
}

// Export functions to window IMMEDIATELY
// Export as functions are defined (not waiting for IIFE at end)
if (typeof window !== 'undefined') {
    // Export immediately when script loads
    window.loadPurchases = loadPurchases;
    window.loadPurchaseSubPage = loadPurchaseSubPage;
    window.switchPurchaseSubPage = switchPurchaseSubPage;
    window.createNewPurchaseOrder = createNewPurchaseOrder;
    window.createNewSupplierInvoice = createNewSupplierInvoice;
    window.createNewPurchaseInvoice = createNewSupplierInvoice; // Backward compatibility
    window.createNewCreditNote = createNewCreditNote;
    window.batchSupplierInvoice = batchSupplierInvoice;
    window.updateInvoicePayment = updateInvoicePayment;
    window.viewSupplierInvoice = viewSupplierInvoice;
    window.editSupplierInvoice = editSupplierInvoice;
    window.deleteSupplierInvoice = deleteSupplierInvoice;
    window.autoSaveInvoice = autoSaveInvoice;
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
    window.autoSavePurchaseOrder = autoSavePurchaseOrder;
    window.autoSavePurchaseOrder = autoSavePurchaseOrder;
    window.updatePurchaseOrder = updatePurchaseOrder;
    window.printPurchaseOrder = printPurchaseOrder;
    // New Page-Shell First pattern functions
    window.fetchAndRenderPurchaseOrdersData = fetchAndRenderPurchaseOrdersData;
    window.fetchAndRenderSupplierInvoicesData = fetchAndRenderSupplierInvoicesData;
    window.fetchAndRenderPurchaseInvoicesData = fetchAndRenderSupplierInvoicesData; // Backward compatibility
    window.clearPurchaseDateFilters = clearPurchaseDateFilters;
    window.fetchAndRenderCreditNotesData = fetchAndRenderCreditNotesData;
    window.renderPurchaseOrdersTableBody = renderPurchaseOrdersTableBody;
    window.renderSupplierInvoicesTableBody = renderSupplierInvoicesTableBody;
    window.renderPurchaseInvoicesTableBody = renderSupplierInvoicesTableBody; // Backward compatibility
    window.renderCreditNotesTableBody = renderCreditNotesTableBody;
    window.searchSuppliersInline = searchSuppliersInline;
    window.handleSupplierSearchFocus = handleSupplierSearchFocus;
    window.handleSupplierSearchBlur = handleSupplierSearchBlur;
    window.handlePOFromBookSupplierFocus = handlePOFromBookSupplierFocus;
    window.selectSupplier = selectSupplier;
    window.renderCreatePurchaseOrderPage = renderCreatePurchaseOrderPage;
    window.initializeTransactionItemsTable = initializeTransactionItemsTable;
    
    // Document zoom functionality (works for all transaction documents)
    function zoomDocumentView(action, cardId = 'purchaseOrderDocumentCard', zoomLevelId = 'documentZoomLevel') {
        const card = document.getElementById(cardId);
        if (!card) return;
        
        let currentZoom = parseFloat(card.style.transform.replace('scale(', '').replace(')', '')) || 1;
        const zoomStep = 0.1;
        const minZoom = 0.5;
        const maxZoom = 1.5;
        
        if (action === 'in') {
            currentZoom = Math.min(currentZoom + zoomStep, maxZoom);
        } else if (action === 'out') {
            currentZoom = Math.max(currentZoom - zoomStep, minZoom);
        } else if (action === 'reset') {
            currentZoom = 1;
        }
        
        card.style.transform = `scale(${currentZoom})`;
        const zoomLevelEl = document.getElementById(zoomLevelId);
        if (zoomLevelEl) {
            zoomLevelEl.textContent = Math.round(currentZoom * 100) + '%';
        }
        
        // Store zoom level
        window.documentZoomLevel = currentZoom;
    }
    
    // Mouse wheel zoom (Ctrl + Scroll) - works for all document cards
    document.addEventListener('wheel', (e) => {
        if (e.ctrlKey || e.metaKey) {
            // Check for Purchase Order card
            let card = document.getElementById('purchaseOrderDocumentCard');
            let zoomLevelId = 'documentZoomLevel';
            
            // If not found, check for Supplier Invoice card
            if (!card || card.offsetParent === null) {
                card = document.getElementById('supplierInvoiceDocumentCard');
                zoomLevelId = 'supplierInvoiceZoomLevel';
            }
            
            if (card && card.offsetParent !== null) { // Check if element is visible
                e.preventDefault();
                const delta = e.deltaY > 0 ? 'out' : 'in';
                zoomDocumentView(delta, card.id, zoomLevelId);
            }
        }
    }, { passive: false });
    
    function setupDocumentZoom(cardId = 'purchaseOrderDocumentCard', zoomLevelId = 'documentZoomLevel') {
        // Initialize zoom level display
        const zoomLevelEl = document.getElementById(zoomLevelId);
        if (zoomLevelEl) {
            zoomLevelEl.textContent = '100%';
        }
        // Reset zoom on page load
        const card = document.getElementById(cardId);
        if (card) {
            card.style.transform = 'scale(1)';
        }
    }
    
    // Export zoom function
    window.zoomDocumentView = zoomDocumentView;
    
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

// =====================================================
// ORDER BOOK PAGE
// =====================================================

let orderBookEntries = [];
let selectedOrderBookEntries = new Set();
let orderBookDateFilter = 'today'; // today | yesterday | this_week | last_week | this_month | last_month | this_year | last_year
let orderBookSupplierFilter = null; // UUID or null = all suppliers

// Render Order Book Page (Page-Shell-First Pattern)
async function renderOrderBookPage() {
    console.log('renderOrderBookPage() called');
    const page = document.getElementById('purchases');
    if (!page) return;

    let suppliers = [];
    try {
        if (window.API && window.API.suppliers && window.API.suppliers.list)
            suppliers = await window.API.suppliers.list(window.CONFIG ? window.CONFIG.COMPANY_ID : null);
    } catch (e) {
        console.warn('Could not load suppliers for order book filter:', e);
    }

    // Render shell first (with supplier dropdown)
    renderOrderBookShell(suppliers);

    // Then fetch and render data
    await fetchAndRenderOrderBookData();
}

function renderOrderBookShell(suppliers = []) {
    const page = document.getElementById('purchases');
    if (!page) return;

    const supplierOptions = (suppliers || []).map(s => 
        `<option value="${s.id}" ${orderBookSupplierFilter === s.id ? 'selected' : ''}>${escapeHtml(s.name || s.supplier_name || s.id)}</option>`
    ).join('');

    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-clipboard-list"></i> Daily Order Book
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="if(window.autoGenerateOrderBook) window.autoGenerateOrderBook()">
                        <i class="fas fa-magic"></i> Auto-Generate
                    </button>
                    <button class="btn btn-primary" id="createPOFromBookBtn" onclick="if(window.createPurchaseOrderFromSelected) window.createPurchaseOrderFromSelected()" disabled>
                        <i class="fas fa-shopping-cart"></i> Create Purchase Order
                    </button>
                </div>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <div style="margin-bottom: 1rem; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                    <label style="font-weight: 500; margin-right: 0.25rem;">Date:</label>
                    <select id="orderBookDateFilter" class="form-input" style="width: 160px;" onchange="if(window.applyOrderBookDateFilter) window.applyOrderBookDateFilter(this.value)">
                        <option value="today" ${orderBookDateFilter === 'today' ? 'selected' : ''}>Today</option>
                        <option value="yesterday" ${orderBookDateFilter === 'yesterday' ? 'selected' : ''}>Yesterday</option>
                        <option value="this_week" ${orderBookDateFilter === 'this_week' ? 'selected' : ''}>This Week</option>
                        <option value="last_week" ${orderBookDateFilter === 'last_week' ? 'selected' : ''}>Last Week</option>
                        <option value="this_month" ${orderBookDateFilter === 'this_month' ? 'selected' : ''}>This Month</option>
                        <option value="last_month" ${orderBookDateFilter === 'last_month' ? 'selected' : ''}>Last Month</option>
                        <option value="this_year" ${orderBookDateFilter === 'this_year' ? 'selected' : ''}>This Year</option>
                        <option value="last_year" ${orderBookDateFilter === 'last_year' ? 'selected' : ''}>Last Year</option>
                    </select>
                    <label style="font-weight: 500; margin-left: 0.5rem; margin-right: 0.25rem;">Supplier:</label>
                    <select id="orderBookSupplierFilter" class="form-input" style="width: 200px;" onchange="if(window.applyOrderBookSupplierFilter) window.applyOrderBookSupplierFilter(this.value)">
                        <option value="">All suppliers</option>
                        ${supplierOptions}
                    </select>
                    <input type="text" 
                           class="form-input" 
                           id="orderBookSearchInput" 
                           placeholder="Search items..."
                           onkeyup="if(window.filterOrderBookEntries) window.filterOrderBookEntries()"
                           style="flex: 1; max-width: 400px;">
                    <button class="btn btn-outline" onclick="if(window.selectAllOrderBookEntries) window.selectAllOrderBookEntries()">
                        <i class="fas fa-check-square"></i> Select All
                    </button>
                    <button class="btn btn-outline" onclick="if(window.deselectAllOrderBookEntries) window.deselectAllOrderBookEntries()">
                        <i class="fas fa-square"></i> Deselect All
                    </button>
                </div>
                
                <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 20;">
                            <tr>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); width: 40px;">
                                    <input type="checkbox" id="selectAllCheckbox" onchange="if(window.toggleSelectAllOrderBook) window.toggleSelectAllOrderBook(this.checked)">
                                </th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">SKU</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Current Stock</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: right;">Qty Needed</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Unit</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Supplier</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Reason</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: center;" title="Number of days this item appeared in the order book in the past 90 days">Days in book (90d)</th>
                                <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: center;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="orderBookTableBody">
                            <tr>
                                <td colspan="10" style="padding: 3rem; text-align: center;">
                                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading order book entries...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function getOrderBookDateRange(filter) {
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth(), d = now.getDate();
    let dateFrom, dateTo;
    switch (filter) {
        case 'today':
            dateFrom = dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        case 'yesterday':
            const yesterday = new Date(now); yesterday.setDate(yesterday.getDate() - 1);
            dateFrom = dateTo = yesterday.toISOString().split('T')[0];
            break;
        case 'this_week': {
            const day = now.getDay();
            const mon = new Date(now); mon.setDate(d - (day === 0 ? 6 : day - 1));
            dateFrom = mon.toISOString().split('T')[0];
            dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        }
        case 'last_week': {
            const day = now.getDay();
            const lastMon = new Date(now); lastMon.setDate(d - (day === 0 ? 6 : day - 1) - 7);
            dateFrom = lastMon.toISOString().split('T')[0];
            const lastSun = new Date(lastMon); lastSun.setDate(lastSun.getDate() + 6);
            dateTo = lastSun.toISOString().split('T')[0];
            break;
        }
        case 'this_month':
            dateFrom = [y, String(m + 1).padStart(2, '0'), '01'].join('-');
            dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        case 'last_month': {
            const lastM = m === 0 ? 11 : m - 1;
            const lastY = m === 0 ? y - 1 : y;
            dateFrom = [lastY, String(lastM + 1).padStart(2, '0'), '01'].join('-');
            const lastDay = new Date(lastY, lastM + 1, 0).getDate();
            dateTo = [lastY, String(lastM + 1).padStart(2, '0'), String(lastDay).padStart(2, '0')].join('-');
            break;
        }
        case 'this_year':
            dateFrom = [y, '01', '01'].join('-');
            dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        case 'last_year':
            dateFrom = [y - 1, '01', '01'].join('-');
            dateTo = [y - 1, '12', '31'].join('-');
            break;
        default:
            const t = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            dateFrom = dateTo = t;
    }
    return { dateFrom, dateTo };
}

async function applyOrderBookDateFilter(value) {
    orderBookDateFilter = value || 'today';
    await fetchAndRenderOrderBookData();
}

async function applyOrderBookSupplierFilter(value) {
    orderBookSupplierFilter = (value && value.trim()) ? value.trim() : null;
    await fetchAndRenderOrderBookData();
}

async function fetchAndRenderOrderBookData() {
    try {
        if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
            const tbody = document.getElementById('orderBookTableBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="10" style="padding: 2rem; text-align: center; color: var(--text-secondary);">Please configure Company and Branch in Settings</td></tr>';
            }
            return;
        }
        const { dateFrom, dateTo } = getOrderBookDateRange(orderBookDateFilter);
        const listOptions = { dateFrom, dateTo, includeOrdered: true };
        if (orderBookSupplierFilter) listOptions.supplierId = orderBookSupplierFilter;
        const entries = await API.orderBook.list(CONFIG.BRANCH_ID, CONFIG.COMPANY_ID, null, listOptions);
        orderBookEntries = entries;
        renderOrderBookTable();
    } catch (error) {
        console.error('Error loading order book entries:', error);
        const tbody = document.getElementById('orderBookTableBody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="10" style="padding: 2rem; text-align: center; color: var(--danger-color);">Error loading order book: ${error.message}</td></tr>`;
        }
    }
}

function renderOrderBookTable() {
    const tbody = document.getElementById('orderBookTableBody');
    if (!tbody) return;
    
    if (orderBookEntries.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="padding: 3rem; text-align: center; color: var(--text-secondary);">
                    <i class="fas fa-clipboard-list" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                    <p style="font-size: 1.1rem;">No order book entries</p>
                    <p style="font-size: 0.875rem;">Click "Auto-Generate" to create entries based on stock thresholds</p>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = orderBookEntries.map(entry => {
        const isConverted = entry.status === 'ORDERED' || entry.purchase_order_id;
        const rowClass = isConverted ? 'order-book-row-converted' : '';
        const rowStyle = isConverted ? 'background: #e8f5e9; border-left: 4px solid var(--success-color, #28a745);' : '';
        return `
        <tr class="${rowClass}" data-entry-id="${entry.id}" data-status="${entry.status || 'PENDING'}" style="${rowStyle}">
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                ${isConverted
                    ? '<span class="badge badge-success" title="Converted to Purchase Order"><i class="fas fa-check-circle"></i> Converted</span>'
                    : `<input type="checkbox" class="order-book-checkbox" data-entry-id="${entry.id}" onchange="if(window.toggleOrderBookEntrySelection) window.toggleOrderBookEntrySelection('${entry.id}', this.checked)">`}
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                <strong>${escapeHtml(entry.item_name || 'Unknown')}</strong>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                <code>${escapeHtml(entry.item_sku || '—')}</code>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: right;">
                <span style="color: ${entry.current_stock <= 0 ? 'var(--danger-color)' : 'var(--text-color)'};">
                    ${entry.current_stock || 0}
                </span>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: right;">
                <strong>${parseFloat(entry.quantity_needed)}</strong>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                ${escapeHtml(entry.unit_name)}
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                ${escapeHtml(entry.supplier_name || '—')}
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                <span class="badge badge-info">${escapeHtml(entry.reason)}</span>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">
                <span class="badge ${(entry.days_in_order_book_90 ?? entry.priority) >= 8 ? 'badge-danger' : (entry.days_in_order_book_90 ?? entry.priority) >= 5 ? 'badge-warning' : 'badge-info'}" title="Days this item appeared in the order book (past 90 days)">
                    ${entry.days_in_order_book_90 != null ? entry.days_in_order_book_90 : entry.priority}
                </span>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">
                ${isConverted
                    ? '—'
                    : `<button class="btn btn-outline btn-sm" onclick="if(window.editOrderBookEntry) window.editOrderBookEntry('${entry.id}')" title="Edit quantity"><i class="fas fa-edit"></i></button>
                       <button class="btn btn-outline btn-sm" onclick="if(window.deleteOrderBookEntry) window.deleteOrderBookEntry('${entry.id}')" title="Delete"><i class="fas fa-trash"></i></button>`}
            </td>
        </tr>
    `;
    }).join('');
    
    updateCreatePOButtonState();
}

function toggleOrderBookEntrySelection(entryId, checked) {
    if (checked) {
        selectedOrderBookEntries.add(entryId);
    } else {
        selectedOrderBookEntries.delete(entryId);
    }
    updateCreatePOButtonState();
}

function selectAllOrderBookEntries() {
    orderBookEntries.forEach(entry => {
        const isConverted = entry.status === 'ORDERED' || entry.purchase_order_id;
        if (!isConverted) {
            selectedOrderBookEntries.add(entry.id);
            const checkbox = document.querySelector(`.order-book-checkbox[data-entry-id="${entry.id}"]`);
            if (checkbox) checkbox.checked = true;
        }
    });
    updateCreatePOButtonState();
}

function deselectAllOrderBookEntries() {
    selectedOrderBookEntries.clear();
    document.querySelectorAll('.order-book-checkbox').forEach(cb => cb.checked = false);
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');
    if (selectAllCheckbox) selectAllCheckbox.checked = false;
    updateCreatePOButtonState();
}

function toggleSelectAllOrderBook(checked) {
    if (checked) {
        selectAllOrderBookEntries();
    } else {
        deselectAllOrderBookEntries();
    }
}

function updateCreatePOButtonState() {
    const btn = document.getElementById('createPOFromBookBtn');
    if (btn) {
        btn.disabled = selectedOrderBookEntries.size === 0;
    }
}

async function autoGenerateOrderBook() {
    try {
        if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
            showToast('Please configure Company and Branch', 'warning');
            return;
        }
        
        showToast('Auto-generating order book entries...', 'info');
        const result = await API.orderBook.autoGenerate(CONFIG.BRANCH_ID, CONFIG.COMPANY_ID);
        showToast(`Created ${result.entries_created} order book entries`, 'success');
        await fetchAndRenderOrderBookData();
    } catch (error) {
        console.error('Error auto-generating order book:', error);
        showToast(`Error: ${error.message}`, 'error');
    }
}

async function createPurchaseOrderFromSelected() {
    if (selectedOrderBookEntries.size === 0) {
        showToast('Please select at least one entry', 'warning');
        return;
    }
    const selectedEntries = orderBookEntries.filter(e => selectedOrderBookEntries.has(e.id) && e.status !== 'ORDERED' && !e.purchase_order_id);
    if (selectedEntries.length === 0) {
        showToast('No pending entries selected', 'warning');
        return;
    }
    const suppliers = [...new Set(selectedEntries.map(e => e.supplier_id).filter(Boolean))];
    // Show modal to select supplier and enter details (user can pick any supplier)
    const modal = document.createElement('div');
    modal.id = 'createPOFromBookModal';
    modal.className = 'modal';
    modal.style.cssText = 'position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 9999;';
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 500px; background: white; border-radius: 0.5rem; box-shadow: 0 4px 20px rgba(0,0,0,0.2);">
            <div class="modal-header" style="padding: 1rem 1.25rem; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0;">Create Purchase Order from Order Book</h3>
                <button class="modal-close" onclick="document.getElementById('createPOFromBookModal')?.remove()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
            </div>
            <div class="modal-body">
                <div style="margin-bottom: 1rem;">
                    <label>Supplier *</label>
                    <div style="position: relative;">
                        <input type="text" class="form-input" id="poFromBookSupplierSearch" 
                               placeholder="Type at least 2 characters to search suppliers..."
                               autocomplete="off" required
                               onkeyup="searchSuppliersInline(event, 'poFromBookSupplierSearch', 'poFromBookSupplierId', 'poFromBookSupplierDropdown')"
                               onfocus="handlePOFromBookSupplierFocus(event)"
                               onblur="setTimeout(function(){ var d=document.getElementById('poFromBookSupplierDropdown'); if(d) d.style.display='none'; }, 200)">
                        <input type="hidden" id="poFromBookSupplierId">
                        <div id="poFromBookSupplierDropdown" 
                             style="position: absolute; top: 100%; left: 0; right: 0; background: white; border: 1px solid var(--border-color); border-radius: 0.25rem; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 10000; max-height: 280px; overflow-y: auto; display: none; margin-top: 0.25rem;">
                        </div>
                    </div>
                </div>
                <div style="margin-bottom: 1rem;">
                    <label>Order Date *</label>
                    <input type="date" id="poOrderDate" class="form-input" value="${new Date().toISOString().split('T')[0]}" required>
                </div>
                <div style="margin-bottom: 1rem;">
                    <label>Reference</label>
                    <input type="text" id="poReference" class="form-input" placeholder="Optional reference">
                </div>
                <div style="margin-bottom: 1rem;">
                    <label>Notes</label>
                    <textarea id="poNotes" class="form-input" rows="3" placeholder="Optional notes"></textarea>
                </div>
                <div style="margin-top: 1.5rem; display: flex; gap: 0.5rem; justify-content: flex-end;">
                    <button type="button" class="btn btn-secondary" id="poFromBookCancelBtn" onclick="document.getElementById('createPOFromBookModal')?.remove()">Cancel</button>
                    <button type="button" class="btn btn-primary" id="poFromBookSubmitBtn" onclick="if(window.confirmCreatePOFromBook) window.confirmCreatePOFromBook()">
                        <i class="fas fa-shopping-cart"></i> Create Purchase Order
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

let confirmCreatePOFromBookInProgress = false;

async function confirmCreatePOFromBook() {
    if (confirmCreatePOFromBookInProgress) {
        return;
    }
    const submitBtn = document.getElementById('poFromBookSubmitBtn');
    const cancelBtn = document.getElementById('poFromBookCancelBtn');
    const supplierId = document.getElementById('poFromBookSupplierId')?.value;
    const orderDate = document.getElementById('poOrderDate')?.value;
    const reference = document.getElementById('poReference')?.value || '';
    const notes = document.getElementById('poNotes')?.value || '';

    if (!supplierId || !orderDate) {
        showToast('Please fill in all required fields', 'warning');
        return;
    }
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID || !CONFIG.USER_ID) {
        showToast('Configuration error: Missing company, branch, or user ID', 'error');
        return;
    }

    confirmCreatePOFromBookInProgress = true;
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
    }
    if (cancelBtn) cancelBtn.disabled = true;

    try {
        const entryIds = Array.from(selectedOrderBookEntries);
        const result = await API.orderBook.createPurchaseOrder(
            { entry_ids: entryIds, supplier_id: supplierId, order_date: orderDate, reference, notes },
            CONFIG.COMPANY_ID,
            CONFIG.BRANCH_ID,
            CONFIG.USER_ID
        );

        const orderNumber = result && result.order_number ? result.order_number : 'PO';
        const poId = result && result.purchase_order_id ? result.purchase_order_id : null;

        const modalEl = document.getElementById('createPOFromBookModal');
        if (modalEl) modalEl.remove();

        showToast(`Purchase order ${orderNumber} created successfully. Opening for editing.`, 'success');

        selectedOrderBookEntries.clear();
        confirmCreatePOFromBookInProgress = false;

        try {
            await fetchAndRenderOrderBookData();
        } catch (_) { /* non-blocking */ }

        if (poId) {
            currentPurchaseSubPage = 'create';
            try {
                await editPurchaseDocument(poId, 'order');
            } catch (e) {
                console.warn('Could not open PO editor:', e);
                showToast('Purchase order created. Open it from the Purchase Orders list.', 'info');
            }
            updatePurchaseSubNavActiveState();
        }
    } catch (error) {
        console.error('Error creating purchase order:', error);
        showToast(error.message || 'Failed to create purchase order', 'error');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-shopping-cart"></i> Create Purchase Order';
        }
        if (cancelBtn) cancelBtn.disabled = false;
    } finally {
        confirmCreatePOFromBookInProgress = false;
    }
}

async function editOrderBookEntry(entryId) {
    const entry = orderBookEntries.find(e => e.id === entryId);
    if (!entry) return;
    if (entry.status === 'ORDERED' || entry.purchase_order_id) {
        showToast('Cannot edit: this entry has already been converted to a purchase order.', 'info');
        return;
    }
    const currentQty = parseFloat(entry.quantity_needed) || 1;
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'orderBookEditModal';
    modal.style.cssText = 'position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 9999;';
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 400px; background: white; border-radius: 0.5rem; box-shadow: 0 4px 20px rgba(0,0,0,0.2);">
            <div class="modal-header">
                <h3>Edit quantity</h3>
                <button class="modal-close" onclick="document.getElementById('orderBookEditModal').remove()">&times;</button>
            </div>
            <div class="modal-body">
                <p style="margin-bottom: 0.75rem; color: var(--text-secondary);">${escapeHtml(entry.item_name || 'Item')}</p>
                <div class="form-group">
                    <label class="form-label">Qty needed *</label>
                    <input type="number" id="orderBookEditQty" class="form-input" min="0.0001" step="any" value="${currentQty}" required>
                </div>
                <div style="margin-top: 1rem; display: flex; gap: 0.5rem; justify-content: flex-end;">
                    <button type="button" class="btn btn-secondary" onclick="document.getElementById('orderBookEditModal').remove()">Cancel</button>
                    <button type="button" class="btn btn-primary" id="orderBookEditSaveBtn">Save</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    document.getElementById('orderBookEditQty').focus();
    document.getElementById('orderBookEditSaveBtn').onclick = async () => {
        const input = document.getElementById('orderBookEditQty');
        const newQty = parseFloat(input.value);
        if (isNaN(newQty) || newQty <= 0) {
            showToast('Please enter a valid quantity greater than 0', 'warning');
            return;
        }
        try {
            await API.orderBook.update(entryId, { quantity_needed: newQty });
            modal.remove();
            showToast('Quantity updated', 'success');
            await fetchAndRenderOrderBookData();
        } catch (err) {
            console.error('Error updating order book entry:', err);
            showToast(err.message || 'Failed to update quantity', 'error');
        }
    };
}

async function deleteOrderBookEntry(entryId) {
    if (!confirm('Are you sure you want to remove this entry from the order book?')) {
        return;
    }
    
    try {
        await API.orderBook.delete(entryId);
        showToast('Entry removed from order book', 'success');
        await fetchAndRenderOrderBookData();
    } catch (error) {
        console.error('Error deleting order book entry:', error);
        showToast(`Error: ${error.message}`, 'error');
    }
}

function filterOrderBookEntries() {
    const searchTerm = document.getElementById('orderBookSearchInput')?.value.toLowerCase() || '';
    const rows = document.querySelectorAll('#orderBookTableBody tr[data-entry-id]');
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// Export order book functions
if (typeof window !== 'undefined') {
    window.renderOrderBookPage = renderOrderBookPage;
    window.fetchAndRenderOrderBookData = fetchAndRenderOrderBookData;
    window.applyOrderBookDateFilter = applyOrderBookDateFilter;
    window.applyOrderBookSupplierFilter = applyOrderBookSupplierFilter;
    window.getOrderBookDateRange = getOrderBookDateRange;
    window.toggleOrderBookEntrySelection = toggleOrderBookEntrySelection;
    window.selectAllOrderBookEntries = selectAllOrderBookEntries;
    window.deselectAllOrderBookEntries = deselectAllOrderBookEntries;
    window.toggleSelectAllOrderBook = toggleSelectAllOrderBook;
    window.autoGenerateOrderBook = autoGenerateOrderBook;
    window.createPurchaseOrderFromSelected = createPurchaseOrderFromSelected;
    window.confirmCreatePOFromBook = confirmCreatePOFromBook;
    window.editOrderBookEntry = editOrderBookEntry;
    window.deleteOrderBookEntry = deleteOrderBookEntry;
    window.filterOrderBookEntries = filterOrderBookEntries;
}

// Verify exports at end of file (after all exports are done)
if (typeof window !== 'undefined') {
    // This runs after the main export block at line 1827-1867
    console.log('✓ Purchases functions final verification');
    console.log('  - window.loadPurchases:', typeof window.loadPurchases);
    console.log('  - window.createNewPurchaseOrder:', typeof window.createNewPurchaseOrder);
    console.log('  - window.loadPurchaseSubPage:', typeof window.loadPurchaseSubPage);
    console.log('  - window.renderOrderBookPage:', typeof window.renderOrderBookPage);
}