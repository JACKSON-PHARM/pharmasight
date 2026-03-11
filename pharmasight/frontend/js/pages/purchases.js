// Purchases Page - Document Management (Purchase Orders, Invoices, Credit Notes)

// Immediate verification that script is executing
console.log('✅ purchases.js script loaded');
console.log('✅ Script execution started at:', new Date().toISOString());

let currentPurchaseSubPage = 'orders'; // 'orders', 'invoices', 'credit-notes', 'create'
let purchaseDocuments = [];
let currentDocument = null;
let documentItems = [];
let allSuppliers = [];
let supplierInvoiceSyncedItemIds = new Set();
/** Cache item_id -> { item_name, item_code } so supplier invoice rows show correct name/code when API omits or returns "=" */
let supplierInvoiceItemDisplayCache = {};
let poSyncedItemIds = new Set();
/** Same for purchase order items */
let poItemDisplayCache = {};
/** Supplier Invoices list date preset: today | yesterday | ... | custom */
let supplierInvoicesDateFilter = 'today';
let supplierInvoicesUserFilter = 'self';
/** Purchase Orders list date preset. Use 'this_week' so approved orders from recent days are visible by default. */
let purchaseOrdersDateFilter = 'this_week';
let purchaseOrdersUserFilter = 'self';

// Guard state for viewing supplier invoices to prevent duplicate API calls and stale UI updates
let supplierInvoiceViewInProgress = false;
let supplierInvoiceViewCurrentId = null;

/** Return today's date as YYYY-MM-DD in the user's local timezone (so "Today" filter and form default match). */
function getLocalDateString() {
    const n = new Date();
    return [n.getFullYear(), String(n.getMonth() + 1).padStart(2, '0'), String(n.getDate()).padStart(2, '0')].join('-');
}

function getSupplierInvoiceItemDisplay(i, cache) {
    const idKey = i.item_id != null ? String(i.item_id) : '';
    let name = (i.item_name && i.item_name !== '=' && String(i.item_name).trim()) ? i.item_name : (i.item && i.item.name ? i.item.name : (i.item_code && i.item_code !== '=' && i.item_code !== '—') ? i.item_code : '') || '';
    let code = (i.item_code && i.item_code !== '=' && i.item_code !== '—' && String(i.item_code).trim()) ? i.item_code : '';
    if (!name && cache && cache[idKey] && cache[idKey].item_name) name = cache[idKey].item_name;
    if (!code && cache && cache[idKey] && cache[idKey].item_code) code = cache[idKey].item_code;
    if (name || code) {
        if (!cache[idKey]) cache[idKey] = {};
        if (name) cache[idKey].item_name = name;
        if (code) cache[idKey].item_code = code;
    }
    return { item_name: name || (cache && cache[idKey] && cache[idKey].item_name) || '', item_code: code || (cache && cache[idKey] && cache[idKey].item_code) || '' };
}

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
    
    // Ensure company print settings are loaded before any print (thermal vs A4, margins, etc.)
    if (typeof window.loadCompanyPrintSettings === 'function') {
        window.loadCompanyPrintSettings().catch(() => {});
    }
    try {
        const raw = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pendingLandingDocument');
        if (raw) {
            const pending = JSON.parse(raw);
            if (pending && pending.type === 'purchase_order') {
                currentPurchaseSubPage = 'create';
            }
        }
    } catch (_) {}
    console.log('Loading purchase sub-page:', currentPurchaseSubPage);
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
    
    // Record payment page: subPage can be "record-payment" or "record-payment?supplier_id=xxx"
    if (subPage === 'record-payment' || (subPage && String(subPage).indexOf('record-payment') === 0)) {
        const hash = window.location.hash || '';
        const fullSub = (subPage || '').toString();
        const queryPart = fullSub.indexOf('?') >= 0 ? fullSub.slice(fullSub.indexOf('?') + 1) : (hash.indexOf('?') >= 0 ? hash.slice(hash.indexOf('?') + 1) : '');
        let supplierId = '';
        if (queryPart) {
            try {
                const params = new URLSearchParams(queryPart);
                supplierId = (params.get('supplier_id') || '').trim();
            } catch (_) {}
        }
        await renderRecordPaymentPage(supplierId);
        updatePurchaseSubNavActiveState();
        return;
    }

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
        case 'supplier-dashboard':
            await renderSupplierDashboardPage();
            break;
        case 'suppliers':
            await renderSuppliersPage();
            break;
        case 'supplier-detail':
            if (window.currentSupplierDetailId) {
                await renderSupplierDetailPage(window.currentSupplierDetailId);
            } else {
                await renderSuppliersPage();
            }
            break;
        case 'supplier-payments':
            await renderSupplierPaymentsPage();
            break;
        case 'order-book':
            await renderOrderBookPage();
            break;
        default:
            if (subPage && subPage.startsWith('suppliers-') && subPage !== 'suppliers') {
                const supplierId = subPage.replace('suppliers-', '');
                window.currentSupplierDetailId = supplierId;
                await renderSupplierDetailPage(supplierId);
            } else {
                await renderPurchaseOrdersPage();
            }
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
    
    const today = getLocalDateString();
    const orderRange = getSupplierInvoicesDateRange(purchaseOrdersDateFilter);
    const orderFrom = orderRange ? orderRange.dateFrom : today;
    const orderTo = orderRange ? orderRange.dateTo : today;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.1rem;">
                    <i class="fas fa-file-invoice"></i> Purchase Orders
                </h3>
                <button class="btn btn-primary btn-sm" onclick="if(window.createNewPurchaseOrder) window.createNewPurchaseOrder()">
                    <i class="fas fa-plus"></i> New Order
                </button>
            </div>
            
            <div class="card-body" style="padding: 0.5rem 0.75rem;">
                <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; font-size: 0.8rem;">
                    <select id="purchaseOrdersDateFilter" class="form-input" style="width: 120px; padding: 0.35rem 0.5rem;" onchange="if(window.togglePurchaseOrdersCustomDates) window.togglePurchaseOrdersCustomDates()">
                        <option value="today" ${purchaseOrdersDateFilter === 'today' ? 'selected' : ''}>Today</option>
                        <option value="yesterday" ${purchaseOrdersDateFilter === 'yesterday' ? 'selected' : ''}>Yesterday</option>
                        <option value="this_week" ${purchaseOrdersDateFilter === 'this_week' ? 'selected' : ''}>This Week</option>
                        <option value="last_week" ${purchaseOrdersDateFilter === 'last_week' ? 'selected' : ''}>Last Week</option>
                        <option value="this_month" ${purchaseOrdersDateFilter === 'this_month' ? 'selected' : ''}>This Month</option>
                        <option value="last_month" ${purchaseOrdersDateFilter === 'last_month' ? 'selected' : ''}>Last Month</option>
                        <option value="this_year" ${purchaseOrdersDateFilter === 'this_year' ? 'selected' : ''}>This Year</option>
                        <option value="last_year" ${purchaseOrdersDateFilter === 'last_year' ? 'selected' : ''}>Last Year</option>
                        <option value="custom" ${purchaseOrdersDateFilter === 'custom' ? 'selected' : ''}>Custom</option>
                    </select>
                    <div id="purchaseOrdersCustomDateRange" style="display: ${purchaseOrdersDateFilter === 'custom' ? 'flex' : 'none'}; gap: 0.35rem; align-items: center;">
                        <input type="date" class="form-input" id="filterDateFrom" value="${orderFrom}" style="width: 120px; padding: 0.35rem 0.5rem;">
                        <span>-</span>
                        <input type="date" class="form-input" id="filterDateTo" value="${orderTo}" style="width: 120px; padding: 0.35rem 0.5rem;">
                    </div>
                    <button type="button" class="btn btn-primary btn-sm" onclick="if(window.applyDateFilter) window.applyDateFilter()">
                        <i class="fas fa-check"></i> Apply
                    </button>
                    <button type="button" class="btn btn-outline btn-sm" onclick="if(window.clearDateFilter) window.clearDateFilter()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                    <select id="purchaseOrdersUserFilter" class="form-input" style="width: 90px; padding: 0.35rem 0.5rem;" onchange="if(window.applyDateFilter) window.applyDateFilter()" title="Show my documents or all">
                        <option value="self" ${purchaseOrdersUserFilter === 'self' ? 'selected' : ''}>Self</option>
                        <option value="all" ${purchaseOrdersUserFilter === 'all' ? 'selected' : ''}>All</option>
                    </select>
                    <input type="text" class="form-input" id="purchaseSearchInput" placeholder="Search doc, supplier..." onkeyup="if(window.filterPurchaseDocuments) window.filterPurchaseDocuments()" style="width: 160px; padding: 0.35rem 0.5rem;">
                </div>
                
                <div class="table-container" style="max-height: calc(100vh - 180px); overflow: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 10; box-shadow: 0 1px 2px rgba(0,0,0,0.06);">
                            <tr>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">DocNumber</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">DocDate</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">DocAmt</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Currency</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Acct</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">AcctRef</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">AcctName</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Branch</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">User</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="purchaseOrdersTableBody">
                            <tr>
                                <td colspan="11" style="padding: 1.5rem; text-align: center; font-size: 0.8rem;">
                                    <div class="spinner" style="margin: 0 auto 0.5rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading documents...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    const fromEl = document.getElementById('filterDateFrom');
    const toEl = document.getElementById('filterDateTo');
    if (fromEl) fromEl.value = orderFrom;
    if (toEl) toEl.value = orderTo;
    
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
    
    const userFilterEl = document.getElementById('purchaseOrdersUserFilter');
    const userFilter = (userFilterEl && userFilterEl.value) ? userFilterEl.value : purchaseOrdersUserFilter;
    const searchTerm = (document.getElementById('purchaseSearchInput')?.value || '').trim().toLowerCase();
    let list = purchaseDocuments.slice();
    if (userFilter === 'self' && typeof CONFIG !== 'undefined' && CONFIG.USER_ID) {
        const uid = String(CONFIG.USER_ID);
        list = list.filter(doc => doc && (String(doc.created_by || '') === uid));
    }
    if (searchTerm) {
        list = list.filter(doc => {
            const num = String(doc.order_number || doc.invoice_number || '').toLowerCase();
            const sup = String(doc.supplier_name || '').toLowerCase();
            const ref = String(doc.reference || '').toLowerCase();
            return num.includes(searchTerm) || sup.includes(searchTerm) || ref.includes(searchTerm);
        });
    }
    
    if (list.length === 0) {
        var emptyHtml = (window.EmptyStateWatermark && window.EmptyStateWatermark.render)
            ? window.EmptyStateWatermark.render({ title: 'No purchase orders yet', description: 'Create your first purchase order to get started' })
            : '<p style="color: var(--text-secondary); margin: 0.5rem 0;">No purchase orders found</p>';
        tbody.innerHTML = '<tr><td colspan="11" style="padding: 1.5rem; text-align: center; font-size: 0.8rem;">' + emptyHtml + '<button class="btn btn-primary btn-sm" onclick="if(window.createNewPurchaseOrder) window.createNewPurchaseOrder()" style="margin-top: 1rem;"><i class="fas fa-plus"></i> Create Your First Purchase Order</button></td></tr>';
        return;
    }
    
    const docType = 'order';
    const formattedDocs = list.map(doc => ({
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
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">
                    <strong style="color: var(--primary-color); cursor: pointer; text-decoration: underline; font-size: 0.8rem;" onclick="${linkClickHandler}">${doc.docNumber}</strong>
                </td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${formatDate(doc.docDate)}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);"><strong>${formatCurrency(doc.docAmt)}</strong></td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.currency}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.acct}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.acctRef}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.acctName}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.branch}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);"><span class="badge ${statusClass}" style="font-size: 0.7rem;">${statusText}</span></td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.doneBy || '—'}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">
                    <button class="btn btn-outline btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', '${docType}')" title="View"><i class="fas fa-eye"></i></button>
                    ${statusText === 'APPROVED' ? `<button class="btn btn-outline btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.downloadPurchaseOrderPdf) window.downloadPurchaseOrderPdf('${doc.id}')" title="PDF"><i class="fas fa-file-pdf"></i></button>` : ''}
                    ${statusText === 'PENDING' ? `
                    <button class="btn btn-outline btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.editPurchaseDocument) window.editPurchaseDocument('${doc.id}', '${docType}')" title="Edit"><i class="fas fa-edit"></i></button>
                    <button class="btn btn-outline btn-danger btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.deletePurchaseOrder) window.deletePurchaseOrder('${doc.id}')" title="Delete"><i class="fas fa-trash"></i></button>
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

/** Returns { dateFrom, dateTo } for the given preset, or null for 'custom' (caller should use From/To inputs). */
function getSupplierInvoicesDateRange(preset) {
    if (preset === 'custom') return null;
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth(), d = now.getDate();
    let dateFrom, dateTo;
    switch (preset) {
        case 'today':
            dateFrom = dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        case 'yesterday': {
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            const yy = yesterday.getFullYear(), mm = yesterday.getMonth(), dd = yesterday.getDate();
            dateFrom = dateTo = [yy, String(mm + 1).padStart(2, '0'), String(dd).padStart(2, '0')].join('-');
            break;
        }
        case 'this_week': {
            const day = now.getDay();
            const mon = new Date(now); mon.setDate(d - (day === 0 ? 6 : day - 1));
            const my = mon.getFullYear(), mm = mon.getMonth(), md = mon.getDate();
            dateFrom = [my, String(mm + 1).padStart(2, '0'), String(md).padStart(2, '0')].join('-');
            dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        }
        case 'last_week': {
            const day = now.getDay();
            const lastMon = new Date(now); lastMon.setDate(d - (day === 0 ? 6 : day - 1) - 7);
            const lmy = lastMon.getFullYear(), lmm = lastMon.getMonth(), lmd = lastMon.getDate();
            dateFrom = [lmy, String(lmm + 1).padStart(2, '0'), String(lmd).padStart(2, '0')].join('-');
            const lastSun = new Date(lastMon); lastSun.setDate(lastSun.getDate() + 6);
            const lsy = lastSun.getFullYear(), lsm = lastSun.getMonth(), lsd = lastSun.getDate();
            dateTo = [lsy, String(lsm + 1).padStart(2, '0'), String(lsd).padStart(2, '0')].join('-');
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
            dateFrom = dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
    }
    return { dateFrom, dateTo };
}

function renderSupplierInvoicesShell() {
    console.log('renderSupplierInvoicesShell() called');
    const page = document.getElementById('purchases');
    if (!page) return;
    
    const today = getLocalDateString();
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.1rem;">
                    <i class="fas fa-file-invoice-dollar"></i> Supplier Invoices
                    <span style="font-size: 0.75rem; color: var(--text-secondary); margin-left: 0.35rem; font-weight: normal;">(Receiving - Add Stock)</span>
                </h3>
                <button class="btn btn-primary btn-sm" onclick="if(window.createNewSupplierInvoice) window.createNewSupplierInvoice()">
                    <i class="fas fa-plus"></i> New Supplier Invoice
                </button>
            </div>
            
            <div class="card-body" style="padding: 0.5rem 0.75rem;">
                <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; font-size: 0.8rem;">
                    <select id="supplierInvoicesDateFilter" class="form-input" style="width: 120px; padding: 0.35rem 0.5rem;" onchange="if(window.toggleSupplierInvoicesCustomDates) window.toggleSupplierInvoicesCustomDates()">
                        <option value="today" ${supplierInvoicesDateFilter === 'today' ? 'selected' : ''}>Today</option>
                        <option value="yesterday" ${supplierInvoicesDateFilter === 'yesterday' ? 'selected' : ''}>Yesterday</option>
                        <option value="this_week" ${supplierInvoicesDateFilter === 'this_week' ? 'selected' : ''}>This Week</option>
                        <option value="last_week" ${supplierInvoicesDateFilter === 'last_week' ? 'selected' : ''}>Last Week</option>
                        <option value="this_month" ${supplierInvoicesDateFilter === 'this_month' ? 'selected' : ''}>This Month</option>
                        <option value="last_month" ${supplierInvoicesDateFilter === 'last_month' ? 'selected' : ''}>Last Month</option>
                        <option value="this_year" ${supplierInvoicesDateFilter === 'this_year' ? 'selected' : ''}>This Year</option>
                        <option value="last_year" ${supplierInvoicesDateFilter === 'last_year' ? 'selected' : ''}>Last Year</option>
                        <option value="custom" ${supplierInvoicesDateFilter === 'custom' ? 'selected' : ''}>Custom</option>
                    </select>
                    <div id="supplierInvoicesCustomDateRange" style="display: ${supplierInvoicesDateFilter === 'custom' ? 'flex' : 'none'}; gap: 0.35rem; align-items: center;">
                        <input type="date" class="form-input" id="filterDateFrom" value="${today}" style="width: 120px; padding: 0.35rem 0.5rem;">
                        <span>-</span>
                        <input type="date" class="form-input" id="filterDateTo" value="${today}" style="width: 120px; padding: 0.35rem 0.5rem;">
                    </div>
                    <button id="applyDateFilterBtn" class="btn btn-primary btn-sm" onclick="if(window.applyDateFilter) window.applyDateFilter()">
                        <i class="fas fa-check"></i> Apply
                    </button>
                    <button class="btn btn-outline btn-sm" onclick="if(window.clearDateFilter) window.clearDateFilter()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                    <select id="supplierInvoicesUserFilter" class="form-input" style="width: 90px; padding: 0.35rem 0.5rem;" onchange="if(window.applyDateFilter) window.applyDateFilter()" title="Show my documents or all">
                        <option value="self" ${supplierInvoicesUserFilter === 'self' ? 'selected' : ''}>Self</option>
                        <option value="all" ${supplierInvoicesUserFilter === 'all' ? 'selected' : ''}>All</option>
                    </select>
                    <input type="text" class="form-input" id="purchaseSearchInput" placeholder="Search invoice, supplier..." onkeyup="if(window.filterPurchaseDocuments) window.filterPurchaseDocuments()" style="width: 160px; padding: 0.35rem 0.5rem;">
                </div>
                
                <div class="table-container" style="max-height: calc(100vh - 180px); overflow: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 10; box-shadow: 0 1px 2px rgba(0,0,0,0.06);">
                            <tr>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Supplier Invoice #</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Date</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Total</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Paid</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Balance</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Supplier</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="supplierInvoicesTableBody">
                            <tr>
                                <td colspan="9" style="padding: 1.5rem; text-align: center; font-size: 0.8rem;">
                                    <div class="spinner" style="margin: 0 auto 0.5rem;"></div>
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

function toggleSupplierInvoicesCustomDates() {
    const sel = document.getElementById('supplierInvoicesDateFilter');
    const customRange = document.getElementById('supplierInvoicesCustomDateRange');
    if (!sel || !customRange) return;
    supplierInvoicesDateFilter = sel.value || 'today';
    customRange.style.display = supplierInvoicesDateFilter === 'custom' ? 'flex' : 'none';
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
    
    const userFilterEl = document.getElementById('supplierInvoicesUserFilter');
    const userFilter = (userFilterEl && userFilterEl.value) ? userFilterEl.value : supplierInvoicesUserFilter;
    const searchTerm = (document.getElementById('purchaseSearchInput')?.value || '').trim().toLowerCase();
    let list = purchaseDocuments.slice();
    if (userFilter === 'self' && typeof CONFIG !== 'undefined' && CONFIG.USER_ID) {
        const uid = String(CONFIG.USER_ID);
        list = list.filter(doc => doc && (String(doc.created_by || '') === uid));
    }
    if (searchTerm) {
        list = list.filter(doc => {
            const num = String(doc.invoice_number || '').toLowerCase();
            const sup = String(doc.supplier_name || '').toLowerCase();
            return num.includes(searchTerm) || sup.includes(searchTerm);
        });
    }
    
    if (list.length === 0) {
        var emptyHtml = (window.EmptyStateWatermark && window.EmptyStateWatermark.render)
            ? window.EmptyStateWatermark.render({ title: 'No supplier invoices yet', description: 'Create your first supplier invoice to get started' })
            : '<p style="color: var(--text-secondary); margin: 0.5rem 0;">No supplier invoices found</p>';
        tbody.innerHTML = '<tr><td colspan="9" style="padding: 1.5rem; text-align: center; font-size: 0.8rem;">' + emptyHtml + '<button class="btn btn-primary btn-sm" onclick="if(window.createNewSupplierInvoice) window.createNewSupplierInvoice()" style="margin-top: 1rem;"><i class="fas fa-plus"></i> Create Your First Supplier Invoice</button></td></tr>';
        return;
    }
    
    tbody.innerHTML = list.map(doc => {
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
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">
                    <a href="#" onclick="event.stopPropagation(); if(window.viewSupplierInvoice) window.viewSupplierInvoice('${doc.id}'); return false;" style="color: var(--primary-color); font-weight: 600; text-decoration: none; font-size: 0.8rem;">${doc.invoice_number || '—'}</a>
                </td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${formatDate(doc.invoice_date || doc.created_at)}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);"><strong>${formatCurrency(total)}</strong></td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${formatCurrency(paid)}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);"><strong style="color: ${balance > 0 ? 'var(--danger-color)' : 'var(--success-color)'}">${formatCurrency(balance)}</strong></td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">${doc.supplier_name || '—'}</td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">
                    <span class="badge ${docStatusClass}" style="font-size: 0.7rem;">${docStatus}</span>
                    <span class="badge ${paymentStatusClass}" style="margin-left: 0.2rem; font-size: 0.7rem;">${paymentStatus}</span>
                </td>
                <td style="padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-color);">
                    ${docStatus === 'DRAFT' ? `<button class="btn btn-primary btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.batchSupplierInvoice) window.batchSupplierInvoice('${doc.id}', this)" title="Batch"><i class="fas fa-boxes"></i></button>` : ''}
                    <button class="btn btn-outline btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.updateInvoicePayment) window.updateInvoicePayment('${doc.id}', ${total}, ${paid})" title="Payment"><i class="fas fa-money-bill-wave"></i></button>
                    <button class="btn btn-outline btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.viewPurchaseDocument) window.viewPurchaseDocument('${doc.id}', 'invoice')" title="View"><i class="fas fa-eye"></i></button>
                    <button class="btn btn-outline btn-sm" style="padding: 0.2rem 0.4rem; font-size: 0.75rem;" onclick="event.stopPropagation(); if(window.downloadSupplierInvoicePdf) window.downloadSupplierInvoicePdf('${doc.id}', '${String(doc.invoice_number || '').replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\\\'")}')" title="PDF"><i class="fas fa-file-pdf"></i></button>
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
    
    const today = getLocalDateString();
    
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
        var emptyHtml = (window.EmptyStateWatermark && window.EmptyStateWatermark.render)
            ? window.EmptyStateWatermark.render({ title: 'No credit notes yet', description: 'Create your first credit note when needed' })
            : '<p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No credit notes found</p>';
        tbody.innerHTML = '<tr><td colspan="6" style="padding: 3rem; text-align: center;">' + emptyHtml + '<button class="btn btn-primary" onclick="if(window.createNewCreditNote) window.createNewCreditNote()" style="margin-top: 1rem;"><i class="fas fa-plus"></i> Create Your First Credit Note</button></td></tr>';
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
        
        // Get filter values (for orders, default to today when empty so we don't list all orders)
        const dateFromEl = document.getElementById('filterDateFrom');
        const dateToEl = document.getElementById('filterDateTo');
        const today = getLocalDateString();
        let dateFrom, dateTo;
        if (documentType === 'invoice') {
            const presetEl = document.getElementById('supplierInvoicesDateFilter');
            const preset = (presetEl && presetEl.value) ? presetEl.value : supplierInvoicesDateFilter;
            const range = getSupplierInvoicesDateRange(preset);
            if (range) {
                dateFrom = range.dateFrom;
                dateTo = range.dateTo;
            } else {
                dateFrom = dateFromEl?.value?.trim() || today;
                dateTo = dateToEl?.value?.trim() || today;
            }
        } else {
            dateFrom = dateFromEl?.value?.trim() || (documentType === 'order' ? today : null);
            dateTo = dateToEl?.value?.trim() || (documentType === 'order' ? today : null);
        }
        const supplierId = document.getElementById('filterSupplier')?.value || null;
        // For orders: do not use status filter unless we have an explicit orders status dropdown (with "All" default).
        // This ensures approved orders always show and avoids any stray filterStatus from other views.
        const status = documentType === 'invoice' ? (document.getElementById('filterStatus')?.value || null) : null;
        
        if (documentType === 'order') {
            // Load purchase orders (no status filter so PENDING, APPROVED, RECEIVED, CANCELLED all show)
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
                    <input type="date" class="form-input" name="date_from" value="${getLocalDateString()}">
                </div>
                <div class="form-group">
                    <label class="form-label">Date To</label>
                    <input type="date" class="form-input" name="date_to" value="${getLocalDateString()}">
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
    if (currentPurchaseSubPage === 'orders') {
        const presetEl = document.getElementById('purchaseOrdersDateFilter');
        if (presetEl) purchaseOrdersDateFilter = presetEl.value || 'today';
        const userEl = document.getElementById('purchaseOrdersUserFilter');
        if (userEl) purchaseOrdersUserFilter = userEl.value || 'self';
        if (purchaseOrdersDateFilter !== 'custom') {
            const range = getSupplierInvoicesDateRange(purchaseOrdersDateFilter);
            if (range) {
                const fromEl = document.getElementById('filterDateFrom');
                const toEl = document.getElementById('filterDateTo');
                if (fromEl) fromEl.value = range.dateFrom;
                if (toEl) toEl.value = range.dateTo;
            }
        }
    }
    if (currentPurchaseSubPage === 'invoices') {
        const presetEl = document.getElementById('supplierInvoicesDateFilter');
        if (presetEl) supplierInvoicesDateFilter = presetEl.value || 'today';
        if (supplierInvoicesDateFilter !== 'custom') {
            const range = getSupplierInvoicesDateRange(supplierInvoicesDateFilter);
            if (range) {
                const fromEl = document.getElementById('filterDateFrom');
                const toEl = document.getElementById('filterDateTo');
                if (fromEl) fromEl.value = range.dateFrom;
                if (toEl) toEl.value = range.dateTo;
            }
        }
        const userEl = document.getElementById('supplierInvoicesUserFilter');
        if (userEl) supplierInvoicesUserFilter = userEl.value || 'self';
    }
    const docType = currentPurchaseSubPage === 'orders' ? 'order' : 
                   currentPurchaseSubPage === 'invoices' ? 'invoice' : 'credit-note';
    const applyBtn = document.getElementById('applyDateFilterBtn');
    const originalBtnHtml = applyBtn ? applyBtn.innerHTML : null;
    try {
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...';
        }
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
    } finally {
        if (applyBtn && originalBtnHtml) {
            applyBtn.disabled = false;
            applyBtn.innerHTML = originalBtnHtml;
        }
    }
}

// Clear date filter (uses new pattern)
function clearDateFilter() {
    const today = getLocalDateString();
    const dateFromInput = document.getElementById('filterDateFrom');
    const dateToInput = document.getElementById('filterDateTo');
    if (dateFromInput) dateFromInput.value = today;
    if (dateToInput) dateToInput.value = today;
    if (currentPurchaseSubPage === 'orders') {
        purchaseOrdersDateFilter = 'this_week';
        purchaseOrdersUserFilter = 'self';
        const orderPresetEl = document.getElementById('purchaseOrdersDateFilter');
        if (orderPresetEl) orderPresetEl.value = 'this_week';
        const orderCustomRange = document.getElementById('purchaseOrdersCustomDateRange');
        if (orderCustomRange) orderCustomRange.style.display = 'none';
        const orderUserEl = document.getElementById('purchaseOrdersUserFilter');
        if (orderUserEl) orderUserEl.value = 'self';
    }
    const presetEl = document.getElementById('supplierInvoicesDateFilter');
    if (presetEl) {
        supplierInvoicesDateFilter = 'today';
        presetEl.value = 'today';
        const customRange = document.getElementById('supplierInvoicesCustomDateRange');
        if (customRange) customRange.style.display = 'none';
    }
    const userEl = document.getElementById('supplierInvoicesUserFilter');
    if (userEl) {
        supplierInvoicesUserFilter = 'self';
        userEl.value = 'self';
    }
    applyDateFilter();
}

function togglePurchaseOrdersCustomDates() {
    const sel = document.getElementById('purchaseOrdersDateFilter');
    const customRange = document.getElementById('purchaseOrdersCustomDateRange');
    if (!sel || !customRange) return;
    purchaseOrdersDateFilter = sel.value || 'today';
    customRange.style.display = purchaseOrdersDateFilter === 'custom' ? 'flex' : 'none';
    if (purchaseOrdersDateFilter !== 'custom') {
        const range = getSupplierInvoicesDateRange(purchaseOrdersDateFilter);
        if (range) {
            const fromEl = document.getElementById('filterDateFrom');
            const toEl = document.getElementById('filterDateTo');
            if (fromEl) fromEl.value = range.dateFrom;
            if (toEl) toEl.value = range.dateTo;
        }
    }
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
        poSyncedItemIds = new Set();
    }
    
    const today = getLocalDateString();
    
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
        ${orderStatus === 'PENDING' ? `
        <button type="button" class="btn btn-primary btn-approve-po" data-order-id="${orderId}" onclick="if(window.approvePurchaseOrder) window.approvePurchaseOrder('${orderId}')" title="Approve (generates PDF with stamp &amp; signature)">
            <i class="fas fa-check-circle"></i> Approve
        </button>
        ` : ''}
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
                    
                    <!-- Transaction Items Table (add row + committed lines) -->
                    <div class="card" style="margin-bottom: 1rem;">
                        <div class="card-header" style="padding: 0.75rem 1rem;">
                            <h4 style="margin: 0; font-size: 1rem;">Items</h4>
                            <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0.25rem 0 0 0;">Search in the row below, then click <strong>Add item</strong> to add a line. Click an item name to view details.</p>
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

    // If opened from landing quick-search with an item, create PO with first supplier
    try {
        const raw = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pendingLandingDocument');
        if (raw && !isEditMode) {
            const pending = JSON.parse(raw);
            if (pending && pending.type === 'purchase_order' && pending.item) {
                sessionStorage.removeItem('pendingLandingDocument');
                (async () => {
                    try {
                        if (!window.API || !window.API.suppliers || !window.API.suppliers.list) {
                            if (typeof showToast === 'function') showToast('Suppliers API not available', 'warning');
                            return;
                        }
                        const list = await window.API.suppliers.list(window.CONFIG.COMPANY_ID);
                        const suppliers = list.suppliers || list || [];
                        const firstSupplier = Array.isArray(suppliers) ? suppliers[0] : null;
                        if (!firstSupplier || !firstSupplier.id) {
                            if (typeof showToast === 'function') showToast('Add a supplier first (Purchases → Suppliers)', 'warning');
                            return;
                        }
                        const payload = {
                            company_id: window.CONFIG.COMPANY_ID,
                            branch_id: window.CONFIG.BRANCH_ID,
                            supplier_id: firstSupplier.id,
                            order_date: getLocalDateString(),
                            reference: null,
                            notes: null,
                            status: 'PENDING',
                            created_by: window.CONFIG.USER_ID,
                            items: [mapTableItemToOrderItem(pending.item)]
                        };
                        const order = await window.API.purchases.createOrder(payload);
                        currentDocument = { type: 'order', id: order.id, order_number: order.order_number, status: order.status };
                        poSyncedItemIds = new Set((order.items || []).map(i => i.item_id));
                        documentItems = (order.items || []).map(i => ({
                            item_id: i.item_id,
                            item_name: i.item_name || '',
                            item_sku: i.item_code || '',
                            item_code: i.item_code || '',
                            unit_name: i.unit_name || 'unit',
                            quantity: i.quantity || 1,
                            unit_price: i.unit_price != null ? i.unit_price : 0,
                            total: i.total_price != null ? i.total_price : 0,
                            is_empty: false
                        }));
                        await renderCreatePurchaseOrderPage();
                        if (typeof showToast === 'function') showToast('Purchase order created. Add more items or save when ready.', 'success');
                    } catch (e) {
                        if (typeof showToast === 'function') showToast((e && e.message) ? e.message : 'Could not create order', 'error');
                    }
                })();
            }
        }
    } catch (_) {}
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
            let batches = [];
            if (item.batch_data && String(item.batch_data).trim()) {
                try {
                    const parsed = JSON.parse(item.batch_data);
                    batches = Array.isArray(parsed) ? parsed : [];
                } catch (e) {
                    console.warn('Error parsing batch_data:', e);
                }
            }
            const disp = getSupplierInvoiceItemDisplay(item, supplierInvoiceItemDisplayCache);
            return {
                item_id: item.item_id,
                item_name: disp.item_name || 'Item',
                item_sku: disp.item_code,
                item_code: disp.item_code,
                quantity: parseFloat(item.quantity) || 0,
                unit_name: item.unit_name,
                unit_price: parseFloat(item.unit_cost_exclusive) || 0,
                tax_percent: parseFloat(item.vat_rate) || 0,
                discount_percent: 0,
                total: parseFloat(item.line_total_inclusive) || 0,
                batches
            };
        });
        supplierInvoiceSyncedItemIds = new Set((invoiceData.items || []).map(i => i.item_id));
    } else if (!isEditMode) {
        documentItems = [];
        supplierInvoiceSyncedItemIds = new Set();
    }
    
    const today = invoiceData ? invoiceData.invoice_date : getLocalDateString();
    let supplierId = invoiceData ? invoiceData.supplier_id : '';
    let supplierName = invoiceData ? invoiceData.supplier_name : '';
    // Pre-fill supplier when opened from supplier detail "Record New Invoice"
    if (!isEditMode && window.preferredSupplierForNewInvoice) {
        supplierId = window.preferredSupplierForNewInvoice;
        try {
            const s = await API.suppliers.get(supplierId);
            if (s) supplierName = s.name || s.company_name || '';
        } catch (_) {}
        window.preferredSupplierForNewInvoice = null; // Clear after use
    }
    const supplierInvoiceNumber = invoiceData ? invoiceData.reference : '';
    const reference = invoiceData ? invoiceData.reference : '';
    const isCreateWithItems = !isEditMode && documentItems.length >= 1;
    const isReadOnly = (currentDocument && currentDocument.readOnly) || (invoiceData && invoiceData.status === 'BATCHED');
    const supplierInvoiceTitleText = isReadOnly && invoiceData && invoiceData.invoice_number
        ? `View Supplier Invoice: ${invoiceData.invoice_number}`
        : (isEditMode && invoiceData && invoiceData.invoice_number
            ? `Edit Supplier Invoice: ${invoiceData.invoice_number}`
            : (isCreateWithItems ? 'Create Supplier Invoice (Draft)' : 'Create Supplier Invoice'));
    const supplierInvoiceActionButtonsHtml = isEditMode && invoiceData ? `
        <button type="button" class="btn btn-outline" onclick="if(window.downloadSupplierInvoicePdf) window.downloadSupplierInvoicePdf('${invoiceData.id}', '${String(invoiceData.invoice_number || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'")}')" title="Download PDF">
            <i class="fas fa-file-pdf"></i> Download PDF
        </button>
        ${invoiceData.status === 'DRAFT' ? `
            <button type="button" class="btn btn-primary" id="batchInvoiceBtn" onclick="if(window.batchSupplierInvoice) window.batchSupplierInvoice('${invoiceData.id}', this)" title="Batch Invoice (Add Stock)">
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
    ` : (isCreateWithItems ? `
        <button type="button" class="btn btn-outline" disabled title="Save invoice first to enable">
            <i class="fas fa-file-pdf"></i> Download PDF
        </button>
        <button type="button" class="btn btn-primary" disabled title="Save invoice first to enable">
            <i class="fas fa-boxes"></i> Batch Invoice
        </button>
        <button type="button" class="btn btn-outline btn-danger" disabled title="Save invoice first to enable">
            <i class="fas fa-trash"></i> Delete
        </button>
    ` : '');
    
    page.innerHTML = `
        <div class="card" id="supplierInvoiceDocumentCard" style="transform-origin: top left; transition: transform 0.2s;">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border-color); position: sticky; top: 0; background: white; z-index: 10;">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <h3 class="card-title" style="margin: 0; font-size: 1.25rem;">
                        <i class="fas fa-file-invoice"></i> <span id="supplierInvoiceTitleText">${supplierInvoiceTitleText}</span>
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
                    <span id="supplierInvoiceActionButtons">${supplierInvoiceActionButtonsHtml}</span>
                    ${isReadOnly ? '' : `<button type="submit" class="btn btn-primary" form="purchaseInvoiceForm">
                        <i class="fas fa-save"></i> ${isEditMode ? 'Update' : 'Save'} Invoice
                    </button>`}
                    ${isReadOnly ? '<span style="font-size: 0.875rem; color: var(--text-secondary); align-self: center;">View only. Only payment can be updated from Supplier or Payments.</span>' : ''}
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
                                               ${isReadOnly ? 'disabled' : ''}
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
                                           value="${today}" required ${isReadOnly ? 'disabled' : ''}>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label" data-role="supplier-invoice-number-label">Supplier's Invoice Number</label>
                                    <input type="text" class="form-input" name="supplier_invoice_number" 
                                           value="${supplierInvoiceNumber || ''}"
                                           placeholder="Enter supplier's invoice number (optional)" ${isReadOnly ? 'disabled' : ''}>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Reference / Comments</label>
                                    <input type="text" class="form-input" name="reference" 
                                           value="${reference || ''}"
                                           placeholder="Optional reference or comments" ${isReadOnly ? 'disabled' : ''}>
                                </div>
                            </div>
                            <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0.25rem 0 0 0;">
                                VAT is per item (from item master). Total VAT is the sum of each line&apos;s VAT.
                            </p>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table (add row + committed lines) -->
                    <div class="card" style="margin-bottom: 1rem;">
                        <div class="card-header" style="padding: 0.75rem 1rem;">
                            <h4 style="margin: 0; font-size: 1rem;">Items Received</h4>
                            <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0.25rem 0 0 0;">
                                Search in the row below, then click <strong>Add item</strong> to add a line. Use &quot;Manage Batches&quot; to distribute items across batches.
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
    
    // Populate supplier field (edit mode or pre-filled from supplier detail)
    if (supplierId) {
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

// Update Create Supplier Invoice header when first item is added (show Draft + disabled Batch/Delete/PDF)
function updateSupplierInvoiceCreateHeader(showDraft) {
    if (currentPurchaseSubPage !== 'create-invoice') return;
    if (currentDocument && currentDocument.invoiceId) return;
    const titleEl = document.getElementById('supplierInvoiceTitleText');
    const buttonsEl = document.getElementById('supplierInvoiceActionButtons');
    if (titleEl) titleEl.textContent = showDraft ? 'Create Supplier Invoice (Draft)' : 'Create Supplier Invoice';
    if (buttonsEl) {
        buttonsEl.innerHTML = showDraft ? `
            <button type="button" class="btn btn-outline" disabled title="Save invoice first to enable">
                <i class="fas fa-file-pdf"></i> Download PDF
            </button>
            <button type="button" class="btn btn-primary" disabled title="Save invoice first to enable">
                <i class="fas fa-boxes"></i> Batch Invoice
            </button>
            <button type="button" class="btn btn-outline btn-danger" disabled title="Save invoice first to enable">
                <i class="fas fa-trash"></i> Delete
            </button>
        ` : '';
    }
}

function mapTableItemToSupplierInvoiceItem(item) {
    const itemData = {
        item_id: item.item_id,
        unit_name: item.unit_name || 'unit',
        quantity: parseFloat(item.quantity) || 1,
        unit_cost_exclusive: parseFloat(item.unit_price) || 0,
        vat_rate: item.tax_percent != null && item.tax_percent !== '' ? Number(item.tax_percent) : 0
    };
    if (item.batches && Array.isArray(item.batches) && item.batches.length > 0) {
        itemData.batches = item.batches.map(b => ({
            batch_number: b.batch_number || '',
            expiry_date: b.expiry_date || null,
            quantity: parseFloat(b.quantity) || 0,
            unit_cost: parseFloat(b.unit_cost) || 0
        }));
    }
    return itemData;
}

async function onSupplierInvoiceAddItem(item) {
    const invoiceId = currentDocument && currentDocument.invoiceId;
    try {
        if (!invoiceId) {
            const form = document.getElementById('purchaseInvoiceForm');
            if (!form) {
                showToast('Form not found', 'error');
                return;
            }
            const fd = new FormData(form);
            const supplierId = fd.get('supplier_id');
            if (!supplierId) {
                showToast('Select a supplier first', 'warning');
                return;
            }
            if (item.item_id != null) {
                const idKey = String(item.item_id);
                if (!supplierInvoiceItemDisplayCache[idKey]) supplierInvoiceItemDisplayCache[idKey] = {};
                if (item.item_name && item.item_name !== '=') supplierInvoiceItemDisplayCache[idKey].item_name = item.item_name;
                if (item.item_code && item.item_code !== '=') supplierInvoiceItemDisplayCache[idKey].item_code = item.item_code;
            }
            const payload = {
                company_id: CONFIG.COMPANY_ID,
                branch_id: CONFIG.BRANCH_ID,
                supplier_id: supplierId,
                invoice_date: fd.get('document_date') || getLocalDateString(),
                supplier_invoice_number: fd.get('supplier_invoice_number') || null,
                reference: fd.get('reference') || null,
                status: 'DRAFT',
                payment_status: 'UNPAID',
                amount_paid: 0,
                created_by: CONFIG.USER_ID,
                items: [mapTableItemToSupplierInvoiceItem(item)]
            };
            const invoice = await API.purchases.createInvoice(payload);
            currentDocument.invoiceId = invoice.id;
            currentDocument.mode = 'edit';
            currentDocument.invoiceData = invoice;
            currentDocument.invoiceNumber = invoice.invoice_number;
            supplierInvoiceSyncedItemIds = new Set((invoice.items || []).map(i => i.item_id));
            documentItems = (invoice.items || []).map(i => {
                const disp = getSupplierInvoiceItemDisplay(i, supplierInvoiceItemDisplayCache);
                const parsed = i.batch_data ? (() => { try { return JSON.parse(i.batch_data); } catch (e) { return null; } })() : null;
                const batches = parsed || (String(i.item_id) === String(item.item_id) && item.batches && item.batches.length ? item.batches : null);
                return {
                    item_id: i.item_id,
                    item_name: disp.item_name,
                    item_sku: disp.item_code,
                    item_code: disp.item_code,
                    unit_name: i.unit_name,
                    quantity: i.quantity,
                    unit_price: i.unit_cost_exclusive,
                    tax_percent: i.vat_rate,
                    total: i.line_total_inclusive,
                    batches: batches
                };
            });
            if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
                transactionItemsTable.setItems(documentItems);
            }
            showToast('Draft invoice created. Add more items or use Manage Batches, then Batch to add stock.', 'success');
            return;
        }
        if (item.item_id != null) {
            const idKey = String(item.item_id);
            if (!supplierInvoiceItemDisplayCache[idKey]) supplierInvoiceItemDisplayCache[idKey] = {};
            if (item.item_name && item.item_name !== '=') supplierInvoiceItemDisplayCache[idKey].item_name = item.item_name;
            if (item.item_code && item.item_code !== '=') supplierInvoiceItemDisplayCache[idKey].item_code = item.item_code;
        }
        const updated = await API.purchases.addInvoiceItem(invoiceId, mapTableItemToSupplierInvoiceItem(item));
        supplierInvoiceSyncedItemIds.add(item.item_id);
        documentItems = (updated.items || []).map(i => {
            const disp = getSupplierInvoiceItemDisplay(i, supplierInvoiceItemDisplayCache);
            const parsed = i.batch_data ? (() => { try { return JSON.parse(i.batch_data); } catch (e) { return null; } })() : null;
            const batches = parsed || (String(i.item_id) === String(item.item_id) && item.batches && item.batches.length ? item.batches : null);
            return {
                item_id: i.item_id,
                item_name: disp.item_name,
                item_sku: disp.item_code,
                item_code: disp.item_code,
                unit_name: i.unit_name,
                quantity: i.quantity,
                unit_price: i.unit_cost_exclusive,
                tax_percent: i.vat_rate,
                total: i.line_total_inclusive,
                batches: batches
            };
        });
        if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
            transactionItemsTable.setItems(documentItems);
        }
    } catch (err) {
        const msg = (err && err.message) || String(err);
        if (msg.indexOf('already exists') !== -1) {
            showToast('Item already on this invoice. Remove the line or choose a different item.', 'warning');
        } else {
            showToast(msg, 'error');
        }
    }
}

// Initialize TransactionItemsTable component for Invoice
function initializeTransactionItemsTableForInvoice() {
    const container = document.getElementById('transactionItemsContainerInvoice');
    if (!container) {
        setTimeout(initializeTransactionItemsTableForInvoice, 100);
        return;
    }

    const isReadOnly = (currentDocument && currentDocument.readOnly) || (currentDocument && currentDocument.invoiceData && currentDocument.invoiceData.status === 'BATCHED');
    
    const items = documentItems.length > 0 
        ? documentItems.map(item => ({
            id: item.item_id,
            item_id: item.item_id,
            item_name: item.item_name,
            item_sku: item.item_sku,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price: item.unit_price,
            tax_percent: item.tax_percent != null && item.tax_percent !== '' ? Number(item.tax_percent) : 0,
            total: item.total,
            batches: item.batches || [],
            is_empty: false
        }))
        : [];
    
    transactionItemsTable = new window.TransactionItemsTable({
        mountEl: container,
        mode: 'purchase',
        items: items,
        priceType: 'purchase_price',
        canEdit: !isReadOnly,
        useAddRow: true,
        onAddItem: onSupplierInvoiceAddItem,
        onBatchSaved: async (itemId, batches) => {
            const invoiceId = currentDocument && currentDocument.invoiceId;
            if (!invoiceId) return;
            await API.purchases.updateInvoiceItem(invoiceId, itemId, { batches });
            const updated = await API.purchases.getInvoice(invoiceId);
            const currentByItemId = (transactionItemsTable && transactionItemsTable.items) ? transactionItemsTable.items.reduce((acc, it) => { if (it.item_id) acc[String(it.item_id)] = it; return acc; }, {}) : {};
            documentItems = (updated.items || []).map(i => {
                const disp = getSupplierInvoiceItemDisplay(i, supplierInvoiceItemDisplayCache);
                const apiCost = parseFloat(i.unit_cost_exclusive);
                const current = currentByItemId[String(i.item_id)];
                const unit_price = (typeof apiCost === 'number' && !isNaN(apiCost) && apiCost > 0) ? apiCost : (current && (current.unit_price != null && current.unit_price !== '')) ? parseFloat(current.unit_price) : (typeof apiCost === 'number' && !isNaN(apiCost)) ? apiCost : 0;
                let batches = [];
                if (i.batch_data && String(i.batch_data).trim()) {
                    try { batches = JSON.parse(i.batch_data); if (!Array.isArray(batches)) batches = []; } catch (e) { batches = current && current.batches ? current.batches : []; }
                } else if (current && current.batches && current.batches.length) batches = current.batches;
                return {
                    item_id: i.item_id,
                    item_name: disp.item_name,
                    item_sku: disp.item_code,
                    item_code: disp.item_code,
                    unit_name: i.unit_name,
                    quantity: parseFloat(i.quantity) || 0,
                    unit_price,
                    tax_percent: parseFloat(i.vat_rate) || 0,
                    total: parseFloat(i.line_total_inclusive) || 0,
                    batches
                };
            });
            if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
                transactionItemsTable.setItems(documentItems);
            }
        },
        onItemsChange: (validItems) => {
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
            const invoiceId = currentDocument && currentDocument.invoiceId;
            if (!invoiceId) {
                if (typeof updateSupplierInvoiceCreateHeader === 'function') updateSupplierInvoiceCreateHeader(validItems.length >= 1);
                return;
            }
            const validItemIds = new Set(validItems.filter(i => i.item_id).map(i => i.item_id));
            const toRemove = [...supplierInvoiceSyncedItemIds].filter(id => !validItemIds.has(id));
            if (toRemove.length === 0) return;
            (async () => {
                for (const itemId of toRemove) {
                    try {
                        await API.purchases.deleteInvoiceItem(invoiceId, itemId);
                        supplierInvoiceSyncedItemIds.delete(itemId);
                    } catch (err) {
                        showToast((err && err.message) || 'Failed to remove item', 'error');
                    }
                }
                const updated = await API.purchases.getInvoice(invoiceId);
                const currentByItemId = (transactionItemsTable && transactionItemsTable.items) ? transactionItemsTable.items.reduce((acc, it) => { if (it.item_id) acc[String(it.item_id)] = it; return acc; }, {}) : {};
                documentItems = (updated.items || []).map(i => {
                    const disp = getSupplierInvoiceItemDisplay(i, supplierInvoiceItemDisplayCache);
                    const apiCost = parseFloat(i.unit_cost_exclusive);
                    const current = currentByItemId[String(i.item_id)];
                    const unit_price = (typeof apiCost === 'number' && !isNaN(apiCost) && apiCost > 0) ? apiCost : (current && (current.unit_price != null && current.unit_price !== '')) ? parseFloat(current.unit_price) : (typeof apiCost === 'number' && !isNaN(apiCost)) ? apiCost : 0;
                    let batches = [];
                    if (i.batch_data && String(i.batch_data).trim()) {
                        try { batches = JSON.parse(i.batch_data); if (!Array.isArray(batches)) batches = []; } catch (e) { batches = current && current.batches ? current.batches : []; }
                    } else if (current && current.batches && current.batches.length) batches = current.batches;
                    return {
                        item_id: i.item_id,
                        item_name: disp.item_name,
                        item_sku: disp.item_code,
                        item_code: disp.item_code,
                        unit_name: i.unit_name,
                        quantity: parseFloat(i.quantity) || 0,
                        unit_price,
                        tax_percent: parseFloat(i.vat_rate) || 0,
                        total: parseFloat(i.line_total_inclusive) || 0,
                        batches
                    };
                });
                if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
                    transactionItemsTable.setItems(documentItems);
                }
            })();
        },
        onTotalChange: () => {},
        onItemCreate: (query, rowIndex, callback) => {
            window._transactionItemCreateCallback = callback;
            window._transactionItemCreateRowIndex = rowIndex;
            if (query) window._transactionItemCreateName = query;
            if (typeof showAddItemModal === 'function') {
                showAddItemModal();
                setTimeout(() => {
                    const nameInput = document.querySelector('#itemForm input[name="name"]');
                    if (nameInput && query) nameInput.value = query;
                }, 100);
            } else {
                showToast(`To create item "${query}", please go to Items page`, 'info');
            }
        }
    });
    
    window[`transactionTable_transactionItemsContainerInvoice`] = transactionItemsTable;
}

function mapTableItemToOrderItem(item) {
    return {
        item_id: item.item_id,
        unit_name: item.unit_name || 'unit',
        quantity: parseFloat(item.quantity) || 1,
        unit_price: parseFloat(item.unit_price) || 0
    };
}

async function onPurchaseOrderAddItem(item) {
    const orderId = currentDocument && currentDocument.id;
    try {
        if (!orderId) {
            const form = document.getElementById('purchaseDocumentForm');
            if (!form) {
                showToast('Form not found', 'error');
                return;
            }
            const fd = new FormData(form);
            const supplierId = fd.get('supplier_id');
            if (!supplierId) {
                showToast('Select a supplier first', 'warning');
                return;
            }
            const payload = {
                company_id: CONFIG.COMPANY_ID,
                branch_id: CONFIG.BRANCH_ID,
                supplier_id: supplierId,
                order_date: fd.get('document_date') || getLocalDateString(),
                reference: fd.get('reference') || null,
                notes: fd.get('notes') || null,
                status: 'PENDING',
                created_by: CONFIG.USER_ID,
                items: [mapTableItemToOrderItem(item)]
            };
            const order = await API.purchases.createOrder(payload);
            currentDocument.id = order.id;
            currentDocument.order_number = order.order_number;
            currentDocument.status = order.status;
            poSyncedItemIds = new Set((order.items || []).map(i => i.item_id));
            documentItems = (order.items || []).map(i => {
                const disp = getSupplierInvoiceItemDisplay(i, poItemDisplayCache);
                return {
                    item_id: i.item_id,
                    item_name: disp.item_name,
                    item_sku: disp.item_code,
                    item_code: disp.item_code,
                    unit_name: i.unit_name,
                    quantity: i.quantity,
                    unit_price: i.unit_price,
                    total: i.total_price,
                    is_empty: false
                };
            });
            if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
                transactionItemsTable.setItems(documentItems);
            }
            showToast('Purchase order created. Add more items or save when ready.', 'success');
            return;
        }
        if (item.item_id != null) {
            const idKey = String(item.item_id);
            if (!poItemDisplayCache[idKey]) poItemDisplayCache[idKey] = {};
            if (item.item_name && item.item_name !== '=') poItemDisplayCache[idKey].item_name = item.item_name;
            if (item.item_code && item.item_code !== '=') poItemDisplayCache[idKey].item_code = item.item_code;
        }
        const updated = await API.purchases.addOrderItem(orderId, mapTableItemToOrderItem(item));
        poSyncedItemIds.add(item.item_id);
        documentItems = (updated.items || []).map(i => {
            const disp = getSupplierInvoiceItemDisplay(i, poItemDisplayCache);
            return {
                item_id: i.item_id,
                item_name: disp.item_name,
                item_sku: disp.item_code,
                item_code: disp.item_code,
                unit_name: i.unit_name,
                quantity: i.quantity,
                unit_price: i.unit_price,
                total: i.total_price,
                is_empty: false
            };
        });
        if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
            transactionItemsTable.setItems(documentItems);
        }
    } catch (err) {
        const msg = (err && err.message) || String(err);
        if (msg.indexOf('already exists') !== -1) {
            showToast('Item already on this order. Remove the line or choose a different item.', 'warning');
        } else {
            showToast(msg, 'error');
        }
    }
}

// Initialize TransactionItemsTable component
let transactionItemsTable = null;

function initializeTransactionItemsTable(canEdit = true) {
    const container = document.getElementById('transactionItemsContainer');
    if (!container) {
        setTimeout(() => initializeTransactionItemsTable(canEdit), 100);
        return;
    }
    
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
    
    transactionItemsTable = new window.TransactionItemsTable({
        mountEl: container,
        mode: 'purchase',
        context: 'purchase_order',
        items: items,
        priceType: 'purchase_price',
        canEdit: canEdit,
        useAddRow: true,
        onAddItem: onPurchaseOrderAddItem,
        onItemsChange: (validItems) => {
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
            const orderId = currentDocument && currentDocument.id;
            if (!orderId) return;
            const validItemIds = new Set(validItems.filter(i => i.item_id).map(i => i.item_id));
            const toRemove = [...poSyncedItemIds].filter(id => !validItemIds.has(id));
            if (toRemove.length === 0) return;
            (async () => {
                for (const itemId of toRemove) {
                    try {
                        await API.purchases.deleteOrderItem(orderId, itemId);
                        poSyncedItemIds.delete(itemId);
                    } catch (err) {
                        showToast((err && err.message) || 'Failed to remove item', 'error');
                    }
                }
                const updated = await API.purchases.getOrder(orderId);
                documentItems = (updated.items || []).map(i => {
                    const disp = getSupplierInvoiceItemDisplay(i, poItemDisplayCache);
                    return {
                        item_id: i.item_id,
                        item_name: disp.item_name,
                        item_sku: disp.item_code,
                        item_code: disp.item_code,
                        unit_name: i.unit_name,
                        quantity: i.quantity,
                        unit_price: i.unit_price,
                        total: i.total_price,
                        is_empty: false
                    };
                });
                if (transactionItemsTable && typeof transactionItemsTable.setItems === 'function') {
                    transactionItemsTable.setItems(documentItems);
                }
            })();
        },
        onTotalChange: () => {},
        onItemCreate: (query, rowIndex, callback) => {
            window._transactionItemCreateCallback = callback;
            window._transactionItemCreateRowIndex = rowIndex;
            if (query) window._transactionItemCreateName = query;
            if (typeof showAddItemModal === 'function') {
                showAddItemModal();
                setTimeout(() => {
                    const nameInput = document.querySelector('#itemForm input[name="name"]');
                    if (nameInput && query) nameInput.value = query;
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
async function selectSupplier(supplierId, supplierName, searchInputId = 'supplierSearch', hiddenInputId = 'supplierId', dropdownId = 'supplierSearchDropdown') {
    const searchInput = document.getElementById(searchInputId);
    const hiddenInput = document.getElementById(hiddenInputId);
    const dropdown = document.getElementById(dropdownId);
    
    if (searchInput) searchInput.value = supplierName;
    if (hiddenInput) hiddenInput.value = supplierId;
    if (dropdown) dropdown.style.display = 'none';
    
    // Focus back on search input for quick entry
    if (searchInput) searchInput.focus();

    // When selecting supplier on the supplier invoice form, fetch supplier profile
    // and enforce "requires supplier invoice number" toggle on the invoice field.
    if (searchInputId === 'supplierSearchInvoice' && window.API && window.API.suppliers && typeof window.API.suppliers.get === 'function') {
        try {
            const supplier = await window.API.suppliers.get(supplierId);
            const input = document.querySelector('input[name="supplier_invoice_number"]');
            const label = document.querySelector('[data-role="supplier-invoice-number-label"]');
            if (!input || !label || input.disabled) return;
            const required = !!supplier.requires_supplier_invoice_number;
            input.required = required;
            if (required) {
                label.textContent = "Supplier's Invoice Number *";
                input.placeholder = 'Supplier invoice number required for this supplier *';
            } else {
                label.textContent = "Supplier's Invoice Number";
                input.placeholder = "Enter supplier's invoice number (optional)";
            }
        } catch (e) {
            console.warn('Failed to load supplier settings for invoice requirement:', e);
        }
    }
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

function getPrimaryFormActionButton(form) {
    if (!form) return null;
    // 1) Button inside the form
    let btn = form.querySelector('button[type="submit"]');
    if (btn) return btn;
    // 2) Button associated via form="<id>" (sticky headers often place it outside)
    const formId = form.getAttribute('id');
    if (formId) {
        try {
            btn = document.querySelector(`button[type="submit"][form="${CSS.escape(formId)}"]`);
        } catch {
            btn = document.querySelector(`button[type="submit"][form="${formId}"]`);
        }
        if (btn) return btn;
    }
    // 3) Edit mode save button lives in header
    return document.querySelector('.btn-save-order');
}

function setButtonSavingState(btn, isSaving, savingHtml) {
    if (!btn) return;
    if (btn.dataset && btn.dataset.originalHtml == null) {
        btn.dataset.originalHtml = btn.innerHTML;
    }
    if (isSaving) {
        btn.disabled = true;
        btn.innerHTML = savingHtml;
        return;
    }
    btn.disabled = false;
    if (btn.dataset && btn.dataset.originalHtml != null) {
        btn.innerHTML = btn.dataset.originalHtml;
    }
}

async function savePurchaseDocument(event, documentType) {
    console.log('savePurchaseDocument()');
    
    event.preventDefault();

    if (documentType === 'invoice' && currentDocument && currentDocument.invoiceData && currentDocument.invoiceData.status === 'BATCHED') {
        showToast('BATCHED invoices are read-only. Only payment can be updated.', 'info');
        return;
    }

    // Prevent duplicate submissions — block silently (no extra toast)
    if (isSavingDocument) return;

    const form = event.target;
    const submitButton = getPrimaryFormActionButton(form);
    
    // Disable submit button and set flag
    isSavingDocument = true;
    setButtonSavingState(submitButton, true, '<i class="fas fa-spinner fa-spin"></i> Saving...');
    
    const formData = new FormData(form);
    
    // Get items from component
    const items = transactionItemsTable ? transactionItemsTable.getItems() : [];
    
    if (items.length === 0) {
        isSavingDocument = false;
        setButtonSavingState(submitButton, false);
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
        isSavingDocument = false;
        setButtonSavingState(submitButton, false);
        showToast('Company and Branch must be configured', 'error');
        return;
    }
    
    try {
        const currentUserId = CONFIG.USER_ID || '29932846-bf01-4b4b-9e13-25cb27764c16';
        
        const documentData = {
            company_id: CONFIG.COMPANY_ID,
            branch_id: CONFIG.BRANCH_ID,
            supplier_id: formData.get('supplier_id'),
            order_date: formData.get('document_date') || getLocalDateString(),
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
                setButtonSavingState(submitButton, false);
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
                invoice_date: formData.get('document_date') || getLocalDateString(),
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
                
                if (result && result.invoice_number) {
                    showToast(`Supplier Invoice ${result.invoice_number} saved as DRAFT! You can Batch or Update from this page.`, 'success');
                } else {
                    showToast('Supplier Invoice saved as DRAFT! (Note: Invoice number not assigned - check branch code)', 'warning');
                }
                // Stay on create-invoice page in edit mode so user can Batch/Delete/Download PDF without going back to list
                if (result && result.id) {
                    let fullInvoice = result;
                    try {
                        fullInvoice = await API.purchases.getInvoice(result.id);
                    } catch (e) {
                        console.warn('Could not fetch full invoice after create, using result:', e);
                    }
                    currentDocument = {
                        type: 'invoice',
                        mode: 'edit',
                        invoiceId: result.id,
                        invoiceData: fullInvoice
                    };
                    isSavingDocument = false;
                    setButtonSavingState(submitButton, false);
                    await loadPurchaseSubPage('create-invoice');
                    return;
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
        setButtonSavingState(submitButton, false);
        
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
        const detail = error.data && error.data.detail;
        if (detail) {
            if (typeof detail === 'string') {
                errorMessage = detail;
            } else if (Array.isArray(detail)) {
                errorMessage = detail.map(e => e.msg || e.loc?.join('.') + ': ' + e.msg).join(', ');
            } else if (typeof detail === 'object' && detail.message) {
                errorMessage = detail.message;
                // If short-expiry blocked save, show override modal (user can then Batch with override)
                if (detail.code === 'SHORT_EXPIRY_OVERRIDE_REQUIRED') {
                    const invoiceId = currentDocument && currentDocument.invoiceId;
                    if (invoiceId && typeof showShortExpiryOverrideModal === 'function') {
                        showShortExpiryOverrideModal(invoiceId, detail, null, null);
                        return;
                    }
                }
            }
        }
        
        showToast(errorMessage, 'error');
        isSavingDocument = false; // Reset flag on error
        setButtonSavingState(submitButton, false);
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
        const isApproved = order.status === 'APPROVED';
        const footer = `
            <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            ${isPending ? `
            <button class="btn btn-outline" onclick="closeModal(); if(window.editPurchaseDocument) window.editPurchaseDocument('${order.id}', 'order')" title="Edit">
                <i class="fas fa-edit"></i> Edit
            </button>
            <button class="btn btn-outline btn-danger" onclick="closeModal(); if(window.deletePurchaseOrder) window.deletePurchaseOrder('${order.id}')" title="Delete">
                <i class="fas fa-trash"></i> Delete
            </button>
            <button class="btn btn-primary btn-approve-po" data-order-id="${order.id}" onclick="closeModal(); if(window.approvePurchaseOrder) window.approvePurchaseOrder('${order.id}')" title="Approve (generates PDF)">
                <i class="fas fa-check-circle"></i> Approve
            </button>
            ` : ''}
            ${isApproved ? `
            <button class="btn btn-outline" onclick="closeModal(); if(window.downloadPurchaseOrderPdf) window.downloadPurchaseOrderPdf('${order.id}')" title="Open PDF">
                <i class="fas fa-file-pdf"></i> Open PDF
            </button>
            <button class="btn btn-primary" onclick="closeModal(); if(window.regeneratePurchaseOrderPdf) window.regeneratePurchaseOrderPdf('${order.id}')" title="Regenerate PDF with latest stamp/logo/signature">
                <i class="fas fa-sync-alt"></i> Regenerate PDF
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
        
        // Map items using backend response (item_name, item_code); use display cache to avoid "=" / "—"
        documentItems = (order.items || []).map(item => {
            const disp = getSupplierInvoiceItemDisplay(item, poItemDisplayCache);
            return {
            item_id: item.item_id,
            item_name: disp.item_name || 'Item',
            item_sku: disp.item_code,
            item_code: disp.item_code,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price: item.unit_price,
            total: item.total_price,
            is_empty: false
            };
        });
        poSyncedItemIds = new Set((order.items || []).map(i => i.item_id));
        
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
    const submitButton = getPrimaryFormActionButton(form);
    
    // Disable submit button and set flag
    isSavingDocument = true;
    setButtonSavingState(submitButton, true, '<i class="fas fa-spinner fa-spin"></i> Saving...');
    
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
        setButtonSavingState(submitButton, false);
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
        isSavingDocument = false;
        setButtonSavingState(submitButton, false);
        loadPurchaseSubPage('orders');
    } catch (error) {
        console.error('Error updating purchase order:', error);
        showToast(error.message || 'Error updating purchase order', 'error');
        isSavingDocument = false;
        setButtonSavingState(submitButton, false);
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
        isDeletingOrder = false;
        console.error('Error deleting purchase order:', error);
        showToast(error.message || 'Error deleting purchase order', 'error');
    }
}

// Download approved purchase order PDF (opens signed URL; user can save from browser)
async function downloadPurchaseOrderPdf(orderId) {
    if (!orderId) {
        if (typeof showToast === 'function') showToast('Invalid order', 'error');
        return;
    }
    if (typeof API === 'undefined' || !API.purchases) {
        if (typeof showToast === 'function') showToast('PDF download not available', 'error');
        return;
    }
    try {
        if (typeof showToast === 'function') showToast('Opening PDF...', 'info');
        const order = await API.purchases.getOrder(orderId);
        const isApproved = (order && (order.status || '').toUpperCase()) === 'APPROVED';
        if (!order || !isApproved) {
            if (typeof showToast === 'function') showToast('PDF is available only for approved orders.', 'info');
            return;
        }
        let url;
        if (order.pdf_path && typeof API.purchases.getOrderPdfUrl === 'function') {
            try {
                const res = await API.purchases.getOrderPdfUrl(orderId);
                url = res && res.url;
            } catch (e) {
                if (e && e.status === 404) url = null;
                else throw e;
            }
        }
        if (!url && typeof API.purchases.regenerateOrderPdf === 'function') {
            if (typeof showToast === 'function') showToast('Generating PDF...', 'info');
            const res = await API.purchases.regenerateOrderPdf(orderId);
            url = res && res.url;
        }
        if (url) {
            window.open(url, '_blank');
            if (typeof showToast === 'function') showToast('PDF opened in new tab; you can save from there.', 'success');
        } else {
            if (typeof showToast === 'function') showToast('Could not get PDF URL. Ensure tenant/ Supabase is configured.', 'error');
        }
    } catch (error) {
        console.error('Error opening PO PDF:', error);
        let msg = error && (error.message || (typeof error.detail === 'string' ? error.detail : error.detail && error.detail.detail ? error.detail.detail : null) || String(error));
        if (!msg || msg === '[object Object]') msg = 'Failed to open PDF';
        if (typeof showToast === 'function') showToast(msg, 'error');
    }
}

// Force regenerate PDF (useful after stamp/logo/signature updates)
async function regeneratePurchaseOrderPdf(orderId) {
    if (!orderId) {
        if (typeof showToast === 'function') showToast('Invalid order', 'error');
        return;
    }
    if (typeof API === 'undefined' || !API.purchases || typeof API.purchases.regenerateOrderPdf !== 'function') {
        if (typeof showToast === 'function') showToast('PDF regeneration not available', 'error');
        return;
    }
    try {
        if (typeof showToast === 'function') showToast('Regenerating PDF with latest stamp...', 'info');
        const order = await API.purchases.getOrder(orderId);
        const isApproved = (order && (order.status || '').toUpperCase()) === 'APPROVED';
        if (!order || !isApproved) {
            if (typeof showToast === 'function') showToast('Only approved orders can have a PDF regenerated.', 'info');
            return;
        }
        const res = await API.purchases.regenerateOrderPdf(orderId);
        const url = res && res.url;
        if (url) {
            window.open(url, '_blank');
            if (typeof showToast === 'function') showToast('Updated PDF opened in new tab.', 'success');
        } else {
            if (typeof showToast === 'function') showToast('Could not regenerate PDF URL. Ensure tenant/Supabase is configured.', 'error');
        }
    } catch (error) {
        console.error('Error regenerating PO PDF:', error);
        let msg = error && (error.message || (typeof error.detail === 'string' ? error.detail : error.detail && error.detail.detail ? error.detail.detail : null) || String(error));
        if (!msg || msg === '[object Object]') msg = 'Failed to regenerate PDF';
        if (typeof showToast === 'function') showToast(msg, 'error');
    }
}

// Approve purchase order (sets approved_by, approved_at, generates immutable PDF)
async function approvePurchaseOrder(orderId) {
    const buttons = document.querySelectorAll(`button.btn-approve-po[data-order-id="${orderId}"]`);
    const setButtonsLoading = (loading) => {
        buttons.forEach(btn => {
            btn.disabled = loading;
            btn.innerHTML = loading
                ? '<i class="fas fa-spinner fa-spin"></i> Approving...'
                : '<i class="fas fa-check-circle"></i> Approve';
        });
    };
    setButtonsLoading(true);
    try {
        await API.purchases.approveOrder(orderId);
        showToast('Purchase order approved. PDF generated.', 'success');
        if (typeof loadPurchaseSubPage === 'function') loadPurchaseSubPage('orders');
        if (typeof renderPurchaseOrderDetail === 'function') renderPurchaseOrderDetail(orderId);
    } catch (error) {
        console.error('Error approving purchase order:', error);
        showToast(error.message || 'Error approving purchase order', 'error');
        setButtonsLoading(false);
    } finally {
        setButtonsLoading(false);
    }
}

// Print purchase order: use stored PDF if approved, else dynamic preview. printType optional; if omitted, shows Thermal/Normal choice.
async function printPurchaseOrder(orderId, printType) {
    const layout = printType != null ? printType : (typeof choosePrintLayout === 'function' ? await choosePrintLayout() : ((typeof CONFIG !== 'undefined' && CONFIG.PRINT_TYPE) || 'thermal'));
    if (layout == null) return;
    try {
        const order = await API.purchases.getOrder(orderId);
        if (order.status === 'APPROVED' && order.pdf_path && typeof API.purchases.getOrderPdfUrl === 'function') {
            const { url } = await API.purchases.getOrderPdfUrl(orderId);
            const printWindow = window.open(url, '_blank');
            if (printWindow) {
                printWindow.onload = () => { try { printWindow.print(); } catch (e) {} };
                setTimeout(() => { try { printWindow.print(); } catch (e) {} }, 1000);
            }
            return;
        }

        const mode = (typeof window.PrintService !== 'undefined' && window.PrintService.getEffectiveMode)
            ? window.PrintService.getEffectiveMode(layout) : 'A4';
        if (mode === 'THERMAL') {
            await window.PrintService.printDocument({ type: 'PURCHASE_ORDER', mode: 'THERMAL', data: order });
            return;
        }

        // Load company print settings so thermal/regular and margins are correct
        if (typeof window.loadCompanyPrintSettings === 'function') {
            await window.loadCompanyPrintSettings().catch(() => {});
        }
        const isThermal = layout === 'thermal';
        const noMargin = !!(typeof CONFIG !== 'undefined' && CONFIG.PRINT_REMOVE_MARGIN);
        const pageWidthMm = isThermal
            ? Math.min(88, Math.max(58, parseInt((typeof CONFIG !== 'undefined' && CONFIG.PRINT_PAGE_WIDTH_MM) || 80, 10) || 80))
            : 210;
        const autoCut = !!(typeof CONFIG !== 'undefined' && CONFIG.PRINT_AUTO_CUT);
        const contentWidthMm = isThermal ? 76 : null;
        const bodyPad = isThermal ? (noMargin ? '2mm' : '3mm') : (noMargin ? '10px' : '20px');
        const pageStyle = isThermal
            ? `@page { size: ${pageWidthMm}mm auto; margin: 0; }
               html, body { height: auto !important; min-height: 0 !important; }
               body { font-size: 10pt; max-width: ${contentWidthMm}mm; width: ${contentWidthMm}mm; padding: ${bodyPad}; margin: 0 auto; box-sizing: border-box; overflow-x: hidden; }
               .header { padding: 0 0 2mm 0; margin-bottom: 2mm; text-align: center; border-bottom: 1px solid #000; }
               .header h1 { margin: 0; font-size: 10pt; }
               .info-section { margin: 2mm 0; font-size: 9pt; }
               .info-grid { gap: 1mm; }
               .info-item { margin: 0.5mm 0; word-wrap: break-word; overflow-wrap: break-word; }
               table { margin: 2mm 0; table-layout: fixed; width: 100%; }
               th, td { padding: 1mm 2mm; font-size: 9pt; word-wrap: break-word; overflow-wrap: break-word; word-break: break-word; }
               .footer { margin-top: 2mm; padding-top: 2mm; font-size: 8pt; }
               .no-print { display: none !important; }
               .print-content-wrap { margin-top: 0 !important; max-width: ${contentWidthMm}mm; }`
            : `@page { size: A4; margin: ${noMargin ? '0.5cm' : '1cm'}; }
               html, body { height: auto !important; min-height: 0 !important; }
               body { font-size: 12px; max-width: 210mm; padding: ${bodyPad}; margin: 0 auto; }
               .no-print { display: none !important; }
               .print-content-wrap { margin-top: 0 !important; }`;
        const layoutLabel = isThermal ? `Thermal (${pageWidthMm}mm)` : 'Regular (A4)';
        const autoCutSpacer = (isThermal && autoCut) ? '<div class="thermal-autocut-spacer" style="height: 40mm; min-height: 40mm; page-break-after: always;"></div>' : '';
        const orderLogoUrl = (order.logo_url && typeof order.logo_url === 'string' && (order.logo_url.startsWith('http://') || order.logo_url.startsWith('https://'))) ? order.logo_url : '';
        const orderLogoUrlForPrint = orderLogoUrl ? (orderLogoUrl + (orderLogoUrl.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now()) : '';
        const formatDate = (dateStr) => {
            if (!dateStr) return '—';
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
        };
        const formatCurrency = (amount) => {
            return new Intl.NumberFormat('en-KE', { style: 'currency', currency: 'KES' }).format(amount || 0);
        };

        const printContent = `
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Purchase Order ${escapeHtml(order.order_number || '')}</title>
                <style>
                    @media print { ${pageStyle} }
                    body { font-family: Arial, sans-serif; }
                    .header { margin-bottom: ${isThermal ? '2mm' : '12px'}; }
                    .header h1 { margin: 0; color: #333; }
                    .info-section { margin-bottom: ${isThermal ? '2mm' : '16px'}; }
                    .info-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: ${isThermal ? '1mm' : '10px'}; }
                    .info-item { margin: ${isThermal ? '0.5mm 0' : '5px 0'}; }
                    .info-label { font-weight: bold; }
                    table { width: 100%; border-collapse: collapse; margin-top: ${isThermal ? '2mm' : '12px'}; }
                    th { background: #f8f9fa; padding: ${isThermal ? '1mm 2mm' : '10px'}; text-align: left; border-bottom: 2px solid #333; }
                    td { padding: ${isThermal ? '1mm 2mm' : '8px'}; border-bottom: 1px solid #ddd; }
                    .text-right { text-align: right; }
                    .text-center { text-align: center; }
                    .total-row { font-weight: bold; background: #f8f9fa; }
                    .footer { margin-top: ${isThermal ? '2mm' : '24px'}; text-align: center; color: #666; }
                </style>
            </head>
            <body>
                <div class="no-print" style="position: fixed; top: 0; left: 0; right: 0; background: #f0f0f0; padding: 8px 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; z-index: 9999; border-bottom: 1px solid #ccc; font-family: Arial, sans-serif; font-size: 14px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="color: #555;">Layout: <strong>${layoutLabel}</strong></span>
                        ${!isThermal ? '<span style="color: #856404; font-size: 12px;">For receipt printers (e.g. XP-80), switch to Thermal in Print Settings to avoid paper waste.</span>' : ''}
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <a href="#" onclick="if(window.opener){window.opener.focus();window.opener.loadPage(\'settings-print\');} return false;" style="padding: 6px 12px; background: #0066cc; color: white; text-decoration: none; border-radius: 4px; font-size: 13px;">&#9881; Customize Print Settings</a>
                        <button type="button" onclick="window.print();" style="padding: 6px 16px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px;">Print</button>
                    </div>
                </div>
                <div class="print-content-wrap" style="margin-top: 48px;">
                <div class="header" style="display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px;">
                    <div style="flex: 1; min-width: 0;">
                        <h1>PURCHASE ORDER</h1>
                        <p>${escapeHtml(order.order_number || '—')}</p>
                    </div>
                    ${(orderLogoUrlForPrint ? `<div style="flex-shrink: 0;"><img src="${orderLogoUrlForPrint.replace(/"/g, '&quot;')}" alt="Logo" style="max-height: 34px; max-width: 70px; object-fit: contain;" onerror="this.style.display='none'" /></div>` : '')}
                </div>
                <div class="info-section">
                    <div class="info-grid">
                        <div class="info-item"><span class="info-label">Date:</span> ${formatDate(order.order_date)}</div>
                        <div class="info-item"><span class="info-label">Supplier:</span> ${escapeHtml(order.supplier_name || '—')}</div>
                        <div class="info-item"><span class="info-label">Branch:</span> ${escapeHtml(order.branch_name || '—')}</div>
                        <div class="info-item"><span class="info-label">Reference:</span> ${escapeHtml(order.reference || '—')}</div>
                        <div class="info-item"><span class="info-label">Status:</span> ${escapeHtml(order.status || 'PENDING')}</div>
                        <div class="info-item"><span class="info-label">Created By:</span> ${escapeHtml(order.created_by_name || '—')}</div>
                    </div>
                    ${order.notes ? `<div class="info-item" style="margin-top: 4px;"><span class="info-label">Notes:</span> ${escapeHtml(order.notes)}</div>` : ''}
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
                                <td>${escapeHtml(item.item_name || 'Item')}${!isThermal && item.item_code ? ' (' + escapeHtml(item.item_code) + ')' : ''}</td>
                                <td class="text-center">${item.quantity != null ? Number(item.quantity) : '—'}</td>
                                <td>${escapeHtml(item.unit_name || '—')}</td>
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
                ${autoCutSpacer}
                </div>
            </body>
            </html>
        `;

        const printWindow = window.open('', '_blank');
        printWindow.document.write(printContent);
        printWindow.document.close();
        printWindow.focus();
        setTimeout(() => { printWindow.print(); }, 250);
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
    const effectiveSubPage = (currentPurchaseSubPage === 'supplier-detail' || (currentPurchaseSubPage && currentPurchaseSubPage.startsWith('suppliers-'))) ? 'suppliers' : currentPurchaseSubPage;
    subNavItemsContainer.querySelectorAll('.sub-nav-item').forEach(subItem => {
        const page = subItem.dataset.page;
        const subPage = subItem.dataset.subPage;

        if (page === 'purchases' && subPage === effectiveSubPage) {
            subItem.classList.add('active');
        } else {
            subItem.classList.remove('active');
        }
    });
}

// View/Edit Supplier Invoice - Navigate to create page (DRAFT = edit, BATCHED = read-only)
async function viewSupplierInvoice(invoiceId) {
    if (!invoiceId) return;

    // If we're already loading this exact invoice, ignore duplicate clicks.
    if (supplierInvoiceViewInProgress && String(supplierInvoiceViewCurrentId) === String(invoiceId)) {
        return;
    }

    supplierInvoiceViewInProgress = true;
    supplierInvoiceViewCurrentId = invoiceId;

    const pageOverlay = document.getElementById('pageLoadOverlay');
    if (pageOverlay) {
        pageOverlay.style.display = 'flex';
    }

    try {
        const invoice = await API.purchases.getInvoice(invoiceId);

        // If another invoice was requested after this one, ignore this response.
        if (String(supplierInvoiceViewCurrentId) !== String(invoiceId)) {
            return;
        }

        const isDraft = invoice.status === 'DRAFT';
        const isBatched = invoice.status === 'BATCHED';

        // DRAFT: edit mode. BATCHED: open as read-only (document can be viewed; only payment can be updated elsewhere).
        currentDocument = {
            type: 'invoice',
            invoiceId: invoiceId,
            mode: 'edit',
            invoiceData: invoice,
            readOnly: isBatched  // When true, form is read-only (no save/batch, disabled fields)
        };

        await loadPurchaseSubPage('create-invoice');
        if (isBatched) {
            showToast('Viewing batched invoice (read-only). Only payment can be updated from Supplier or Payments.', 'info');
        }
    } catch (error) {
        console.error('Error loading supplier invoice:', error);
        showToast(error.message || 'Error loading invoice', 'error');
    } finally {
        // Only clear global loading state if this is still the active invoice.
        if (String(supplierInvoiceViewCurrentId) === String(invoiceId)) {
            supplierInvoiceViewInProgress = false;
            supplierInvoiceViewCurrentId = null;
        }
        if (pageOverlay && !supplierInvoiceViewInProgress) {
            pageOverlay.style.display = 'none';
        }
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

async function downloadSupplierInvoicePdf(invoiceId, invoiceNumber) {
    if (typeof showToast === 'function') showToast('Preparing PDF...', 'info');
    if (!invoiceId) {
        if (typeof showToast === 'function') showToast('Invalid invoice', 'error');
        return;
    }
    if (typeof API === 'undefined' || !API.purchases || typeof API.purchases.downloadSupplierInvoicePdf !== 'function') {
        if (typeof showToast === 'function') showToast('PDF download not available', 'error');
        return;
    }
    try {
        await API.purchases.downloadSupplierInvoicePdf(invoiceId, invoiceNumber || null);
        if (typeof showToast === 'function') showToast('PDF downloaded', 'success');
    } catch (error) {
        console.error('Error downloading supplier invoice PDF:', error);
        const msg = error && (error.message || error.detail || String(error));
        if (typeof showToast === 'function') showToast(msg || 'Failed to download PDF', 'error');
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
            invoice_date: formData.get('document_date') || getLocalDateString(),
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
            <div class="form-row">
                <div class="form-group" style="display: flex; align-items: flex-end;">
                    <label style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer;">
                        <input type="checkbox" name="requires_supplier_invoice_number">
                        Require supplier invoice number on invoices
                    </label>
                </div>
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
        address: formData.get('address') || null,
        requires_supplier_invoice_number: formData.get('requires_supplier_invoice_number') === 'on',
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

// Open create-invoice page with supplier pre-filled (from supplier detail)
function openCreateInvoiceWithSupplier(supplierId) {
    window.preferredSupplierForNewInvoice = supplierId || null;
    loadPurchaseSubPage('create-invoice');
}

// When global item search opens "Purchase order" while already on #purchases, switch to create PO sub-page
if (typeof window !== 'undefined') {
    window.addEventListener('pharmasight-open-pending-document', function (e) {
        if (!e.detail || e.detail.type !== 'purchase_order') return;
        loadPurchaseSubPage('create');
    });
}

// Export immediately after definition
if (typeof window !== 'undefined') {
    window.loadPurchaseSubPage = loadPurchaseSubPage;
    window.switchPurchaseSubPage = switchPurchaseSubPage;
}

// Batch supplier invoice (add stock to inventory)
async function batchSupplierInvoice(invoiceId, buttonEl, confirmationsBody) {
    if (!confirmationsBody && !confirm('Are you sure you want to batch this invoice? This will add stock to inventory and cannot be undone.')) {
        return;
    }

    const btn = buttonEl || document.getElementById('batchInvoiceBtn');
    const originalHtml = btn ? btn.innerHTML : null;
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Batching...';
        }
        const result = await API.purchases.batchInvoice(invoiceId, confirmationsBody || null);
        showToast('Invoice batched successfully! Stock has been added to inventory.', 'success');
        if (typeof closeModal === 'function') closeModal();
        // Clear item search cache so next search shows updated costs (last unit cost from this batch)
        if (typeof window !== 'undefined' && window.searchCache && typeof window.searchCache.clear === 'function') {
            window.searchCache.clear();
        }
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
        const data = error.data || error.response?.data || {};
        const detail = data.detail;
        if (detail && typeof detail === 'object' && detail.code === 'PRICE_CONFIRMATION_REQUIRED') {
            const items = detail.items || [];
            if (items.length === 0) {
                showToast(detail.message || 'Price confirmation required', 'error');
            } else {
                showBatchPriceConfirmationModal(invoiceId, items, buttonEl);
            }
        } else if (detail && typeof detail === 'object' && detail.code === 'SHORT_EXPIRY_OVERRIDE_REQUIRED') {
            showShortExpiryOverrideModal(invoiceId, detail, buttonEl, confirmationsBody);
        } else if (detail && typeof detail === 'object' && detail.code === 'SHORT_EXPIRY_OVERRIDE_FORBIDDEN') {
            showToast(detail.message || 'You do not have permission to override short expiry. Ask a Manager or Pharmacist to batch this invoice.', 'error');
        } else {
            const msg = (detail && (typeof detail === 'string' ? detail : detail.message)) || error.message || 'Error batching invoice';
            showToast(msg, 'error');
        }
    } finally {
        if (btn && originalHtml) {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}

function showBatchPriceConfirmationModal(invoiceId, items, buttonEl) {
    const rows = items.map((it, idx) => {
        const floorNote = it.floor_price != null ? ` (Floor: ${it.floor_price})` : '';
        const marginNote = it.margin_below_standard ? ' — Margin below standard' : '';
        return `
            <div class="form-group" style="margin-bottom:0.75rem;">
                <label for="batchConfirm_${idx}">${escapeHtml(it.item_name || it.item_id)}${floorNote}${marginNote}</label>
                <input type="number" id="batchConfirm_${idx}" class="form-input" min="0" step="0.01" 
                    data-item-id="${escapeHtml(it.item_id)}" data-expected="${it.unit_cost_base}"
                    placeholder="Re-enter unit cost: ${it.unit_cost_base}">
            </div>`;
    }).join('');
    const content = `
        <div style="padding:0.5rem 0;">
            <p style="margin-bottom:1rem; color:var(--warning-text,#856404); font-weight:600;">
                <i class="fas fa-exclamation-triangle"></i> Some items have a floor price or margin below standard. 
                Please re-enter the unit cost for each item to confirm you are aware of the price.
            </p>
            ${rows}
        </div>`;
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" id="batchConfirmSubmitBtn"><i class="fas fa-check"></i> Confirm & Batch</button>`;
    if (typeof showModal === 'function') {
        showModal('Confirm Unit Costs', content, footer);
    }
    const submitBtn = document.getElementById('batchConfirmSubmitBtn');
    if (submitBtn) {
        submitBtn.onclick = async () => {
            const confirmations = [];
            for (let i = 0; i < items.length; i++) {
                const inp = document.getElementById('batchConfirm_' + i);
                if (!inp) continue;
                const val = parseFloat(inp.value);
                if (isNaN(val) || val < 0) {
                    showToast('Please enter a valid unit cost for ' + (items[i].item_name || items[i].item_id), 'warning');
                    inp.focus();
                    return;
                }
                confirmations.push({ item_id: items[i].item_id, unit_cost_base: val });
            }
            await batchSupplierInvoice(invoiceId, buttonEl, { confirmations });
        };
    }
}

function showShortExpiryOverrideModal(invoiceId, detail, buttonEl, existingConfirmationsBody) {
    const message = detail.message || 'Product expires sooner than the required minimum. Override required to accept.';
    const daysRemaining = detail.days_remaining;
    const minDays = detail.min_expiry_days;
    const subText = (daysRemaining != null && minDays != null)
        ? `This batch has ${daysRemaining} days until expiry (minimum ${minDays} days required).`
        : '';
    const content = `
        <div style="padding:0.5rem 0;">
            <p style="margin-bottom:0.75rem; color:var(--warning-text,#856404); font-weight:600;">
                <i class="fas fa-exclamation-triangle"></i> ${escapeHtml(message)}
            </p>
            ${subText ? `<p style="margin-bottom:0.75rem; color:var(--text-secondary);">${escapeHtml(subText)}</p>` : ''}
            <p style="margin-bottom:0.75rem;">Only users with <strong>Short Expiry Override</strong> permission (e.g. Manager or Pharmacist) can confirm. You will be verified when you click Override &amp; Batch.</p>
            <p style="margin-bottom:0;">Do you want to accept this batch anyway?</p>
        </div>`;
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" id="shortExpiryOverrideBatchBtn"><i class="fas fa-check"></i> Override & Batch</button>`;
    if (typeof showModal === 'function') {
        showModal('Short Expiry – Override Required', content, footer);
    }
    const submitBtn = document.getElementById('shortExpiryOverrideBatchBtn');
    if (submitBtn) {
        submitBtn.onclick = async () => {
            if (typeof closeModal === 'function') closeModal();
            const body = { short_expiry_override: true };
            if (existingConfirmationsBody && existingConfirmationsBody.confirmations) {
                body.confirmations = existingConfirmationsBody.confirmations;
            }
            await batchSupplierInvoice(invoiceId, buttonEl, body);
        };
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
    window.showShortExpiryOverrideModal = showShortExpiryOverrideModal;
    window.updateInvoicePayment = updateInvoicePayment;
    window.viewSupplierInvoice = viewSupplierInvoice;
    window.editSupplierInvoice = editSupplierInvoice;
    window.deleteSupplierInvoice = deleteSupplierInvoice;
    window.downloadSupplierInvoicePdf = downloadSupplierInvoicePdf;
    window.autoSaveInvoice = autoSaveInvoice;
    window.updatePurchaseSubNavActiveState = updatePurchaseSubNavActiveState;
    window.showCreateSupplierModal = showCreateSupplierModal;
    window.createSupplier = createSupplier;
    window.applyDateFilter = applyDateFilter;
    window.clearDateFilter = clearDateFilter;
    window.togglePurchaseOrdersCustomDates = togglePurchaseOrdersCustomDates;
    window.toggleSupplierInvoicesCustomDates = toggleSupplierInvoicesCustomDates;
    window.applyPurchaseFilters = applyPurchaseFilters;
    window.renderSuppliersPage = renderSuppliersPage;
    window.filterSuppliers = filterSuppliers;
    window.navigateToSupplierDetail = navigateToSupplierDetail;
    window.approveSupplierReturn = approveSupplierReturn;
    window.showNewPaymentModal = showNewPaymentModal;
    window.showNewPaymentModalWithSupplierSelect = showNewPaymentModalWithSupplierSelect;
    window.navigateToRecordPaymentPage = navigateToRecordPaymentPage;
    window.showInvoiceDetailsModal = showInvoiceDetailsModal;
    window.renderRecordPaymentPage = renderRecordPaymentPage;
    window.fetchSupplierDashboardData = fetchSupplierDashboardData;
    window.fetchSupplierPaymentsData = fetchSupplierPaymentsData;
    window.submitNewPayment = submitNewPayment;
    window.showAllocatePaymentModal = showAllocatePaymentModal;
    window.showNewReturnModal = showNewReturnModal;
    window.submitNewReturn = submitNewReturn;
    window.viewSupplierInvoice = viewSupplierInvoice;
    window.openCreateInvoiceWithSupplier = openCreateInvoiceWithSupplier;
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
    window.downloadPurchaseOrderPdf = downloadPurchaseOrderPdf;
    window.regeneratePurchaseOrderPdf = regeneratePurchaseOrderPdf;
    window.approvePurchaseOrder = approvePurchaseOrder;
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

// Supplier Dashboard — date range + metrics (default Today, auto-load on open)
let supplierDashboardDatePreset = 'today';
let supplierDashboardDateFrom = '';
let supplierDashboardDateTo = '';

function renderSupplierDashboardPage() {
    const page = document.getElementById('purchases');
    if (!page) return;
    const range = getSupplierInvoicesDateRange(supplierDashboardDatePreset);
    const defRange = getSupplierInvoicesDateRange('this_month');
    const from = supplierDashboardDateFrom || (range ? range.dateFrom : (defRange?.dateFrom || new Date().toISOString().slice(0, 10)));
    const to = supplierDashboardDateTo || (range ? range.dateTo : (defRange?.dateTo || new Date().toISOString().slice(0, 10)));
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-chart-pie"></i> Supplier Dashboard</h3>
                <div style="display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.5rem;">
                    <div class="form-group" style="margin: 0;"><label class="form-label" style="font-size: 0.75rem;">Date range</label>
                    <select id="supplierDashboardPreset" class="form-select" style="min-width: 140px;">
                        <option value="today" selected>Today</option>
                        <option value="yesterday">Yesterday</option>
                        <option value="this_week">This Week</option>
                        <option value="last_week">Last Week</option>
                        <option value="last_month">Last Month</option>
                        <option value="this_month">This Month</option>
                        <option value="this_year">This Year</option>
                        <option value="last_year">Last Year</option>
                        <option value="custom">Custom</option>
                    </select></div>
                    <div class="form-group" style="margin: 0; display: ${supplierDashboardDatePreset === 'custom' ? 'flex' : 'none'}; align-items: flex-end; gap: 0.5rem;" id="supplierDashboardCustomDates">
                        <div><label class="form-label" style="font-size: 0.75rem;">From</label><input type="date" id="supplierDashboardFrom" class="form-input" value="${from}" style="width: 130px;"></div>
                        <div><label class="form-label" style="font-size: 0.75rem;">To</label><input type="date" id="supplierDashboardTo" class="form-input" value="${to}" style="width: 130px;"></div>
                    </div>
                    <button type="button" class="btn btn-primary" id="supplierDashboardApply">Apply</button>
                </div>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div id="supplierDashboardContent"><div class="spinner"></div></div>
            </div>
        </div>
    `;
    document.getElementById('supplierDashboardPreset').addEventListener('change', function () {
        supplierDashboardDatePreset = this.value;
        const r = getSupplierInvoicesDateRange(supplierDashboardDatePreset);
        document.getElementById('supplierDashboardCustomDates').style.display = this.value === 'custom' ? 'block' : 'none';
        if (r && this.value !== 'custom') {
            document.getElementById('supplierDashboardFrom').value = r.dateFrom;
            document.getElementById('supplierDashboardTo').value = r.dateTo;
        }
    });
    document.getElementById('supplierDashboardApply').addEventListener('click', () => fetchSupplierDashboardData());
    // Auto-load with Today on open to avoid empty state
    fetchSupplierDashboardData();
}

async function fetchSupplierDashboardData() {
    const preset = document.getElementById('supplierDashboardPreset')?.value || 'this_month';
    supplierDashboardDatePreset = preset;
    let from, to;
    if (preset === 'custom') {
        from = document.getElementById('supplierDashboardFrom')?.value;
        to = document.getElementById('supplierDashboardTo')?.value;
    } else {
        const r = getSupplierInvoicesDateRange(preset);
        from = r?.dateFrom;
        to = r?.dateTo;
    }
    if (!from || !to) {
        showToast('Select valid date range', 'warning');
        return;
    }
    supplierDashboardDateFrom = from;
    supplierDashboardDateTo = to;
    const cont = document.getElementById('supplierDashboardContent');
    if (!cont) return;
    cont.innerHTML = '<div class="spinner"></div>';
    try {
        const params = { branch_id: CONFIG.BRANCH_ID };
        const [aging, payments, invoices] = await Promise.all([
            API.suppliers.getAging({ ...params, as_of_date: to }).catch(() => ({ suppliers: [] })),
            API.suppliers.listPayments({ ...params, date_from: from, date_to: to, limit: 500 }).catch(() => []),
            API.purchases.listInvoices({ company_id: CONFIG.COMPANY_ID, ...params, date_from: from, date_to: to }).catch(() => []),
        ]);
        const totalOutstanding = (aging.suppliers || []).reduce((s, r) => s + (parseFloat(r.total_outstanding) || 0), 0);
        const totalOverdue = (aging.suppliers || []).reduce((s, r) => s + (parseFloat(r.overdue_amount) || 0), 0);
        const purchasesInRange = (invoices || []).filter(inv => inv.status === 'BATCHED').reduce((s, inv) => s + (parseFloat(inv.total_inclusive) || 0), 0);
        const paymentsInRange = (payments || []).reduce((s, p) => s + (parseFloat(p.amount) || 0), 0);
        cont.innerHTML = `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
                <div class="card" style="padding: 1rem; border-left: 4px solid var(--primary-color);"><div style="font-size: 0.75rem; color: var(--text-secondary);">Total Outstanding</div><div style="font-size: 1.5rem; font-weight: 600;">${fmt(totalOutstanding)}</div></div>
                <div class="card" style="padding: 1rem; border-left: 4px solid var(--danger-color);"><div style="font-size: 0.75rem; color: var(--text-secondary);">Total Overdue</div><div style="font-size: 1.5rem; font-weight: 600; color: var(--danger-color);">${fmt(totalOverdue)}</div></div>
                <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Purchases (${from} to ${to})</div><div style="font-size: 1.5rem; font-weight: 600;">${fmt(purchasesInRange)}</div></div>
                <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Payments (${from} to ${to})</div><div style="font-size: 1.5rem; font-weight: 600;">${fmt(paymentsInRange)}</div></div>
                <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Suppliers with Balance</div><div style="font-size: 1.5rem; font-weight: 600;">${(aging.suppliers || []).length}</div></div>
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 1rem;">
                <a href="#" class="btn btn-primary" onclick="window.switchPurchaseSubPage && window.switchPurchaseSubPage('invoices'); return false;"><i class="fas fa-file-invoice-dollar"></i> Supplier Invoices</a>
                <a href="#" class="btn btn-outline" onclick="window.switchPurchaseSubPage && window.switchPurchaseSubPage('suppliers'); return false;"><i class="fas fa-truck"></i> Suppliers Management</a>
                <a href="#" class="btn btn-outline" onclick="window.switchPurchaseSubPage && window.switchPurchaseSubPage('supplier-payments'); return false;"><i class="fas fa-money-bill-wave"></i> Supplier Payments</a>
            </div>
        `;
    } catch (e) {
        console.error('Dashboard load error:', e);
        cont.innerHTML = `<p style="color: var(--danger-color);">Failed to load: ${e.message || 'Unknown error'}</p><button class="btn btn-outline" onclick="fetchSupplierDashboardData()">Retry</button>`;
    }
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

// Load suppliers from API (prefer enriched list with balances)
async function loadSuppliers() {
    try {
        if (!window.CONFIG || !window.CONFIG.COMPANY_ID) {
            console.warn('Company ID not configured');
            allSuppliers = [];
            return;
        }
        const params = {};
        if (window.CONFIG.BRANCH_ID) params.branch_id = window.CONFIG.BRANCH_ID;
        try {
            if (window.API?.suppliers?.listEnriched) {
                allSuppliers = await window.API.suppliers.listEnriched(params);
            } else {
                throw new Error('listEnriched not available');
            }
        } catch (enrichErr) {
            console.warn('listEnriched failed, falling back to list:', enrichErr?.message);
            try {
                const raw = await window.API.suppliers.list(window.CONFIG.COMPANY_ID);
                const list = Array.isArray(raw) ? raw : (raw?.suppliers || raw || []);
                allSuppliers = (list || []).map(s => ({
                    ...(typeof s === 'object' ? s : { id: s?.id, name: s?.name }),
                    id: s?.id,
                    name: s?.name || s?.company_name,
                    outstanding_balance: 0,
                    overdue_amount: 0,
                    this_month_purchases: 0
                }));
            } catch (listErr) {
                console.error('list also failed:', listErr);
                allSuppliers = [];
            }
        }
        if (!Array.isArray(allSuppliers)) allSuppliers = [];
        console.log('✅ Loaded suppliers:', allSuppliers.length);
    } catch (error) {
        console.error('❌ Error loading suppliers:', error);
        allSuppliers = [];
    }
}

// Format KES for display
function fmt(num) {
    if (num == null || isNaN(num)) return '—';
    return typeof formatCurrency === 'function' ? formatCurrency(num) : 'KES ' + Number(num).toLocaleString('en-KE', { minimumFractionDigits: 2 });
}

// Supplier row badge/indicator color
function supplierBalanceBadge(outstanding, overdue) {
    const ob = parseFloat(outstanding) || 0;
    const ov = parseFloat(overdue) || 0;
    if (ob > 0 && ov > 0) return { cls: 'badge-danger', icon: 'fa-exclamation-circle', text: 'Overdue' };
    if (ob > 0) return { cls: 'badge-warning', icon: 'fa-clock', text: 'Outstanding' };
    if (ob < 0) return { cls: 'badge-info', icon: 'fa-arrow-down', text: 'Credit Balance' };
    return { cls: 'badge-success', icon: 'fa-check', text: 'Paid Up' };
}

// Render suppliers table (enhanced with balance columns, click to open detail)
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
                <i class="fas fa-search" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                <p style="color: var(--text-secondary);">No suppliers match your search</p>
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
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Outstanding</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Overdue</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">This Month</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Credit Terms</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${filtered.map(supplier => {
                        const ob = supplier.outstanding_balance ?? supplier.outstanding ?? 0;
                        const ov = supplier.overdue_amount ?? supplier.overdue ?? 0;
                        const tm = supplier.this_month_purchases ?? supplier.this_month ?? 0;
                        const ct = supplier.credit_terms ?? supplier.default_payment_terms_days;
                        const badge = supplierBalanceBadge(ob, ov);
                        const rowClick = `onclick="navigateToSupplierDetail('${supplier.id}')" style="cursor: pointer;"`;
                        return `
                        <tr ${rowClick} title="Click to view supplier details">
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                <strong>${escapeHtml(supplier.name)}</strong>
                                ${badge.text === 'Overdue' ? '<span class="badge badge-danger" style="margin-left: 0.5rem; font-size: 0.7rem;">Overdue</span>' : ''}
                                ${badge.text === 'Credit Balance' ? '<span class="badge badge-info" style="margin-left: 0.5rem; font-size: 0.7rem;">Credit</span>' : ''}
                            </td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${fmt(ob)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${fmt(ov)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${fmt(tm)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${ct ? ct + ' days' : '—'}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                <span class="badge ${supplier.is_active !== false ? 'badge-success' : 'badge-danger'}">
                                    ${supplier.is_active !== false ? 'Active' : 'Inactive'}
                                </span>
                            </td>
                        </tr>
                    `}).join('')}
                </tbody>
            </table>
        </div>
    `;
}

// Navigate to supplier detail (hash triggers loadPage -> supplier detail)
function navigateToSupplierDetail(supplierId) {
    window.currentSupplierDetailId = supplierId;
    window.location.hash = '#purchases-suppliers-' + supplierId;
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

// =====================================================
// SUPPLIER DETAIL PAGE
// =====================================================
let currentSupplierDetail = null;
let currentSupplierTab = 'profile';

async function renderSupplierDetailPage(supplierId) {
    const page = document.getElementById('purchases');
    if (!page || !supplierId) {
        if (window.switchPurchaseSubPage) window.switchPurchaseSubPage('suppliers');
        return;
    }
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; border-bottom: 1px solid var(--border-color); flex-wrap: wrap; gap: 0.5rem;">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <button class="btn btn-outline" onclick="window.currentSupplierDetailId=null; window.switchPurchaseSubPage('suppliers')" title="Back to suppliers">
                        <i class="fas fa-arrow-left"></i>
                    </button>
                    <h3 class="card-title" style="margin: 0; font-size: 1.25rem;" id="supplierDetailTitle">Loading...</h3>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-primary" onclick="showNewPaymentModal('${supplierId}')"><i class="fas fa-money-bill-wave"></i> New Payment</button>
                    <button class="btn btn-outline" onclick="showNewReturnModal('${supplierId}')"><i class="fas fa-undo"></i> New Return</button>
                    <button class="btn btn-outline" onclick="openCreateInvoiceWithSupplier('${supplierId}')"><i class="fas fa-file-invoice"></i> Record Invoice</button>
                </div>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div id="supplierSummaryCards" class="summary-cards" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;"></div>
                <div class="tabs" style="border-bottom: 1px solid var(--border-color); margin-bottom: 1rem;">
                    <button class="tab-btn active" data-tab="overview">Overview</button>
                    <button class="tab-btn" data-tab="profile">Profile</button>
                    <button class="tab-btn" data-tab="invoices">Invoices</button>
                    <button class="tab-btn" data-tab="payments">Payments</button>
                    <button class="tab-btn" data-tab="returns">Returns</button>
                    <button class="tab-btn" data-tab="ledger">Ledger</button>
                    <button class="tab-btn" data-tab="statement">Statement</button>
                    <button class="tab-btn" data-tab="aging">Aging</button>
                    <button class="tab-btn" data-tab="metrics">Metrics</button>
                </div>
                <div id="supplierTabContent"></div>
            </div>
        </div>
    `;
    currentSupplierTab = 'overview';
    page.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentSupplierTab = btn.dataset.tab;
            page.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderSupplierTabContent(supplierId, currentSupplierTab);
        });
    });
    try {
        const params = {};
        if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
        const [supplier, enrichedList] = await Promise.all([
            API.suppliers.get(supplierId),
            API.suppliers.listEnriched ? API.suppliers.listEnriched(params).catch(() => []) : [],
        ]);
        currentSupplierDetail = supplier;
        document.getElementById('supplierDetailTitle').textContent = supplier.name || 'Supplier';
        const list = Array.isArray(enrichedList) ? enrichedList : [];
        const enrichedRow = list.find(s => String(s.id) === String(supplierId));
        const ob = enrichedRow != null ? (parseFloat(enrichedRow.outstanding_balance) ?? parseFloat(enrichedRow.outstanding) ?? 0) : 0;
        const ov = enrichedRow != null ? (parseFloat(enrichedRow.overdue_amount) ?? parseFloat(enrichedRow.overdue) ?? 0) : 0;
        const thisMonth = enrichedRow != null ? (parseFloat(enrichedRow.this_month_purchases) ?? parseFloat(enrichedRow.this_month) ?? 0) : 0;
        const paymentsThisMonth = 0;
        renderSupplierSummaryCards({ outstanding: ob, overdue: ov, thisMonthPurchases: thisMonth, thisMonthPayments: paymentsThisMonth, creditLimit: supplier.credit_limit });
        renderSupplierTabContent(supplierId, currentSupplierTab);
    } catch (e) {
        console.error('Supplier detail load error:', e);
        document.getElementById('supplierDetailTitle').textContent = 'Error loading supplier';
        document.getElementById('supplierSummaryCards').innerHTML = '<p style="color: var(--danger-color);">Failed to load supplier data.</p>';
    }
}

async function refreshSupplierDetailAfterAction(supplierId) {
    if (!supplierId || !window.currentSupplierDetailId || String(window.currentSupplierDetailId) !== String(supplierId)) return;
    const cont = document.getElementById('supplierSummaryCards');
    if (!cont) return;
    try {
        const params = {};
        if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
        const [supplier, enrichedList] = await Promise.all([
            API.suppliers.get(supplierId),
            API.suppliers.listEnriched ? API.suppliers.listEnriched(params).catch(() => []) : [],
        ]);
        currentSupplierDetail = supplier;
        const list = Array.isArray(enrichedList) ? enrichedList : [];
        const enrichedRow = list.find(s => String(s.id) === String(supplierId));
        const ob = enrichedRow != null ? (parseFloat(enrichedRow.outstanding_balance) ?? parseFloat(enrichedRow.outstanding) ?? 0) : 0;
        const ov = enrichedRow != null ? (parseFloat(enrichedRow.overdue_amount) ?? parseFloat(enrichedRow.overdue) ?? 0) : 0;
        const thisMonth = enrichedRow != null ? (parseFloat(enrichedRow.this_month_purchases) ?? parseFloat(enrichedRow.this_month) ?? 0) : 0;
        const paymentsThisMonth = 0;
        renderSupplierSummaryCards({ outstanding: ob, overdue: ov, thisMonthPurchases: thisMonth, thisMonthPayments: paymentsThisMonth, creditLimit: supplier.credit_limit });
        await renderSupplierTabContent(supplierId, currentSupplierTab);
    } catch (_) {}
}

function renderSupplierSummaryCards(data) {
    const cont = document.getElementById('supplierSummaryCards');
    if (!cont) return;
    const { outstanding, overdue, thisMonthPurchases, thisMonthPayments, creditLimit } = data || {};
    const cards = [
        { label: 'Outstanding Balance', value: outstanding, formatter: 'currency', cls: outstanding > 0 ? (overdue > 0 ? 'border-danger' : 'border-warning') : (outstanding < 0 ? 'border-info' : 'border-success') },
        { label: 'Overdue Amount', value: overdue, formatter: 'currency', cls: overdue > 0 ? 'border-danger' : '' },
        { label: 'This Month Purchases', value: thisMonthPurchases, formatter: 'currency' },
        { label: 'This Month Payments', value: thisMonthPayments, formatter: 'currency' },
    ];
    if (creditLimit != null && creditLimit > 0) {
        cards.push({ label: 'Credit Limit', value: creditLimit, formatter: 'currency' });
    }
    if (outstanding < 0) {
        cards.push({ label: 'Credit Balance', value: Math.abs(outstanding), formatter: 'currency', cls: 'border-info' });
    }
    cont.innerHTML = cards.map(c => `
        <div class="card" style="padding: 1rem; border-left: 4px solid var(--primary-color); ${c.cls ? 'border-left-color: var(--' + c.cls.replace('border-','') + '-color, #6c757d);' : ''}">
            <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.25rem;">${c.label}</div>
            <div style="font-size: 1.25rem; font-weight: 600;">${c.formatter === 'currency' ? fmt(c.value) : (c.value ?? '—')}</div>
        </div>
    `).join('');
}

async function renderSupplierTabContent(supplierId, tab) {
    const cont = document.getElementById('supplierTabContent');
    if (!cont) return;
    cont.innerHTML = '<div class="spinner"></div>';
    try {
        if (tab === 'overview') {
            await renderSupplierOverviewTab(supplierId, cont);
        } else if (tab === 'profile') {
            await renderSupplierProfileTab(supplierId, cont);
        } else if (tab === 'invoices') {
            await renderSupplierInvoicesTab(supplierId, cont);
        } else if (tab === 'payments') {
            await renderSupplierPaymentsTab(supplierId, cont);
        } else if (tab === 'returns') {
            await renderSupplierReturnsTab(supplierId, cont);
        } else if (tab === 'ledger') {
            await renderSupplierLedgerTab(supplierId, cont);
        } else if (tab === 'statement') {
            await renderSupplierStatementTab(supplierId, cont);
        } else if (tab === 'aging') {
            await renderSupplierAgingTab(supplierId, cont);
        } else if (tab === 'metrics') {
            await renderSupplierMetricsTab(supplierId, cont);
        }
    } catch (e) {
        console.error('Tab load error:', e);
        cont.innerHTML = '<p style="color: var(--danger-color);">Failed to load tab data.</p>';
    }
}

async function renderSupplierOverviewTab(supplierId, cont) {
    const now = new Date();
    const month = now.toISOString().slice(0, 7);
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
    const monthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10);
    const params = {};
    if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
    let metrics = {};
    let enrichedRow = null;
    let lastPayment = null;
    let paymentsList = [];
    let returnsList = [];
    try {
        const [enrichedList, m, payments, returns, lastPay] = await Promise.all([
            API.suppliers.listEnriched ? API.suppliers.listEnriched(params).catch(() => []) : [],
            API.suppliers.getMetrics(month, { branch_id: CONFIG.BRANCH_ID }).catch(() => ({})),
            API.suppliers.listPayments({ supplier_id: supplierId, branch_id: CONFIG.BRANCH_ID, date_from: monthStart, date_to: monthEnd, limit: 500 }).catch(() => []),
            API.suppliers.listReturns({ supplier_id: supplierId, branch_id: CONFIG.BRANCH_ID, limit: 500 }).catch(() => []),
            API.suppliers.listPayments({ supplier_id: supplierId, branch_id: CONFIG.BRANCH_ID, limit: 1 }).catch(() => []),
        ]);
        metrics = m || {};
        const list = Array.isArray(enrichedList) ? enrichedList : [];
        enrichedRow = list.find(s => String(s.id) === String(supplierId));
        paymentsList = payments || [];
        returnsList = returns || [];
        lastPayment = (lastPay && lastPay[0]) ? lastPay[0] : null;
    } catch (_) {}
    const topSupplier = (metrics.top_suppliers_by_purchase || []).find(s => String(s.supplier_id) === String(supplierId));
    const outstanding = enrichedRow != null ? (parseFloat(enrichedRow.outstanding_balance) ?? parseFloat(enrichedRow.outstanding) ?? 0) : 0;
    const overdue = enrichedRow != null ? (parseFloat(enrichedRow.overdue_amount) ?? parseFloat(enrichedRow.overdue) ?? 0) : 0;
    const thisMonthPurchases = enrichedRow != null ? (parseFloat(enrichedRow.this_month_purchases) ?? parseFloat(enrichedRow.this_month) ?? 0) : (topSupplier ? parseFloat(topSupplier.total) || 0 : 0);
    const thisMonthPayments = (paymentsList || []).reduce((sum, p) => sum + (parseFloat(p.amount) || 0), 0);
    const thisMonthReturns = (returnsList || []).filter(r => {
        if (r.status !== 'credited') return false;
        const d = r.return_date ? new Date(r.return_date) : null;
        return d && d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
    }).reduce((sum, r) => sum + (parseFloat(r.total_value) || 0), 0);
    const lastPaymentDate = lastPayment && lastPayment.payment_date ? new Date(lastPayment.payment_date).toLocaleDateString('en-KE') : '—';
    const avgPaymentDays = metrics.average_payment_days != null ? Number(metrics.average_payment_days).toFixed(1) : '—';
    cont.innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Outstanding</div><div style="font-size: 1.25rem; font-weight: 600;">${fmt(outstanding)}</div></div>
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Overdue</div><div style="font-size: 1.25rem; font-weight: 600; color: var(--danger-color);">${fmt(overdue)}</div></div>
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">This Month Purchases</div><div style="font-size: 1.25rem; font-weight: 600;">${fmt(thisMonthPurchases)}</div></div>
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">This Month Payments</div><div style="font-size: 1.25rem; font-weight: 600;">${fmt(thisMonthPayments)}</div></div>
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">This Month Returns</div><div style="font-size: 1.25rem; font-weight: 600;">${fmt(thisMonthReturns)}</div></div>
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Last Payment Date</div><div style="font-size: 1.1rem; font-weight: 600;">${lastPaymentDate}</div></div>
            <div class="card" style="padding: 1rem;"><div style="font-size: 0.75rem; color: var(--text-secondary);">Avg Payment Days</div><div style="font-size: 1.1rem; font-weight: 600;">${avgPaymentDays}</div></div>
        </div>
    `;
}

async function renderSupplierProfileTab(supplierId, cont) {
    const s = currentSupplierDetail || await API.suppliers.get(supplierId);
    currentSupplierDetail = s;
    cont.innerHTML = `
        <form id="supplierProfileForm" style="max-width: 600px;">
            <div class="form-row">
                <div class="form-group"><label class="form-label">Name</label><input type="text" class="form-input" name="name" value="${escapeHtml(s.name || '')}" required></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label class="form-label">Contact Person</label><input type="text" class="form-input" name="contact_person" value="${escapeHtml(s.contact_person || '')}"></div>
                <div class="form-group"><label class="form-label">Phone</label><input type="text" class="form-input" name="phone" value="${escapeHtml(s.phone || '')}"></div>
            </div>
            <div class="form-group"><label class="form-label">Email</label><input type="email" class="form-input" name="email" value="${escapeHtml(s.email || '')}"></div>
            <div class="form-group"><label class="form-label">Address</label><textarea class="form-textarea" name="address" rows="2">${escapeHtml(s.address || '')}</textarea></div>
            <div class="form-row">
                <div class="form-group"><label class="form-label">Credit Terms (days)</label><input type="number" class="form-input" name="credit_terms" value="${s.credit_terms ?? s.default_payment_terms_days ?? ''}" min="0" placeholder="e.g. 30"></div>
                <div class="form-group"><label class="form-label">Credit Limit (KES)</label><input type="number" class="form-input" name="credit_limit" value="${s.credit_limit ?? ''}" min="0" step="0.01" placeholder="Optional"></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label class="form-label">Opening Balance</label><input type="number" class="form-input" name="opening_balance" value="${s.opening_balance ?? 0}" step="0.01"></div>
                <div class="form-group" style="display: flex; align-items: flex-end;">
                    <label style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer;">
                        <input type="checkbox" name="allow_over_credit" ${(s.allow_over_credit || false) ? 'checked' : ''}> Allow over credit
                    </label>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group" style="display: flex; align-items: flex-end;">
                    <label style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer;">
                        <input type="checkbox" name="requires_supplier_invoice_number" ${(s.requires_supplier_invoice_number || false) ? 'checked' : ''}>
                        Require supplier invoice number on invoices
                    </label>
                </div>
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Changes</button>
        </form>
    `;
    cont.querySelector('form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            await API.suppliers.update(supplierId, {
                name: fd.get('name'),
                contact_person: fd.get('contact_person') || null,
                phone: fd.get('phone') || null,
                email: fd.get('email') || null,
                address: fd.get('address') || null,
                credit_terms: fd.get('credit_terms') ? parseInt(fd.get('credit_terms'), 10) : null,
                credit_limit: fd.get('credit_limit') ? parseFloat(fd.get('credit_limit')) : null,
                opening_balance: fd.get('opening_balance') != null ? parseFloat(fd.get('opening_balance')) : null,
                allow_over_credit: fd.get('allow_over_credit') === 'on',
                requires_supplier_invoice_number: fd.get('requires_supplier_invoice_number') === 'on',
            });
            showToast('Supplier updated', 'success');
            currentSupplierDetail = await API.suppliers.get(supplierId);
        } catch (err) {
            showToast(err.message || 'Failed to update', 'error');
        }
    });
}

async function renderSupplierInvoicesTab(supplierId, cont) {
    const params = { company_id: CONFIG.COMPANY_ID, supplier_id: supplierId };
    if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
    const invoices = await API.purchases.listInvoices(params);
    if (!invoices || invoices.length === 0) {
        cont.innerHTML = '<div class="text-center" style="padding: 2rem;"><i class="fas fa-file-invoice" style="font-size: 2rem; color: var(--text-secondary);"></i><p>No invoices</p><a href="#" class="btn btn-primary" onclick="window.openCreateInvoiceWithSupplier(\'' + supplierId + '\'); return false;">Record New Invoice</a></div>';
        return;
    }
    cont.innerHTML = `
        <div style="margin-bottom: 1rem;"><a href="#" class="btn btn-primary" onclick="window.openCreateInvoiceWithSupplier('${supplierId}'); return false;"><i class="fas fa-plus"></i> Record New Invoice</a></div>
        <div class="table-container" style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead><tr><th>Date</th><th>Invoice No</th><th>Due Date</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>${invoices.map(inv => {
                    const status = inv.status === 'DRAFT' ? 'Draft' : inv.payment_status === 'PAID' ? 'Paid' : inv.payment_status === 'PARTIAL' ? 'Partially Paid' : (inv.due_date && new Date(inv.due_date) < new Date() && (parseFloat(inv.balance) || 0) > 0 ? 'Overdue' : 'Posted');
                    const statusCls = status === 'Draft' ? 'badge-secondary' : status === 'Overdue' ? 'badge-danger' : status === 'Paid' ? 'badge-success' : status === 'Partially Paid' ? 'badge-warning' : 'badge-info';
                    return `<tr>
                        <td>${inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('en-KE') : '—'}</td>
                        <td>${escapeHtml(inv.invoice_number || '—')}</td>
                        <td>${inv.due_date ? new Date(inv.due_date).toLocaleDateString('en-KE') : '—'}</td>
                        <td>${fmt(inv.total_inclusive)}</td>
                        <td>${fmt(inv.amount_paid)}</td>
                        <td>${fmt(inv.balance)}</td>
                        <td><span class="badge ${statusCls}">${status}</span></td>
                        <td><button class="btn btn-outline btn-sm" onclick="viewSupplierInvoice('${inv.id}')">View</button> ${(parseFloat(inv.balance) || 0) > 0 ? `<button class="btn btn-primary btn-sm" onclick="showAllocatePaymentModal('${inv.id}','${supplierId}')">Allocate Payment</button>` : ''} <button class="btn btn-outline btn-sm" onclick="showNewReturnModal('${supplierId}', '${inv.id}')" title="New return linked to this invoice">Return</button></td>
                    </tr>`;
                }).join('')}</tbody>
            </table>
        </div>
    `;
}

async function renderSupplierPaymentsTab(supplierId, cont) {
    const params = { supplier_id: supplierId };
    if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
    let payments = [];
    try { payments = await API.suppliers.listPayments(params); } catch (_) {}
    cont.innerHTML = `
        <div style="margin-bottom: 1rem; display: flex; justify-content: flex-end;"><button class="btn btn-primary" onclick="showNewPaymentModal('${supplierId}')"><i class="fas fa-plus"></i> New Payment</button></div>
        <div class="table-container" style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead><tr><th>Date</th><th>Method</th><th>Reference</th><th>Amount</th><th>Allocated</th><th>Actions</th></tr></thead>
                <tbody>${(payments && payments.length) ? payments.map(p => `
                    <tr>
                        <td>${p.payment_date ? new Date(p.payment_date).toLocaleDateString('en-KE') : '—'}</td>
                        <td>${escapeHtml(p.method || '—')}</td>
                        <td>${escapeHtml(p.reference || '—')}</td>
                        <td>${fmt(p.amount)}</td>
                        <td>${p.is_allocated ? 'Yes' : 'No'}</td>
                        <td>—</td>
                    </tr>
                `).join('') : '<tr><td colspan="6" style="text-align: center; padding: 2rem;">No payments recorded</td></tr>'}</tbody>
            </table>
        </div>
    `;
}

async function renderSupplierReturnsTab(supplierId, cont) {
    const params = { supplier_id: supplierId };
    if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
    let returns = [];
    try { returns = await API.suppliers.listReturns(params); } catch (_) {}
    cont.innerHTML = `
        <div style="margin-bottom: 1rem;"><button class="btn btn-primary" onclick="showNewReturnModal('${supplierId}')"><i class="fas fa-plus"></i> New Return</button></div>
        <div class="table-container" style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead><tr><th>Date</th><th>Linked Invoice</th><th>Total</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>${(returns && returns.length) ? returns.map(r => {
                    const statusCls = r.status === 'credited' ? 'badge-success' : r.status === 'pending' ? 'badge-warning' : r.status === 'rejected' ? 'badge-danger' : 'badge-info';
                    return `<tr>
                        <td>${r.return_date ? new Date(r.return_date).toLocaleDateString('en-KE') : '—'}</td>
                        <td>${r.linked_invoice_id ? 'Yes' : '—'}</td>
                        <td>${fmt(r.total_value)}</td>
                        <td><span class="badge ${statusCls}">${r.status || '—'}</span></td>
                        <td>${r.status === 'pending' ? `<button class="btn btn-primary btn-sm" onclick="approveSupplierReturn('${r.id}')">Approve</button>` : '—'}</td>
                    </tr>`;
                }).join('') : '<tr><td colspan="5" style="text-align: center; padding: 2rem;">No returns</td></tr>'}</tbody>
            </table>
        </div>
    `;
}

async function approveSupplierReturn(returnId) {
    if (!confirm('Approve this return? Stock will be reduced and supplier balance credited.')) return;
    const supplierId = window.currentSupplierDetailId;
    try {
        await API.suppliers.approveReturn(returnId);
        showToast('Return approved', 'success');
        if (supplierId) refreshSupplierDetailAfterAction(supplierId);
        else if (document.getElementById('supplierTabContent')) renderSupplierTabContent(supplierId, 'returns');
    } catch (e) {
        showToast(e.message || 'Failed to approve', 'error');
    }
}

const supplierLedgerDateFrom = {};
const supplierLedgerDateTo = {};
const SUPPLIER_LEDGER_PAGE_SIZE = 100;

async function renderSupplierLedgerTab(supplierId, cont) {
    const now = new Date();
    const defaultFrom = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
    const defaultTo = now.toISOString().slice(0, 10);
    const from = supplierLedgerDateFrom[supplierId] || defaultFrom;
    const to = supplierLedgerDateTo[supplierId] || defaultTo;
    const params = { supplier_id: supplierId, date_from: from, date_to: to, limit: SUPPLIER_LEDGER_PAGE_SIZE, offset: 0 };
    if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
    let entries = [];
    try { entries = await API.suppliers.listLedger(params); } catch (_) {}
    let bal = 0;
    cont.innerHTML = `
        <div style="display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; align-items: flex-end;">
            <div class="form-group" style="margin: 0;"><label class="form-label">From</label><input type="date" id="ledgerDateFrom" class="form-input" value="${from}"></div>
            <div class="form-group" style="margin: 0;"><label class="form-label">To</label><input type="date" id="ledgerDateTo" class="form-input" value="${to}"></div>
            <button type="button" class="btn btn-primary" id="ledgerApplyFilter">Apply</button>
        </div>
        <div class="table-container" style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead><tr><th>Date</th><th>Type</th><th>Reference</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead>
                <tbody>${(entries && entries.length) ? entries.map(e => {
                    const runBal = e.running_balance != null ? parseFloat(e.running_balance) : (bal += (parseFloat(e.debit) || 0) - (parseFloat(e.credit) || 0));
                    if (e.running_balance != null) bal = runBal;
                    return `<tr>
                        <td>${e.date ? new Date(e.date).toLocaleDateString('en-KE') : '—'}</td>
                        <td>${escapeHtml(e.entry_type || '—')}</td>
                        <td>${e.reference_id ? String(e.reference_id).slice(0, 8) : '—'}</td>
                        <td style="color: ${(parseFloat(e.debit) || 0) > 0 ? 'var(--danger-color)' : ''}">${fmt(e.debit)}</td>
                        <td style="color: ${(parseFloat(e.credit) || 0) > 0 ? 'var(--success-color)' : ''}">${fmt(e.credit)}</td>
                        <td>${fmt(runBal)}</td>
                    </tr>`;
                }).join('') : '<tr><td colspan="6" style="text-align: center; padding: 2rem;">No ledger entries for this range</td></tr>'}</tbody>
            </table>
        </div>
    `;
    document.getElementById('ledgerApplyFilter').addEventListener('click', () => {
        supplierLedgerDateFrom[supplierId] = document.getElementById('ledgerDateFrom').value;
        supplierLedgerDateTo[supplierId] = document.getElementById('ledgerDateTo').value;
        renderSupplierTabContent(supplierId, 'ledger');
    });
}

const supplierStatementDateFrom = {};
const supplierStatementDateTo = {};

async function renderSupplierStatementTab(supplierId, cont) {
    const today = new Date();
    const defaultFrom = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
    const defaultTo = today.toISOString().slice(0, 10);
    const fromDate = supplierStatementDateFrom[supplierId] || defaultFrom;
    const toDate = supplierStatementDateTo[supplierId] || defaultTo;
    cont.innerHTML = '<div class="spinner"></div>';
    let agingRow = null;
    try {
        const [st, aging] = await Promise.all([
            API.suppliers.getStatement({ supplier_id: supplierId, branch_id: CONFIG.BRANCH_ID, from_date: fromDate, to_date: toDate }),
            API.suppliers.getAging({ branch_id: CONFIG.BRANCH_ID }),
        ]);
        agingRow = (aging.suppliers || []).find(s => String(s.supplier_id) === String(supplierId));
        const systemOutstanding = agingRow ? parseFloat(agingRow.total_outstanding) || 0 : 0;
        const closingBalance = parseFloat(st.closing_balance) || 0;
        const matchNote = Math.abs(systemOutstanding - closingBalance) < 0.01
            ? '<p style="font-size: 0.875rem; color: var(--success-color); margin-top: 0.5rem;">Statement matches system outstanding.</p>'
            : '<p style="font-size: 0.875rem; color: var(--warning-color); margin-top: 0.5rem;">If this differs from the supplier\'s statement, investigate via the Ledger tab.</p>';
        cont.innerHTML = `
            <div style="display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; align-items: flex-end;">
                <div class="form-group" style="margin: 0;"><label class="form-label">From</label><input type="date" id="statementDateFrom" class="form-input" value="${fromDate}"></div>
                <div class="form-group" style="margin: 0;"><label class="form-label">To</label><input type="date" id="statementDateTo" class="form-input" value="${toDate}"></div>
                <button type="button" class="btn btn-primary" id="statementApplyFilter">Apply</button>
            </div>
            <div id="supplierStatementPrint" style="background: white; padding: 1.5rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 1.5rem;">
                    <div><h4>${escapeHtml(st.supplier_name)}</h4><p>Period: ${st.from_date} to ${st.to_date}</p><p>Opening: ${fmt(st.opening_balance)}</p></div>
                    <button class="btn btn-primary" onclick="window.print();"><i class="fas fa-print"></i> Print</button>
                </div>
                <table style="width: 100%; border-collapse: collapse;">
                    <thead><tr><th>Date</th><th>Description</th><th>Reference</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead>
                    <tbody>${(st.lines || []).map(l => `
                        <tr>
                            <td>${l.date ? new Date(l.date).toLocaleDateString('en-KE') : '—'}</td>
                            <td>${escapeHtml(l.description || '')}</td>
                            <td>${escapeHtml(l.reference || '')}</td>
                            <td>${fmt(l.debit)}</td>
                            <td>${fmt(l.credit)}</td>
                            <td>${fmt(l.balance)}</td>
                        </tr>
                    `).join('')}</tbody>
                </table>
                <div style="margin-top: 1rem;">
                    <div style="font-weight: 600;">Statement Closing Balance: ${fmt(closingBalance)}</div>
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">System Outstanding: ${fmt(systemOutstanding)}</div>
                    ${matchNote}
                </div>
            </div>
        `;
        document.getElementById('statementApplyFilter').addEventListener('click', () => {
            supplierStatementDateFrom[supplierId] = document.getElementById('statementDateFrom').value;
            supplierStatementDateTo[supplierId] = document.getElementById('statementDateTo').value;
            renderSupplierTabContent(supplierId, 'statement');
        });
    } catch (_) {
        cont.innerHTML = '<p>Failed to load statement.</p>';
    }
}

async function renderSupplierAgingTab(supplierId, cont) {
    const aging = await API.suppliers.getAging({ branch_id: CONFIG.BRANCH_ID });
    const row = (aging.suppliers || []).find(s => String(s.supplier_id) === String(supplierId));
    if (!row) {
        cont.innerHTML = '<p>No aging data for this supplier (no outstanding invoices).</p>';
        return;
    }
    cont.innerHTML = `
        <table style="width: 100%; max-width: 400px; border-collapse: collapse;">
            <tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">Current (0–30 days)</td><td style="text-align: right; padding: 0.5rem;">${fmt(row.bucket_0_30)}</td></tr>
            <tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">31–60 days</td><td style="text-align: right; padding: 0.5rem;">${fmt(row.bucket_31_60)}</td></tr>
            <tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">61–90 days</td><td style="text-align: right; padding: 0.5rem;">${fmt(row.bucket_61_90)}</td></tr>
            <tr><td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">90+ days</td><td style="text-align: right; padding: 0.5rem;">${fmt(row.bucket_90_plus)}</td></tr>
            <tr style="font-weight: 600;"><td style="padding: 0.5rem;">Total Outstanding</td><td style="text-align: right; padding: 0.5rem;">${fmt(row.total_outstanding)}</td></tr>
        </table>
    `;
}

async function renderSupplierMetricsTab(supplierId, cont) {
    const month = new Date().toISOString().slice(0, 7);
    const params = {};
    if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
    let metrics = {};
    let enrichedRow = null;
    try {
        const [m, enrichedList] = await Promise.all([
            API.suppliers.getMetrics(month, { branch_id: CONFIG.BRANCH_ID }),
            API.suppliers.listEnriched ? API.suppliers.listEnriched(params).catch(() => []) : [],
        ]);
        metrics = m || {};
        const list = Array.isArray(enrichedList) ? enrichedList : [];
        enrichedRow = list.find(s => String(s.id) === String(supplierId));
    } catch (_) {}
    const topSupplier = (metrics.top_suppliers_by_purchase || []).find(s => String(s.supplier_id) === String(supplierId));
    const supplierTotal = topSupplier ? parseFloat(topSupplier.total) || 0 : 0;
    const ob = enrichedRow != null ? (parseFloat(enrichedRow.outstanding_balance) ?? parseFloat(enrichedRow.outstanding) ?? 0) : 0;
    const ov = enrichedRow != null ? (parseFloat(enrichedRow.overdue_amount) ?? parseFloat(enrichedRow.overdue) ?? 0) : 0;
    cont.innerHTML = `
        <div class="card" style="padding: 1rem; margin-bottom: 1rem;">
            <h4 style="margin: 0 0 1rem 0;">Company metrics (${month})</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem;">
                <div><span style="font-size: 0.75rem; color: var(--text-secondary);">Total Purchases</span><div style="font-weight: 600;">${fmt(metrics.total_purchases)}</div></div>
                <div><span style="font-size: 0.75rem; color: var(--text-secondary);">Total Payments</span><div style="font-weight: 600;">${fmt(metrics.total_payments)}</div></div>
                <div><span style="font-size: 0.75rem; color: var(--text-secondary);">Total Returns</span><div style="font-weight: 600;">${fmt(metrics.total_returns)}</div></div>
                <div><span style="font-size: 0.75rem; color: var(--text-secondary);">Net Outstanding</span><div style="font-weight: 600;">${fmt(metrics.net_outstanding)}</div></div>
                <div><span style="font-size: 0.75rem; color: var(--text-secondary);">Overdue</span><div style="font-weight: 600; color: var(--danger-color);">${fmt(metrics.overdue_amount)}</div></div>
                <div><span style="font-size: 0.75rem; color: var(--text-secondary);">Avg Payment Days</span><div style="font-weight: 600;">${metrics.average_payment_days != null ? Number(metrics.average_payment_days).toFixed(1) : '—'}</div></div>
            </div>
        </div>
        <div class="card" style="padding: 1rem;">
            <h4 style="margin: 0 0 1rem 0;">This supplier (${month})</h4>
            <p><strong>This month purchases:</strong> ${fmt(supplierTotal)}</p>
            <p><strong>Outstanding:</strong> ${fmt(ob)}</p>
            <p><strong>Overdue:</strong> ${fmt(ov)}</p>
        </div>
    `;
}

// Navigate to record payment page (URL contains supplier_id for refresh safety)
function navigateToRecordPaymentPage(supplierId) {
    if (!supplierId) return;
    window.location.hash = '#purchases-record-payment?supplier_id=' + encodeURIComponent(supplierId);
}

// Record Payment Page — same form and allocation table as former modal, with invoice drill-down
async function renderRecordPaymentPage(supplierId) {
    currentPurchaseSubPage = 'record-payment';
    const page = document.getElementById('purchases');
    if (!page) return;

    if (!supplierId) {
        page.innerHTML = `
            <div class="card" id="recordPaymentPage" style="padding: 2rem;">
                <h3 style="margin: 0 0 1rem 0;">Supplier not found</h3>
                <p style="color: var(--text-secondary); margin-bottom: 1rem;">The supplier could not be loaded. Please select a supplier from the Supplier Payments page.</p>
                <a href="#" class="btn btn-primary" onclick="window.location.hash='#purchases-supplier-payments'; if(window.loadPurchaseSubPage) window.loadPurchaseSubPage('supplier-payments'); return false;"><i class="fas fa-arrow-left"></i> Back to Supplier Payments</a>
            </div>
        `;
        return;
    }

    let supplier = null;
    try {
        supplier = await API.suppliers.get(supplierId);
    } catch (e) {
        page.innerHTML = `
            <div class="card" id="recordPaymentPage" style="padding: 2rem;">
                <h3 style="margin: 0 0 1rem 0;">Supplier not found</h3>
                <p style="color: var(--text-secondary); margin-bottom: 1rem;">The supplier could not be loaded. Please check the link or go back to Supplier Payments.</p>
                <a href="#" class="btn btn-primary" onclick="window.location.hash='#purchases-supplier-payments'; if(window.loadPurchaseSubPage) window.loadPurchaseSubPage('supplier-payments'); return false;"><i class="fas fa-arrow-left"></i> Back to Supplier Payments</a>
            </div>
        `;
        return;
    }

    const payDate = new Date().toISOString().slice(0, 10);
    let unpaidInvoices = [];
    try {
        const params = { company_id: CONFIG.COMPANY_ID, supplier_id: supplierId };
        if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
        const list = await API.purchases.listInvoices(params);
        unpaidInvoices = (list || []).filter(inv => inv.status === 'BATCHED' && (parseFloat(inv.balance) || 0) > 0);
    } catch (e) {
        console.warn('Could not load invoices for allocation:', e);
    }

    let allocationDatePreset = 'this_month';
    let allocationDateFrom = null;
    let allocationDateTo = null;
    function filterUnpaidInvoices() {
        let from = allocationDateFrom;
        let to = allocationDateTo;
        if (allocationDatePreset && allocationDatePreset !== 'custom') {
            const range = getSupplierInvoicesDateRange(allocationDatePreset);
            if (range) {
                from = range.dateFrom;
                to = range.dateTo;
            }
        }
        if (!from && !to) return unpaidInvoices;
        return unpaidInvoices.filter(inv => {
            if (!inv.invoice_date) return false;
            const d = inv.invoice_date.slice(0, 10);
            if (from && d < from) return false;
            if (to && d > to) return false;
            return true;
        });
    }
    function buildAllocationRows(sourceInvoices) {
        return sourceInvoices.map(inv => {
            const bal = parseFloat(inv.balance) || 0;
            return {
                id: inv.id,
                invoice_number: inv.invoice_number || '—',
                supplier_invoice_number: inv.supplier_invoice_number || inv.reference || '—',
                due_date: inv.due_date ? new Date(inv.due_date).toLocaleDateString('en-KE') : '—',
                total: parseFloat(inv.total_inclusive) || 0,
                balance: bal,
            };
        });
    }
    const initialInvoices = filterUnpaidInvoices();
    const allocationRows = buildAllocationRows(initialInvoices);
    const tableBody = allocationRows.length === 0
        ? '<tr><td colspan="7" style="padding: 1rem; color: var(--text-secondary);">No unpaid (posted) invoices in this period. Unallocated amount will become supplier credit.</td></tr>'
        : allocationRows.map((row, i) => `
            <tr class="alloc-row-clickable" data-invoice-id="${row.id}" data-balance="${row.balance}" style="cursor: pointer;">
                <td style="padding: 0.5rem;">${escapeHtml(row.invoice_number)}</td>
                <td style="padding: 0.5rem;">${row.due_date}</td>
                <td style="padding: 0.5rem;">${escapeHtml(row.supplier_invoice_number)}</td>
                <td style="padding: 0.5rem; text-align: right;">${fmt(row.total)}</td>
                <td style="padding: 0.5rem; text-align: right;">${fmt(row.balance)}</td>
                <td style="padding: 0.5rem;" onclick="event.stopPropagation();"><input type="checkbox" class="alloc-check" data-idx="${i}" data-balance="${row.balance}"></td>
                <td style="padding: 0.5rem;" onclick="event.stopPropagation();"><input type="number" class="form-input alloc-amount" data-invoice-id="${row.id}" data-balance="${row.balance}" step="0.01" min="0" max="${row.balance}" placeholder="0" style="width: 100px; text-align: right;"></td>
            </tr>
        `).join('');

    const supplierName = escapeHtml(supplier.name || '—');
    page.innerHTML = `
        <div class="card" id="recordPaymentPage">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; border-bottom: 1px solid var(--border-color); flex-wrap: wrap; gap: 0.5rem;">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <a href="#" class="btn btn-outline" onclick="window.location.hash='#purchases-supplier-payments'; if(window.loadPurchaseSubPage) window.loadPurchaseSubPage('supplier-payments'); return false;" title="Back to Supplier Payments"><i class="fas fa-arrow-left"></i></a>
                    <h3 class="card-title" style="margin: 0; font-size: 1.25rem;">Record Supplier Payment</h3>
                </div>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div class="form-group" style="margin-bottom: 1.5rem; padding: 1rem; background: var(--bg-secondary, #f8f9fa); border-radius: 0.25rem;">
                    <h4 style="margin: 0 0 0.5rem 0; font-size: 1rem;">Supplier</h4>
                    <p style="margin: 0; font-weight: 600;">${supplierName}</p>
                    <p style="margin: 0.25rem 0 0 0; font-size: 0.875rem; color: var(--text-secondary);">ID: ${escapeHtml(supplierId)}</p>
                </div>
                <form id="newPaymentForm">
                    <input type="hidden" id="recordPaymentPageFlag" value="1">
                    <div class="form-row">
                        <div class="form-group"><label class="form-label">Payment Date *</label><input type="date" class="form-input" name="payment_date" value="${payDate}" required></div>
                        <div class="form-group"><label class="form-label">Method *</label><select class="form-select" name="method" id="newPaymentMethod" required><option value="cash">Cash</option><option value="bank">Bank</option><option value="mpesa">MPesa</option><option value="card">Card</option><option value="cheque">Cheque</option></select></div>
                    </div>
                    <div class="form-group" id="newPaymentRefGroup"><label class="form-label" id="newPaymentRefLabel">Reference</label><input type="text" class="form-input" name="reference" id="newPaymentRefInput" placeholder="Optional"></div>
                    <div class="form-group"><label class="form-label">Amount (KES) *</label><input type="number" id="newPaymentAmount" class="form-input" name="amount" step="0.01" min="0.01" required></div>
                    <div class="form-group" style="margin-top: 1rem;">
                        <label class="form-label">Allocate to invoices</label>
                        <div class="form-row" style="margin-bottom: 0.5rem; gap: 0.5rem; align-items: center;">
                            <div class="form-group">
                                <select id="allocationDatePreset" class="form-select" style="min-width: 130px; font-size: 0.8rem;">
                                    <option value="today">Today</option><option value="yesterday">Yesterday</option>
                                    <option value="this_week">This Week</option><option value="last_week">Last Week</option>
                                    <option value="this_month" selected>This Month</option><option value="last_month">Last Month</option>
                                    <option value="this_year">This Year</option><option value="last_year">Last Year</option>
                                    <option value="custom">Custom</option>
                                </select>
                            </div>
                            <div class="form-group" id="allocationDateCustom" style="display: none; gap: 0.25rem;">
                                <input type="date" id="allocationDateFrom" class="form-input" style="width: 130px;">
                                <input type="date" id="allocationDateTo" class="form-input" style="width: 130px;">
                            </div>
                            <button type="button" class="btn btn-outline btn-sm" id="allocationDateApply">Apply</button>
                        </div>
                        <div class="table-container" style="overflow-x: auto; max-height: 320px; overflow-y: auto;">
                            <table style="width: 100%; border-collapse: collapse; font-size: 0.875rem;">
                                <thead><tr><th>Invoice</th><th>Due Date</th><th>Supplier Inv No</th><th>Total</th><th>Balance</th><th>Allocate?</th><th>Amount (KES)</th></tr></thead>
                                <tbody id="newPaymentAllocTbody">${tableBody}</tbody>
                            </table>
                        </div>
                        <div id="newPaymentAllocSummary" style="margin-top: 0.75rem; padding: 0.5rem; background: var(--bg-secondary, #f5f5f5); border-radius: 0.25rem; font-size: 0.875rem;">Payment Amount: KES 0.00 &nbsp;|&nbsp; Total Allocated: KES 0.00 &nbsp;|&nbsp; Unallocated: KES 0.00</div>
                        <p id="newPaymentUnallocatedWarning" style="display: none; font-size: 0.875rem; color: var(--warning-color, #856404); margin-top: 0.5rem;">Unallocated amount will remain as supplier credit.</p>
                    </div>
                </form>
                <div style="margin-top: 1.5rem; display: flex; gap: 0.5rem;">
                    <a href="#" class="btn btn-secondary" onclick="window.location.hash='#purchases-supplier-payments'; if(window.loadPurchaseSubPage) window.loadPurchaseSubPage('supplier-payments'); return false;">Cancel</a>
                    <button type="button" class="btn btn-primary" id="submitNewPaymentBtn" onclick="submitNewPayment('${supplierId}')">Record Payment</button>
                </div>
            </div>
        </div>
    `;

    const CASHLESS_METHODS = ['mpesa', 'bank', 'card', 'cheque'];
    const methodEl = document.getElementById('newPaymentMethod');
    const refInput = document.getElementById('newPaymentRefInput');
    const refLabel = document.getElementById('newPaymentRefLabel');
    function updateRefRequired() {
        const m = (methodEl && methodEl.value || '').toLowerCase();
        const needsRef = CASHLESS_METHODS.includes(m);
        if (refInput) { refInput.required = needsRef; refInput.placeholder = needsRef ? 'M-Pesa code, transaction ID, cheque number, etc. *' : 'Optional'; }
        if (refLabel) refLabel.textContent = needsRef ? 'Reference *' : 'Reference';
    }
    if (methodEl) methodEl.addEventListener('change', updateRefRequired);
    updateRefRequired();

    const amountEl = document.getElementById('newPaymentAmount');
    const summaryEl = document.getElementById('newPaymentAllocSummary');
    const warningEl = document.getElementById('newPaymentUnallocatedWarning');
    function updateAllocSummary() {
        const amount = parseFloat(amountEl && amountEl.value) || 0;
        let totalAlloc = 0;
        document.querySelectorAll('.alloc-amount').forEach(function(input) {
            totalAlloc += parseFloat(input.value) || 0;
        });
        const unallocated = Math.max(0, amount - totalAlloc);
        if (summaryEl) summaryEl.innerHTML = 'Payment Amount: ' + fmt(amount) + ' &nbsp;|&nbsp; Total Allocated: ' + fmt(totalAlloc) + ' &nbsp;|&nbsp; Unallocated: ' + fmt(unallocated);
        if (warningEl) warningEl.style.display = (amount > 0 && unallocated > 0) ? 'block' : 'none';
    }
    function wireAllocationRowEvents() {
        document.querySelectorAll('.alloc-check').forEach(function(cb) {
            cb.addEventListener('change', function() {
                const row = this.closest('tr');
                const input = row && row.querySelector('.alloc-amount');
                if (input) {
                    input.value = this.checked ? (row.dataset.balance || '0') : '';
                    updateAllocSummary();
                }
            });
        });
        document.querySelectorAll('.alloc-amount').forEach(function(input) {
            input.addEventListener('input', updateAllocSummary);
        });
        document.querySelectorAll('#newPaymentAllocTbody tr.alloc-row-clickable').forEach(function(tr) {
            tr.addEventListener('click', function(e) {
                if (e.target.closest('input') || e.target.closest('button')) return;
                const id = tr.dataset.invoiceId;
                if (id && window.showInvoiceDetailsModal) window.showInvoiceDetailsModal(id);
            });
        });
    }
    wireAllocationRowEvents();
    if (amountEl) amountEl.addEventListener('input', updateAllocSummary);

    const allocationPresetEl = document.getElementById('allocationDatePreset');
    const allocationCustomEl = document.getElementById('allocationDateCustom');
    const allocationFromEl = document.getElementById('allocationDateFrom');
    const allocationToEl = document.getElementById('allocationDateTo');
    const allocationApplyBtn = document.getElementById('allocationDateApply');
    if (allocationPresetEl && allocationCustomEl && allocationApplyBtn) {
        allocationPresetEl.addEventListener('change', function() {
            allocationDatePreset = allocationPresetEl.value || 'this_month';
            allocationCustomEl.style.display = allocationDatePreset === 'custom' ? 'flex' : 'none';
        });
        allocationApplyBtn.addEventListener('click', function() {
            if (allocationDatePreset === 'custom' && allocationFromEl && allocationToEl) {
                allocationDateFrom = allocationFromEl.value || null;
                allocationDateTo = allocationToEl.value || null;
            } else {
                allocationDateFrom = null;
                allocationDateTo = null;
            }
            const filtered = buildAllocationRows(filterUnpaidInvoices());
            const tbody = document.getElementById('newPaymentAllocTbody');
            if (!tbody) return;
            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="padding: 1rem; color: var(--text-secondary);">No unpaid (posted) invoices in this period. Unallocated amount will become supplier credit.</td></tr>';
            } else {
                tbody.innerHTML = filtered.map(function(row, i) {
                    return '<tr class="alloc-row-clickable" data-invoice-id="' + row.id + '" data-balance="' + row.balance + '" style="cursor: pointer;">' +
                        '<td style="padding: 0.5rem;">' + escapeHtml(row.invoice_number) + '</td>' +
                        '<td style="padding: 0.5rem;">' + row.due_date + '</td>' +
                        '<td style="padding: 0.5rem;">' + escapeHtml(row.supplier_invoice_number) + '</td>' +
                        '<td style="padding: 0.5rem; text-align: right;">' + fmt(row.total) + '</td>' +
                        '<td style="padding: 0.5rem; text-align: right;">' + fmt(row.balance) + '</td>' +
                        '<td style="padding: 0.5rem;" onclick="event.stopPropagation();"><input type="checkbox" class="alloc-check" data-idx="' + i + '" data-balance="' + row.balance + '"></td>' +
                        '<td style="padding: 0.5rem;" onclick="event.stopPropagation();"><input type="number" class="form-input alloc-amount" data-invoice-id="' + row.id + '" data-balance="' + row.balance + '" step="0.01" min="0" max="' + row.balance + '" placeholder="0" style="width: 100px; text-align: right;"></td></tr>';
                }).join('');
            }
            wireAllocationRowEvents();
            updateAllocSummary();
        });
    }
}

// Invoice Details modal (read-only) — opened when clicking an invoice row on the record payment page
async function showInvoiceDetailsModal(invoiceId) {
    if (!invoiceId || !window.API || !window.API.purchases || !window.API.purchases.getInvoice) return;
    let invoice = null;
    try {
        invoice = await API.purchases.getInvoice(invoiceId);
    } catch (e) {
        showToast(e.message || 'Failed to load invoice', 'error');
        return;
    }
    const ref = escapeHtml(invoice.invoice_number || '—');
    const supplierRef = escapeHtml((invoice.reference || invoice.supplier_invoice_number || '—').toString());
    const supplierName = escapeHtml(invoice.supplier_name || '—');
    const invDate = invoice.invoice_date ? new Date(invoice.invoice_date).toLocaleDateString('en-KE') : '—';
    const dueDate = invoice.due_date ? new Date(invoice.due_date).toLocaleDateString('en-KE') : '—';
    const status = invoice.status || '—';
    const total = fmt(invoice.total_inclusive);
    const paid = fmt(invoice.amount_paid);
    const balance = fmt(invoice.balance);
    const items = (invoice.items || []).map(function(item) {
        const name = escapeHtml((item.item_name || item.item_code || item.item && (item.item.name || item.item.code)) || '—');
        const qty = item.quantity != null ? item.quantity : '—';
        const unit = escapeHtml((item.unit_name || '—').toString());
        const cost = fmt(item.unit_cost_exclusive);
        const lineTotal = fmt(item.line_total_inclusive);
        return '<tr><td style="padding: 0.5rem;">' + name + '</td><td style="padding: 0.5rem; text-align: right;">' + qty + '</td><td style="padding: 0.5rem;">' + unit + '</td><td style="padding: 0.5rem; text-align: right;">' + cost + '</td><td style="padding: 0.5rem; text-align: right;">' + lineTotal + '</td></tr>';
    }).join('');
    const content =
        '<div style="max-height: 70vh; overflow-y: auto;">' +
        '<div style="margin-bottom: 1rem;">' +
        '<h4 style="margin: 0 0 0.5rem 0;">Invoice header</h4>' +
        '<p style="margin: 0.25rem 0;"><strong>Invoice:</strong> ' + ref + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Supplier invoice number:</strong> ' + supplierRef + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Supplier:</strong> ' + supplierName + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Invoice date:</strong> ' + invDate + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Due date:</strong> ' + dueDate + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Status:</strong> ' + status + '</p>' +
        '</div>' +
        '<div style="margin-bottom: 1rem;">' +
        '<h4 style="margin: 0 0 0.5rem 0;">Totals</h4>' +
        '<p style="margin: 0.25rem 0;"><strong>Total:</strong> ' + total + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Paid:</strong> ' + paid + '</p>' +
        '<p style="margin: 0.25rem 0;"><strong>Balance:</strong> ' + balance + '</p>' +
        '</div>' +
        '<div>' +
        '<h4 style="margin: 0 0 0.5rem 0;">Line items</h4>' +
        '<div class="table-container" style="overflow-x: auto;">' +
        '<table style="width: 100%; border-collapse: collapse; font-size: 0.875rem;">' +
        '<thead><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Unit cost</th><th>Line total</th></tr></thead>' +
        '<tbody>' + items + '</tbody></table></div></div></div>';
    const footer = '<button class="btn btn-secondary" onclick="closeModal()">Close</button><button class="btn btn-primary" onclick="closeModal(); if(window.viewSupplierInvoice) window.viewSupplierInvoice(\'' + invoiceId + '\');">Open Full Invoice</button>';
    showModal('Invoice Details', content, footer);
}

// New Payment — navigates to record payment page (modal removed)
async function showNewPaymentModal(supplierId) {
    navigateToRecordPaymentPage(supplierId);
}

async function submitNewPayment(supplierId) {
    const form = document.getElementById('newPaymentForm');
    if (!form) return;
    const fd = new FormData(form);
    const amount = parseFloat(fd.get('amount')) || 0;
    if (amount <= 0) {
        showToast('Enter a valid payment amount', 'error');
        return;
    }
    const method = (fd.get('method') || '').toLowerCase();
    const reference = (fd.get('reference') || '').trim();
    const cashlessMethods = ['mpesa', 'bank', 'card', 'cheque'];
    if (cashlessMethods.includes(method) && !reference) {
        showToast('Reference is required for MPesa, Bank, Card, and Cheque payments (e.g. transaction ID, M-Pesa code)', 'error');
        return;
    }
    const allocations = [];
    let totalAlloc = 0;
    document.querySelectorAll('.alloc-amount').forEach(input => {
        const val = parseFloat(input.value) || 0;
        if (val <= 0) return;
        const balance = parseFloat(input.dataset.balance) || 0;
        if (val > balance) {
            showToast(`Allocation ${val} exceeds invoice balance ${balance}`, 'error');
            return;
        }
        allocations.push({ supplier_invoice_id: input.dataset.invoiceId, allocated_amount: val });
        totalAlloc += val;
    });
    if (totalAlloc > amount) {
        showToast('Total allocated cannot exceed payment amount', 'error');
        return;
    }
    if (!CONFIG.BRANCH_ID) {
        showToast('Branch context required. Select a branch in Settings.', 'error');
        return;
    }
    const btn = document.getElementById('submitNewPaymentBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    try {
        await API.suppliers.createPayment({
            branch_id: CONFIG.BRANCH_ID,
            supplier_id: supplierId,
            payment_date: fd.get('payment_date'),
            method: fd.get('method'),
            reference: fd.get('reference') || null,
            amount,
            allocations: allocations.length ? allocations : undefined,
        });
        showToast('Payment recorded', 'success');
        if (document.getElementById('recordPaymentPageFlag')) {
            window.location.hash = '#purchases-supplier-payments';
            if (window.loadPurchaseSubPage) window.loadPurchaseSubPage('supplier-payments');
            if (document.getElementById('supplierPaymentsTable')) setTimeout(function() { if (window.fetchSupplierPaymentsData) window.fetchSupplierPaymentsData(); }, 100);
        } else {
            closeModal();
            if (window.currentSupplierDetailId && String(window.currentSupplierDetailId) === String(supplierId)) {
                refreshSupplierDetailAfterAction(supplierId);
            }
            if (document.getElementById('supplierPaymentsTable')) fetchSupplierPaymentsData();
            else if (window.renderSupplierTabContent) renderSupplierTabContent(supplierId, 'payments');
        }
    } catch (e) {
        showToast(e.message || (e.detail && (Array.isArray(e.detail) ? e.detail.map(x => x.msg || x).join(' ') : e.detail)) || 'Failed to record payment', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Record Payment'; }
    }
}

function showAllocatePaymentModal(invoiceId, supplierId) {
    if (supplierId) {
        showNewPaymentModal(supplierId);
    } else {
        showToast('Open the supplier first, then use New Payment to allocate.', 'info');
    }
}

// New Return Modal — full flow: supplier, optional link invoice, items (search + quantity + cost), reason
async function showNewReturnModal(supplierId, linkedInvoiceId = null) {
    if (!supplierId) {
        showToast('Select a supplier first (open supplier detail).', 'warning');
        return;
    }
    let supplier = null;
    let invoices = [];
    try {
        supplier = await API.suppliers.get(supplierId);
        const params = { company_id: CONFIG.COMPANY_ID, supplier_id: supplierId };
        if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
        invoices = await API.purchases.listInvoices(params);
        invoices = (invoices || []).filter(inv => inv.status === 'BATCHED');
    } catch (e) {
        showToast('Could not load supplier or invoices', 'error');
        return;
    }
    const invoiceOptions = invoices.map(inv => `<option value="${inv.id}" ${inv.id === linkedInvoiceId ? 'selected' : ''}>${escapeHtml(inv.invoice_number || inv.id)} - ${fmt(inv.total_inclusive)}</option>`).join('');
    const returnLines = []; // { item_id, item_name, quantity, unit_cost, line_total, batch_number?, expiry_date? }
    const today = new Date().toISOString().slice(0, 10);
    const content = `
        <form id="newReturnForm">
            <div class="form-group">
                <label class="form-label">Supplier</label>
                <input type="text" class="form-input" value="${escapeHtml(supplier.name || '')}" readonly>
            </div>
            <div class="form-group">
                <label class="form-label">Link to invoice (optional)</label>
                <select class="form-select" name="linked_invoice_id" id="newReturnLinkedInvoice">
                    <option value="">— None —</option>
                    ${invoiceOptions}
                </select>
            </div>
            <div class="form-row">
                <div class="form-group"><label class="form-label">Return Date *</label><input type="date" class="form-input" name="return_date" value="${today}" required></div>
                <div class="form-group" style="flex: 1;"><label class="form-label">Reason</label><input type="text" class="form-input" name="reason" placeholder="e.g. Expired, Damaged"></div>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <label class="form-label">Items to return</label>
                <div style="margin-bottom: 0.5rem;">
                    <input type="text" id="newReturnItemSearch" class="form-input" placeholder="Search item by name or SKU..." style="max-width: 300px;" autocomplete="off">
                    <span id="newReturnItemStock" style="font-size: 0.875rem; color: var(--text-secondary); margin-left: 0.5rem;"></span>
                </div>
                <div class="table-container" style="overflow-x: auto; max-height: 200px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.875rem;">
                        <thead><tr><th>Item</th><th>Qty</th><th>Unit cost (KES)</th><th>Total (KES)</th><th></th></tr></thead>
                        <tbody id="newReturnLinesTbody"></tbody>
                    </table>
                </div>
                <p id="newReturnLineError" style="display: none; color: var(--danger-color); font-size: 0.875rem; margin-top: 0.5rem;"></p>
            </div>
        </form>
    `;
    const footer = `<button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button><button type="button" class="btn btn-primary" id="submitNewReturnBtn" onclick="submitNewReturn('${supplierId}')">Save Return (Pending)</button>`;
    showModal('New Return', content, footer);
    const tbody = document.getElementById('newReturnLinesTbody');
    const searchInput = document.getElementById('newReturnItemSearch');
    const stockSpan = document.getElementById('newReturnItemStock');
    let searchDropdown = null;
    let selectedReturnItem = null; // { id, name, sku }

    function renderReturnLines() {
        if (!tbody) return;
        if (returnLines.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="padding: 1rem; color: var(--text-secondary);">Search and add items above.</td></tr>';
            return;
        }
        tbody.innerHTML = returnLines.map((line, i) => `
            <tr data-idx="${i}">
                <td style="padding: 0.5rem;">${escapeHtml(line.item_name || '—')}</td>
                <td style="padding: 0.5rem;"><input type="number" class="form-input return-line-qty" data-idx="${i}" value="${line.quantity}" min="0.01" step="0.01" style="width: 80px;"></td>
                <td style="padding: 0.5rem;"><input type="number" class="form-input return-line-cost" data-idx="${i}" value="${line.unit_cost}" min="0" step="0.01" style="width: 90px;"></td>
                <td style="padding: 0.5rem;">${fmt(line.quantity * line.unit_cost)}</td>
                <td style="padding: 0.5rem;"><button type="button" class="btn btn-outline btn-sm" onclick="window.removeNewReturnLine(${i})">Remove</button></td>
            </tr>
        `).join('');
        tbody.querySelectorAll('.return-line-qty').forEach(el => el.addEventListener('input', recalcReturnLine));
        tbody.querySelectorAll('.return-line-cost').forEach(el => el.addEventListener('input', recalcReturnLine));
    }
    function recalcReturnLine() {
        const idx = parseInt(this.dataset.idx, 10);
        const row = returnLines[idx];
        if (!row) return;
        const qtyEl = tbody.querySelector(`.return-line-qty[data-idx="${idx}"]`);
        const costEl = tbody.querySelector(`.return-line-cost[data-idx="${idx}"]`);
        row.quantity = parseFloat(qtyEl?.value) || 0;
        row.unit_cost = parseFloat(costEl?.value) || 0;
        row.line_total = row.quantity * row.unit_cost;
        renderReturnLines();
    }
    window.removeNewReturnLine = function (idx) {
        returnLines.splice(idx, 1);
        renderReturnLines();
    };

    searchInput.addEventListener('input', debounceReturnSearch);
    searchInput.addEventListener('focus', function () {
        if (searchInput.value.trim().length >= 2) debounceReturnSearch();
    });
    let returnSearchTimeout = null;
    function debounceReturnSearch() {
        clearTimeout(returnSearchTimeout);
        returnSearchTimeout = setTimeout(async () => {
            const q = searchInput.value.trim();
            if (q.length < 2) {
                if (searchDropdown) { searchDropdown.remove(); searchDropdown = null; }
                stockSpan.textContent = '';
                return;
            }
            try {
                const items = await API.items.search(q, CONFIG.COMPANY_ID, 20, CONFIG.BRANCH_ID, true);
                if (!items || items.length === 0) {
                    showReturnItemDropdown([]);
                    return;
                }
                showReturnItemDropdown(items);
            } catch (_) {
                stockSpan.textContent = 'Search failed';
            }
        }, 60);
    }
    function showReturnItemDropdown(items) {
        if (searchDropdown) searchDropdown.remove();
        searchDropdown = document.createElement('div');
        searchDropdown.setAttribute('id', 'newReturnItemDropdown');
        searchDropdown.style.cssText = 'position: absolute; background: white; border: 1px solid var(--border-color); border-radius: 0.25rem; box-shadow: 0 4px 12px rgba(0,0,0,0.15); max-height: 220px; overflow-y: auto; z-index: 1050;';
        searchDropdown.innerHTML = items.map(it => {
            const name = (it.name || '').trim() || '—';
            const sku = (it.sku || it.item_code || '') || '';
            const stock = it.base_quantity != null ? it.base_quantity : (it.current_stock != null ? it.current_stock : '—');
            return `<div class="new-return-item-option" data-id="${it.id}" data-name="${escapeHtml(name)}" data-sku="${escapeHtml(sku)}" data-stock="${stock}" data-cost="${it.last_unit_cost != null ? it.last_unit_cost : (it.default_cost != null ? it.default_cost : 0)}" style="padding: 0.5rem 0.75rem; cursor: pointer; border-bottom: 1px solid var(--border-color);">${escapeHtml(name)} ${sku ? '(' + escapeHtml(sku) + ')' : ''} — Stock: ${stock}</div>`;
        }).join('');
        searchInput.parentElement.style.position = 'relative';
        searchInput.parentElement.appendChild(searchDropdown);
        searchDropdown.querySelectorAll('.new-return-item-option').forEach(el => {
            el.addEventListener('mousedown', function (e) {
                e.preventDefault();
                const id = el.dataset.id;
                const name = el.dataset.name || '';
                const sku = el.dataset.sku || '';
                const stock = parseFloat(el.dataset.stock) || 0;
                const cost = parseFloat(el.dataset.cost) || 0;
                searchInput.value = name + (sku ? ' (' + sku + ')' : '');
                if (searchDropdown) { searchDropdown.remove(); searchDropdown = null; }
                const existing = returnLines.find(l => String(l.item_id) === String(id));
                if (existing) {
                    showToast('Item already in list', 'info');
                    return;
                }
                if (stock <= 0) {
                    document.getElementById('newReturnLineError').style.display = 'block';
                    document.getElementById('newReturnLineError').textContent = 'Item has no stock; cannot return.';
                    return;
                }
                returnLines.push({ item_id: id, item_name: name + (sku ? ' (' + sku + ')' : ''), quantity: 1, unit_cost: cost, line_total: cost });
                renderReturnLines();
                document.getElementById('newReturnLineError').style.display = 'none';
                searchInput.value = '';
            });
        });
    }
    searchInput.addEventListener('blur', () => setTimeout(() => { if (searchDropdown) { searchDropdown.remove(); searchDropdown = null; } }, 150));
    window._newReturnLines = returnLines;
    renderReturnLines();
}

async function submitNewReturn(supplierId) {
    const form = document.getElementById('newReturnForm');
    if (!form) return;
    const fd = new FormData(form);
    const returnDate = fd.get('return_date');
    const reason = fd.get('reason') || null;
    const linkedInvoiceId = fd.get('linked_invoice_id') || null;
    const lines = window._newReturnLines || [];
    const tbody = document.getElementById('newReturnLinesTbody');
    if (tbody && lines.length > 0) {
        lines.forEach((line, idx) => {
            const qtyEl = tbody.querySelector(`.return-line-qty[data-idx="${idx}"]`);
            const costEl = tbody.querySelector(`.return-line-cost[data-idx="${idx}"]`);
            if (qtyEl) line.quantity = parseFloat(qtyEl.value) || 0;
            if (costEl) line.unit_cost = parseFloat(costEl.value) || 0;
            line.line_total = line.quantity * line.unit_cost;
        });
    }
    if (!Array.isArray(lines) || lines.length === 0) {
        showToast('Add at least one item to return', 'error');
        return;
    }
    const branchId = CONFIG.BRANCH_ID;
    if (!branchId) {
        showToast('Branch context required', 'error');
        return;
    }
    const payload = {
        branch_id: branchId,
        supplier_id: supplierId,
        return_date: returnDate,
        reason: reason || null,
        linked_invoice_id: linkedInvoiceId || null,
        lines: lines.map(l => ({
            item_id: l.item_id,
            batch_number: l.batch_number || null,
            expiry_date: l.expiry_date || null,
            quantity: l.quantity,
            unit_cost: l.unit_cost,
            line_total: l.quantity * l.unit_cost,
        })),
    };
    const btn = document.getElementById('submitNewReturnBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    try {
        await API.suppliers.createReturn(payload);
        showToast('Return saved (Pending). Approve from Returns tab to credit supplier.', 'success');
        closeModal();
        if (window.currentSupplierDetailId && String(window.currentSupplierDetailId) === String(supplierId)) {
            refreshSupplierDetailAfterAction(supplierId);
            await renderSupplierTabContent(supplierId, 'returns');
        }
    } catch (e) {
        showToast(e.message || (e.detail && (Array.isArray(e.detail) ? e.detail.map(x => x.msg || x).join(' ') : e.detail)) || 'Failed to save return', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save Return (Pending)'; }
    }
}

// =====================================================
// SUPPLIER PAYMENTS GLOBAL PAGE
// =====================================================
let supplierPaymentsDatePreset = 'this_month';
let supplierPaymentsDateFrom = '';
let supplierPaymentsDateTo = '';

async function renderSupplierPaymentsPage() {
    const page = document.getElementById('purchases');
    if (!page) return;
    const range = getSupplierInvoicesDateRange(supplierPaymentsDatePreset);
    const from = supplierPaymentsDateFrom || (range ? range.dateFrom : '');
    const to = supplierPaymentsDateTo || (range ? range.dateTo : '');
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                <h3 class="card-title" style="margin: 0;"><i class="fas fa-money-bill-wave"></i> Supplier Payments</h3>
                <div style="display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.5rem;">
                    <select id="supplierPaymentsPreset" class="form-select" style="min-width: 130px;">
                        <option value="today">Today</option><option value="yesterday">Yesterday</option>
                        <option value="this_week">This Week</option><option value="last_week">Last Week</option>
                        <option value="last_month">Last Month</option><option value="this_month" selected>This Month</option>
                        <option value="this_year">This Year</option><option value="last_year">Last Year</option>
                        <option value="custom">Custom</option>
                    </select>
                    <span id="supplierPaymentsCustomSpan" style="display: none;">
                        <input type="date" id="supplierPaymentsFrom" class="form-input" value="${from}" style="width: 120px;">
                        <input type="date" id="supplierPaymentsTo" class="form-input" value="${to}" style="width: 120px;">
                    </span>
                    <button type="button" class="btn btn-outline" id="supplierPaymentsApply">Apply</button>
                    <button type="button" class="btn btn-primary" onclick="showNewPaymentModalWithSupplierSelect()"><i class="fas fa-plus"></i> New Payment</button>
                </div>
            </div>
            <div class="card-body" style="padding: 1.5rem;"><div id="supplierPaymentsTable"><div class="spinner"></div></div></div>
        </div>
    `;
    document.getElementById('supplierPaymentsPreset').addEventListener('change', function () {
        supplierPaymentsDatePreset = this.value;
        document.getElementById('supplierPaymentsCustomSpan').style.display = this.value === 'custom' ? 'inline' : 'none';
    });
    document.getElementById('supplierPaymentsApply').addEventListener('click', () => fetchSupplierPaymentsData());
    await fetchSupplierPaymentsData();
}

async function fetchSupplierPaymentsData() {
    const preset = document.getElementById('supplierPaymentsPreset')?.value || 'this_month';
    supplierPaymentsDatePreset = preset;
    let from, to;
    if (preset === 'custom') {
        from = document.getElementById('supplierPaymentsFrom')?.value;
        to = document.getElementById('supplierPaymentsTo')?.value;
    } else {
        const r = getSupplierInvoicesDateRange(preset);
        from = r?.dateFrom;
        to = r?.dateTo;
    }
    if (from) supplierPaymentsDateFrom = from;
    if (to) supplierPaymentsDateTo = to;
    const cont = document.getElementById('supplierPaymentsTable');
    if (!cont) return;
    cont.innerHTML = '<div class="spinner"></div>';
    try {
        const params = {};
        if (CONFIG.BRANCH_ID) params.branch_id = CONFIG.BRANCH_ID;
        if (from) params.date_from = from;
        if (to) params.date_to = to;
        const payments = await API.suppliers.listPayments(params);
        if (!payments || payments.length === 0) {
            cont.innerHTML = '<div class="text-center" style="padding: 3rem;"><i class="fas fa-money-bill-wave" style="font-size: 3rem; color: var(--text-secondary);"></i><p>No payments in this period</p><p style="font-size: 0.875rem; color: var(--text-secondary);">Click "New Payment" to record a supplier payment.</p></div>';
            return;
        }
        cont.innerHTML = `
            <div class="table-container" style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead><tr><th>Supplier</th><th>Date</th><th>Method</th><th>Amount</th><th>Allocated</th></tr></thead>
                    <tbody>${payments.map(p => `
                        <tr style="cursor: pointer;" onclick="navigateToSupplierDetail('${p.supplier_id}')">
                            <td>${escapeHtml(p.supplier_name || '—')}</td>
                            <td>${p.payment_date ? new Date(p.payment_date).toLocaleDateString('en-KE') : '—'}</td>
                            <td>${escapeHtml(p.method || '—')}</td>
                            <td>${fmt(p.amount)}</td>
                            <td>${p.is_allocated ? 'Yes' : 'No'}</td>
                        </tr>
                    `).join('')}</tbody>
                </table>
            </div>
        `;
    } catch (e) {
        console.error('Payments load error:', e);
        cont.innerHTML = `<p style="color: var(--danger-color);">Failed to load payments: ${e.message || 'Unknown error'}</p><button class="btn btn-outline" onclick="fetchSupplierPaymentsData()">Retry</button>`;
    }
}

// New Payment from global page — select supplier first, then open payment modal
async function showNewPaymentModalWithSupplierSelect() {
    let suppliers = [];
    try {
        suppliers = await API.suppliers.list(CONFIG.COMPANY_ID) || [];
        if (!Array.isArray(suppliers)) suppliers = suppliers.suppliers || [];
    } catch (e) {
        showToast('Could not load suppliers', 'error');
        return;
    }
    if (suppliers.length === 0) {
        showToast('Create a supplier first (Suppliers Management)', 'warning');
        return;
    }
    const options = suppliers.map(s => `<option value="${s.id}">${escapeHtml(s.name || 'Supplier')}</option>`).join('');
    const content = `
        <div class="form-group"><label class="form-label">Select Supplier *</label>
        <select class="form-select" id="newPaymentSupplierSelect" required>${options}</select></div>
    `;
    const footer = '<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" onclick="var sid = document.getElementById(\'newPaymentSupplierSelect\').value; closeModal(); if(window.navigateToRecordPaymentPage) window.navigateToRecordPaymentPage(sid);">Continue</button>';
    showModal('New Payment — Select Supplier', content, footer);
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
                    <button class="btn btn-primary btn-sm" onclick="if(window.applyOrderBookFilters) window.applyOrderBookFilters()" title="Apply date and supplier filters and refresh">
                        <i class="fas fa-check"></i> Apply Filters
                    </button>
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
        case 'yesterday': {
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            const yy = yesterday.getFullYear(), mm = yesterday.getMonth(), dd = yesterday.getDate();
            dateFrom = dateTo = [yy, String(mm + 1).padStart(2, '0'), String(dd).padStart(2, '0')].join('-');
            break;
        }
        case 'this_week': {
            const day = now.getDay();
            const mon = new Date(now); mon.setDate(d - (day === 0 ? 6 : day - 1));
            const my = mon.getFullYear(), mm = mon.getMonth(), md = mon.getDate();
            dateFrom = [my, String(mm + 1).padStart(2, '0'), String(md).padStart(2, '0')].join('-');
            dateTo = [y, String(m + 1).padStart(2, '0'), String(d).padStart(2, '0')].join('-');
            break;
        }
        case 'last_week': {
            const day = now.getDay();
            const lastMon = new Date(now); lastMon.setDate(d - (day === 0 ? 6 : day - 1) - 7);
            const lmy = lastMon.getFullYear(), lmm = lastMon.getMonth(), lmd = lastMon.getDate();
            dateFrom = [lmy, String(lmm + 1).padStart(2, '0'), String(lmd).padStart(2, '0')].join('-');
            const lastSun = new Date(lastMon); lastSun.setDate(lastSun.getDate() + 6);
            const lsy = lastSun.getFullYear(), lsm = lastSun.getMonth(), lsd = lastSun.getDate();
            dateTo = [lsy, String(lsm + 1).padStart(2, '0'), String(lsd).padStart(2, '0')].join('-');
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

async function applyOrderBookFilters() {
    const dateEl = document.getElementById('orderBookDateFilter');
    const supplierEl = document.getElementById('orderBookSupplierFilter');
    if (dateEl) orderBookDateFilter = dateEl.value || 'today';
    if (supplierEl) orderBookSupplierFilter = (supplierEl.value && supplierEl.value.trim()) ? supplierEl.value.trim() : null;
    await fetchAndRenderOrderBookData();
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
                    <input type="date" id="poOrderDate" class="form-input" value="${getLocalDateString()}" required>
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
    window.applyOrderBookFilters = applyOrderBookFilters;
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