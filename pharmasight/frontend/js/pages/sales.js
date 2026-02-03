// Sales Page - Sales Invoices and Quotations

let currentSalesSubPage = 'invoices'; // 'invoices', 'quotations'
let cart = [];
let currentInvoice = null;
let salesInvoices = [];
let salesDocuments = [];
let currentQuotation = null; // For quotation edit mode
let quotationItems = []; // For quotation items

// Initialize sales page
async function loadSales() {
    console.log('loadSales() called');
    const page = document.getElementById('sales');
    if (!page) {
        console.error('Sales page element not found!');
        return;
    }
    
    // Show the page
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
    
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
        console.warn('Company or Branch not configured');
        page.innerHTML = '<div class="card"><p>Please configure Company and Branch in Settings</p></div>';
        return;
    }
    
    console.log('Loading sales sub-page:', currentSalesSubPage);
    await loadSalesSubPage(currentSalesSubPage);
}

// Load specific sales sub-page
async function loadSalesSubPage(subPage) {
    console.log('loadSalesSubPage() called with:', subPage);
    currentSalesSubPage = subPage;
    const page = document.getElementById('sales');
    
    if (!page) {
        console.error('Sales page element not found in loadSalesSubPage!');
        return;
    }
    
    // Ensure page is visible
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
    
    switch(subPage) {
        case 'invoices':
            await renderSalesInvoicesPage();
            break;
        case 'quotations':
            if (typeof renderSalesQuotationsPage === 'function') {
                await renderSalesQuotationsPage();
            } else {
                console.warn('renderSalesQuotationsPage not implemented yet, showing invoices as fallback');
                await renderSalesInvoicesPage();
            }
            break;
        case 'create-invoice':
            await renderCreateSalesInvoicePage();
            break;
        case 'create-quotation':
            await renderCreateSalesQuotationPage();
            break;
        default:
            await renderSalesInvoicesPage();
    }
    
    // Update sub-nav active state
    updateSalesSubNavActiveState();
}

// Update sub-nav active state
function updateSalesSubNavActiveState() {
    const subNavItems = document.querySelectorAll('.sub-nav-item');
    subNavItems.forEach(item => {
        if (item.dataset.subPage === currentSalesSubPage) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

// Switch sales sub-page
function switchSalesSubPage(subPage) {
    loadSalesSubPage(subPage);
}

// =====================================================
// POINT OF SALE PAGE
// =====================================================

async function renderPOSPage() {
    console.log('renderPOSPage() called');
    const page = document.getElementById('sales');
    if (!page) return;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-cash-register"></i> Point of Sale</h3>
            </div>
            <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem;">
                <div>
                    <div class="form-group">
                        <label class="form-label">Search Item</label>
                        <input type="text" class="form-input" id="itemSearch" 
                               placeholder="Search by name, SKU, or barcode" 
                               onkeyup="searchItems(event)">
                    </div>
                    <div id="itemsList" style="max-height: 400px; overflow-y: auto;">
                        <p class="text-center">Search for items to add to cart</p>
                    </div>
                </div>
                <div>
                    <div class="card">
                        <h4>Cart</h4>
                        <div id="cartItems"></div>
                        <div id="cartSummary" style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color);"></div>
                        <button class="btn btn-primary" style="width: 100%; margin-top: 1rem;" 
                                onclick="processSale()" id="checkoutBtn" disabled>
                            <i class="fas fa-check"></i> Checkout
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    cart = [];
    renderCart();
}

// =====================================================
// SALES INVOICES PAGE
// =====================================================

async function renderSalesInvoicesPage() {
    console.log('renderSalesInvoicesPage() called');
    const page = document.getElementById('sales');
    if (!page) return;
    
    const today = new Date().toISOString().split('T')[0];
    
    // Render page shell
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice-dollar"></i> Sales Invoices
                </h3>
                <button class="btn btn-primary" onclick="if(window.createNewSalesInvoice) window.createNewSalesInvoice()">
                    <i class="fas fa-plus"></i> New Invoice
                </button>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <!-- Date Filter Bar -->
                <div style="margin-bottom: 1.5rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 50px;">From:</label>
                        <input type="date" 
                               class="form-input" 
                               id="filterDateFrom" 
                               value="${today}"
                               onchange="if(window.applySalesDateFilter) window.applySalesDateFilter()"
                               style="width: 150px;">
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <label style="font-weight: 500; min-width: 30px;">To:</label>
                        <input type="date" 
                               class="form-input" 
                               id="filterDateTo" 
                               value="${today}"
                               onchange="if(window.applySalesDateFilter) window.applySalesDateFilter()"
                               style="width: 150px;">
                    </div>
                    <button class="btn btn-outline" onclick="if(window.clearSalesDateFilter) window.clearSalesDateFilter()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                </div>
                
                <!-- Search Bar -->
                <div style="margin-bottom: 1.5rem;">
                    <input type="text" 
                           class="form-input" 
                           id="salesSearchInput" 
                           placeholder="Search by invoice number, customer..." 
                           onkeyup="if(window.filterSalesInvoices) window.filterSalesInvoices()"
                           style="width: 100%; max-width: 500px; padding: 0.75rem;">
                </div>
                
                <!-- Table Container -->
                <div class="table-container" style="max-height: calc(100vh - 400px); overflow-y: auto; position: relative;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <tr>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Invoice #</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Date</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Customer</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: right;">Amount</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Payment</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Mode</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="salesInvoicesTableBody">
                            <tr>
                                <td colspan="7" style="padding: 3rem; text-align: center;">
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
    
    // Fetch and render data
    await fetchAndRenderSalesInvoicesData();
}

// =====================================================
// SALES QUOTATIONS PAGE (placeholder - to be enhanced)
// =====================================================

async function renderSalesQuotationsPage() {
    console.log('renderSalesQuotationsPage() called');
    const page = document.getElementById('sales');
    if (!page) return;

    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice"></i> Sales Quotations
                </h3>
                <button class="btn btn-primary" onclick="createNewSalesQuotation()">
                    <i class="fas fa-plus"></i> New Quotation
                </button>
            </div>
            <div class="card-body" style="padding: 1.5rem;">
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: #f8f9fa;">
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Quotation #</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Date</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Customer</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: right;">Net</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: right;">VAT</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: right;">Total</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="salesQuotationsTableBody">
                            <tr>
                                <td colspan="8" style="padding: 3rem; text-align: center;">
                                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                                    <p style="color: var(--text-secondary);">Loading quotations...</p>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    
    // Fetch and render data
    await fetchAndRenderSalesQuotationsData();
}

let salesQuotations = [];

async function fetchAndRenderSalesQuotationsData() {
    const tbody = document.getElementById('salesQuotationsTableBody');
    if (!tbody) return;
    
    try {
        if (!CONFIG.BRANCH_ID) {
            throw new Error('Branch ID not configured');
        }
        
        salesQuotations = await API.quotations.listByBranch(CONFIG.BRANCH_ID);
        console.log('✅ Loaded sales quotations:', salesQuotations.length);
        renderSalesQuotationsTableBody();
    } catch (error) {
        console.error('Error fetching sales quotations:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                    <p style="color: var(--danger-color);">Error loading quotations</p>
                    <p style="color: var(--text-secondary); font-size: 0.875rem;">${error.message || 'Unknown error'}</p>
                    <button class="btn btn-outline" onclick="if(window.fetchAndRenderSalesQuotationsData) window.fetchAndRenderSalesQuotationsData()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </td>
            </tr>
        `;
    }
}

function renderSalesQuotationsTableBody() {
    const tbody = document.getElementById('salesQuotationsTableBody');
    if (!tbody) return;
    
    if (salesQuotations.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-file-invoice" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No quotations found</p>
                    <button class="btn btn-primary" onclick="createNewSalesQuotation()">
                        <i class="fas fa-plus"></i> Create Your First Quotation
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = salesQuotations.map(q => {
        const statusBadge = getQuotationStatusBadge(q.status);
        const dateStr = new Date(q.quotation_date).toLocaleDateString();
        return `
            <tr style="border-bottom: 1px solid var(--border-color); cursor: pointer;" onclick="if(window.viewQuotation) window.viewQuotation('${q.id}')">
                <td style="padding: 0.75rem;">
                    <strong style="color: var(--primary-color);">${escapeHtml(q.quotation_no)}</strong>
                </td>
                <td style="padding: 0.75rem;">${dateStr}</td>
                <td style="padding: 0.75rem;">${escapeHtml(q.customer_name || 'Walk-in')}</td>
                <td style="padding: 0.75rem; text-align: right;">${formatCurrency(q.total_exclusive)}</td>
                <td style="padding: 0.75rem; text-align: right;">${formatCurrency(q.vat_amount)}</td>
                <td style="padding: 0.75rem; text-align: right; font-weight: 600;">${formatCurrency(q.total_inclusive)}</td>
                <td style="padding: 0.75rem;">${statusBadge}</td>
                <td style="padding: 0.75rem;" onclick="event.stopPropagation();">
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); if(window.viewQuotation) window.viewQuotation('${q.id}')" title="View/Edit">
                            <i class="fas fa-eye"></i>
                        </button>
                        ${q.status === 'draft' ? `
                            <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); if(window.deleteQuotation) window.deleteQuotation('${q.id}')" title="Delete (Draft only)">
                                <i class="fas fa-trash"></i>
                            </button>
                        ` : ''}
                        ${q.status !== 'converted' ? `
                            <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); if(window.convertQuotationToInvoice) window.convertQuotationToInvoice('${q.id}')" title="Convert to Invoice">
                                <i class="fas fa-exchange-alt"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function getQuotationStatusBadge(status) {
    const badges = {
        'draft': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #e5e7eb; color: #374151; font-size: 0.875rem; font-weight: 500;">Draft</span>',
        'sent': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #dbeafe; color: #1e40af; font-size: 0.875rem; font-weight: 500;">Sent</span>',
        'accepted': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #dcfce7; color: #166534; font-size: 0.875rem; font-weight: 500;">Accepted</span>',
        'converted': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #fef3c7; color: #92400e; font-size: 0.875rem; font-weight: 500;">Converted</span>',
        'cancelled': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #fee2e2; color: #991b1b; font-size: 0.875rem; font-weight: 500;">Cancelled</span>'
    };
    return badges[status] || badges['draft'];
}

function createNewSalesQuotation() {
    loadSalesSubPage('create-quotation');
}

// View/Edit Quotation (same function - navigates to edit page)
async function viewQuotation(quotationId) {
    try {
        const quotation = await API.quotations.get(quotationId);
        const isDraft = quotation.status === 'draft';
        
        if (!isDraft) {
            // For non-draft quotations, show read-only view
            showToast('This quotation is not in draft status. Only draft quotations can be edited.', 'info');
            // TODO: Could show a read-only view modal
            return;
        }
        
        // For draft quotations, navigate to edit page (same as create page)
        currentQuotation = { 
            id: quotationId, 
            mode: 'edit',
            quotationData: quotation  // Store quotation data to populate form
        };
        
        // Navigate to create page (will load as edit mode)
        await loadSalesSubPage('create-quotation');
    } catch (error) {
        console.error('Error loading quotation:', error);
        showToast(error.message || 'Error loading quotation', 'error');
    }
}

// Edit Quotation (only DRAFT) - Same as view, navigates to create page
async function editQuotation(quotationId) {
    await viewQuotation(quotationId);
}

async function deleteQuotation(quotationId) {
    // First check if quotation is draft
    try {
        const quotation = await API.quotations.get(quotationId);
        if (quotation.status !== 'draft') {
            showToast(`Cannot delete quotation with status ${quotation.status}. Only draft quotations can be deleted.`, 'error');
            return;
        }
    } catch (error) {
        console.error('Error checking quotation status:', error);
        showToast('Error checking quotation status', 'error');
        return;
    }
    
    if (!confirm('Are you sure you want to delete this quotation? This action cannot be undone.')) {
        return;
    }
    
    try {
        await API.quotations.delete(quotationId);
        showToast('Quotation deleted successfully', 'success');
        
        // Clear auto-save timeout if any
        clearTimeout(window.autoSaveQuotationTimeout);
        
        // If we're on the edit page, navigate back to quotations list
        if (currentQuotation && currentQuotation.id === quotationId) {
            currentQuotation = null;
            quotationItems = [];
            await loadSalesSubPage('quotations');
        } else {
            // Refresh the quotations list
            await fetchAndRenderSalesQuotationsData();
        }
    } catch (error) {
        console.error('Error deleting quotation:', error);
        showToast(error.message || 'Failed to delete quotation', 'error');
    }
}

async function convertQuotationToInvoice(quotationId) {
    if (!confirm('Convert this quotation to a sales invoice? This will check stock availability and create an invoice.')) return;
    
    try {
        showToast('Converting quotation to invoice...', 'info');
        const invoice = await API.quotations.convertToInvoice(quotationId, {
            payment_mode: 'cash',
            payment_status: 'PAID'
        });
        showToast('Quotation converted to invoice successfully!', 'success');
        // Switch to invoices page and show the new invoice
        loadSalesSubPage('invoices');
        // TODO: Optionally highlight the new invoice
    } catch (error) {
        console.error('Error converting quotation:', error);
        const errorMsg = error.response?.data?.detail?.message || error.message || 'Failed to convert quotation';
        showToast(errorMsg, 'error');
    }
}

async function fetchAndRenderSalesInvoicesData() {
    const tbody = document.getElementById('salesInvoicesTableBody');
    if (!tbody) return;
    
    try {
        if (!CONFIG.BRANCH_ID) {
            throw new Error('Branch ID not configured');
        }
        
        salesInvoices = await API.sales.getBranchInvoices(CONFIG.BRANCH_ID);
        console.log('✅ Loaded sales invoices:', salesInvoices.length);
        renderSalesInvoicesTableBody();
    } catch (error) {
        console.error('Error fetching sales invoices:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="7" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                    <p style="color: var(--danger-color);">Error loading sales invoices</p>
                    <p style="color: var(--text-secondary); font-size: 0.875rem;">${error.message || 'Unknown error'}</p>
                    <button class="btn btn-outline" onclick="if(window.fetchAndRenderSalesInvoicesData) window.fetchAndRenderSalesInvoicesData()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </td>
            </tr>
        `;
    }
}

function renderSalesInvoicesTableBody() {
    const tbody = document.getElementById('salesInvoicesTableBody');
    if (!tbody) return;
    
    if (salesInvoices.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="padding: 3rem; text-align: center;">
                    <i class="fas fa-file-invoice-dollar" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <p style="color: var(--text-secondary); margin-bottom: 0.5rem; font-weight: 500;">No sales invoices found</p>
                    <button class="btn btn-primary" onclick="if(window.createNewSalesInvoice) window.createNewSalesInvoice()">
                        <i class="fas fa-plus"></i> Create Your First Sales Invoice
                    </button>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = salesInvoices.map(invoice => {
        const status = invoice.status || 'DRAFT';
        const statusBadge = getSalesInvoiceStatusBadge(status);
        const paymentStatusBadge = getPaymentStatusBadge(invoice.payment_status || 'UNPAID');
        
        return `
            <tr style="cursor: pointer; border-bottom: 1px solid var(--border-color);" onclick="if(window.viewSalesInvoice) window.viewSalesInvoice('${invoice.id}')">
                <td style="padding: 0.75rem;">
                    <strong style="color: var(--primary-color);">${escapeHtml(invoice.invoice_no || invoice.id.substring(0, 8))}</strong>
                </td>
                <td style="padding: 0.75rem;">${formatDate(invoice.invoice_date || invoice.created_at)}</td>
                <td style="padding: 0.75rem;">${escapeHtml(invoice.customer_name || 'Walk-in Customer')}</td>
                <td style="padding: 0.75rem; text-align: right;"><strong>${formatCurrency(invoice.total_inclusive || invoice.total || 0)}</strong></td>
                <td style="padding: 0.75rem;">${statusBadge}</td>
                <td style="padding: 0.75rem;">${paymentStatusBadge}</td>
                <td style="padding: 0.75rem;">${escapeHtml(invoice.payment_mode || 'Cash')}</td>
                <td style="padding: 0.75rem;" onclick="event.stopPropagation();">
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                        <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); if(window.viewSalesInvoice) window.viewSalesInvoice('${invoice.id}')" title="View">
                            <i class="fas fa-eye"></i>
                        </button>
                        ${status === 'DRAFT' ? `
                            <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); if(window.batchSalesInvoice) window.batchSalesInvoice('${invoice.id}')" title="Batch & Print">
                                <i class="fas fa-check"></i> Batch
                            </button>
                            <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); if(window.deleteSalesInvoice) window.deleteSalesInvoice('${invoice.id}')" title="Delete">
                                <i class="fas fa-trash"></i>
                            </button>
                        ` : ''}
                        ${status === 'BATCHED' && invoice.payment_status !== 'PAID' ? `
                            <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); if(window.collectPayment) window.collectPayment('${invoice.id}')" title="Collect Payment">
                                <i class="fas fa-money-bill-wave"></i> Pay
                            </button>
                        ` : ''}
                        ${status === 'BATCHED' || status === 'PAID' ? `
                            <button class="btn btn-sm btn-outline" onclick="event.stopPropagation(); if(window.printSalesInvoice) window.printSalesInvoice('${invoice.id}')" title="Print Receipt">
                                <i class="fas fa-print"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function getSalesInvoiceStatusBadge(status) {
    const badges = {
        'DRAFT': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #fef3c7; color: #92400e; font-size: 0.875rem; font-weight: 500;">DRAFT</span>',
        'BATCHED': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #dbeafe; color: #1e40af; font-size: 0.875rem; font-weight: 500;">BATCHED</span>',
        'PAID': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #dcfce7; color: #166534; font-size: 0.875rem; font-weight: 500;">PAID</span>',
        'CANCELLED': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #fee2e2; color: #991b1b; font-size: 0.875rem; font-weight: 500;">CANCELLED</span>'
    };
    return badges[status] || badges['DRAFT'];
}

function getPaymentStatusBadge(paymentStatus) {
    const badges = {
        'UNPAID': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #fee2e2; color: #991b1b; font-size: 0.875rem; font-weight: 500;">UNPAID</span>',
        'PARTIAL': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #fef3c7; color: #92400e; font-size: 0.875rem; font-weight: 500;">PARTIAL</span>',
        'PAID': '<span style="padding: 0.25rem 0.75rem; border-radius: 1rem; background: #dcfce7; color: #166534; font-size: 0.875rem; font-weight: 500;">PAID</span>'
    };
    return badges[paymentStatus] || badges['UNPAID'];
}

// Create new Sales Invoice
function createNewSalesInvoice() {
    console.log('createNewSalesInvoice() called');
    currentInvoice = null;  // Clear any edit mode
    documentItems = [];
    loadSalesSubPage('create-invoice');
}

// Render Create Sales Invoice Page
async function renderCreateSalesInvoicePage() {
    console.log('renderCreateSalesInvoicePage() called');
    const page = document.getElementById('sales');
    if (!page) return;
    
    // Check if we're in edit mode
    const isEditMode = currentInvoice && currentInvoice.mode === 'edit' && currentInvoice.id;
    let invoiceData = isEditMode ? currentInvoice.invoiceData : null;
    const invoiceId = currentInvoice?.id || null;
    
    // If not editing, reset document state
    if (!isEditMode) {
        currentInvoice = null;
        documentItems = [];
    }
    
    const today = new Date().toISOString().split('T')[0];
    const invoiceDate = invoiceData?.invoice_date ? new Date(invoiceData.invoice_date).toISOString().split('T')[0] : today;
    
    // Prepare buttons for top bar based on mode
    const topButtonsHtml = isEditMode ? `
        <div style="display: flex; gap: 0.5rem;">
            <button type="button" class="btn btn-primary" onclick="if(window.saveSalesInvoice) { const form = document.getElementById('salesInvoiceForm'); if(form) saveSalesInvoice({preventDefault:()=>{},target:form}); }">
                <i class="fas fa-save"></i> Update Invoice
            </button>
            <button type="button" class="btn btn-success" onclick="if(window.batchSalesInvoice) window.batchSalesInvoice('${invoiceId}')" title="Batch & Print">
                <i class="fas fa-check"></i> Batch & Print
            </button>
            <button type="button" class="btn btn-info" onclick="if(window.convertSalesInvoiceToQuotation) window.convertSalesInvoiceToQuotation('${invoiceId}')" title="Convert to Quotation">
                <i class="fas fa-exchange-alt"></i> Convert to Quotation
            </button>
            <button type="button" class="btn btn-danger" onclick="if(window.deleteSalesInvoice) window.deleteSalesInvoice('${invoiceId}')" title="Delete Invoice (Draft only)">
                <i class="fas fa-trash"></i> Delete
            </button>
            <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('invoices')">
                <i class="fas fa-arrow-left"></i> Back
            </button>
        </div>
    ` : `
        <button type="submit" class="btn btn-primary" form="salesInvoiceForm">
            <i class="fas fa-save"></i> Save Invoice
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('invoices')">
            <i class="fas fa-arrow-left"></i> Back to Invoices
        </button>
    `;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice-dollar"></i> ${isEditMode ? 'Edit' : 'Create'} Sales Invoice
                    ${isEditMode && invoiceData?.invoice_no ? `: ${invoiceData.invoice_no}` : ''}
                </h3>
                ${topButtonsHtml}
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <form id="salesInvoiceForm" onsubmit="saveSalesInvoice(event)">
                    <!-- Document Header -->
                    <div style="margin-bottom: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;">
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Date *</label>
                                <input type="date" class="form-input" name="invoice_date" 
                                       value="${invoiceDate}" required>
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Customer</label>
                                <input type="text" class="form-input" name="customer_name" 
                                       value="${invoiceData?.customer_name || ''}"
                                       placeholder="Customer name (optional)">
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Customer PIN</label>
                                <input type="text" class="form-input" name="customer_pin" 
                                       value="${invoiceData?.customer_pin || ''}"
                                       placeholder="Customer PIN (optional)">
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Customer Phone</label>
                                <input type="text" class="form-input" name="customer_phone" 
                                       id="customerPhoneInput"
                                       value="${invoiceData?.customer_phone || ''}"
                                       placeholder="Phone number (required for credit)">
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-top: 1rem;">
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Sales Type *</label>
                                <select class="form-select" name="sales_type" id="salesTypeSelect" onchange="handleSalesTypeChange()">
                                    <option value="RETAIL" ${invoiceData?.sales_type === 'RETAIL' || !invoiceData?.sales_type ? 'selected' : ''}>Retail (Customers)</option>
                                    <option value="WHOLESALE" ${invoiceData?.sales_type === 'WHOLESALE' ? 'selected' : ''}>Wholesale (Pharmacies)</option>
                                    <option value="SUPPLIER" ${invoiceData?.sales_type === 'SUPPLIER' ? 'selected' : ''}>Supplier</option>
                                </select>
                                <small style="color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.25rem; display: block;">
                                    <i class="fas fa-info-circle"></i> Units and prices follow mode: Retail = retail units, Wholesale = wholesale units, Supplier = supplier units (or wholesale if not set)
                                </small>
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Payment Mode *</label>
                                <select class="form-select" name="payment_mode" id="paymentModeSelect" onchange="handlePaymentModeChange()">
                                    <option value="cash" ${invoiceData?.payment_mode === 'cash' ? 'selected' : ''}>Cash</option>
                                    <option value="card" ${invoiceData?.payment_mode === 'card' ? 'selected' : ''}>Card</option>
                                    <option value="mpesa" ${invoiceData?.payment_mode === 'mpesa' ? 'selected' : ''}>M-Pesa</option>
                                    <option value="credit" ${invoiceData?.payment_mode === 'credit' ? 'selected' : ''}>Credit</option>
                                </select>
                                <small id="creditPaymentWarning" style="display: none; color: var(--danger-color); margin-top: 0.25rem;">
                                    <i class="fas fa-exclamation-triangle"></i> Credit payment requires customer name and phone number
                                </small>
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Notes</label>
                                <input type="text" class="form-input" name="notes" 
                                       placeholder="Additional notes">
                            </div>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table and Summary -->
                    <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem;">
                        <div>
                            <div id="salesInvoiceItemsContainer">
                                <!-- TransactionItemsTable component will render here -->
                            </div>
                        </div>
                        <div>
                            <div class="card" style="position: sticky; top: 1rem;">
                                <div class="card-header" style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                                    <h4 style="margin: 0; font-size: 1.1rem;">Invoice Summary</h4>
                                </div>
                                <div class="card-body" style="padding: 1rem;">
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                        <span style="font-weight: 500;">Net:</span>
                                        <strong id="invoiceSummaryNett">Ksh 0.00</strong>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                        <span style="font-weight: 500;">VAT:</span>
                                        <strong id="invoiceSummaryVat">Ksh 0.00</strong>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; padding-top: 0.75rem; border-top: 2px solid var(--border-color);">
                                        <span style="font-weight: 600; font-size: 1.1rem;">Total:</span>
                                        <strong id="invoiceSummaryTotal" style="font-size: 1.2rem; color: var(--primary-color);">Ksh 0.00</strong>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    ${!isEditMode ? `
                    <!-- Form Actions -->
                    <div style="display: flex; gap: 1rem; justify-content: flex-end; padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('invoices')">
                            Cancel
                        </button>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Sales Invoice
                        </button>
                    </div>
                    ` : ''}
                </form>
            </div>
        </div>
    `;
    
    // Initialize TransactionItemsTable component
    initializeSalesInvoiceItemsTable();
    
    // Set up payment mode change handler
    setTimeout(() => {
        handlePaymentModeChange();
    }, 100);
}

// Handle payment mode change - validate credit requirements
function handleSalesTypeChange() {
    const salesTypeSelect = document.getElementById('salesTypeSelect');
    if (!salesTypeSelect) return;
    
    const salesType = salesTypeSelect.value;
    // When sales type changes, prices should be recalculated
    // The TransactionItemsTable will fetch new prices when items are added/updated
    if (window.salesInvoiceItemsTable && typeof window.salesInvoiceItemsTable.refreshPrices === 'function') {
        window.salesInvoiceItemsTable.refreshPrices();
    }
}

function handlePaymentModeChange() {
    const paymentModeSelect = document.getElementById('paymentModeSelect');
    const customerNameInput = document.querySelector('input[name="customer_name"]');
    const customerPhoneInput = document.getElementById('customerPhoneInput');
    const warningEl = document.getElementById('creditPaymentWarning');
    
    if (!paymentModeSelect) return;
    
    const isCredit = paymentModeSelect.value === 'credit';
    
    if (isCredit) {
        // Make customer name and phone required
        if (customerNameInput) {
            customerNameInput.required = true;
            customerNameInput.style.borderColor = '';
        }
        if (customerPhoneInput) {
            customerPhoneInput.required = true;
            customerPhoneInput.style.borderColor = '';
        }
        if (warningEl) {
            warningEl.style.display = 'block';
        }
    } else {
        // Remove required attribute
        if (customerNameInput) {
            customerNameInput.required = false;
        }
        if (customerPhoneInput) {
            customerPhoneInput.required = false;
        }
        if (warningEl) {
            warningEl.style.display = 'none';
        }
    }
}

// Initialize TransactionItemsTable for Sales Invoice
let salesInvoiceItemsTable = null;

// Update sales invoice summary (Net, VAT, Total)
function updateSalesInvoiceSummary() {
    if (!salesInvoiceItemsTable) return;
    
    const summary = salesInvoiceItemsTable.calculateSummary();
    const nettEl = document.getElementById('invoiceSummaryNett');
    const vatEl = document.getElementById('invoiceSummaryVat');
    const totalEl = document.getElementById('invoiceSummaryTotal');
    
    if (nettEl) nettEl.textContent = formatCurrency(summary.nett);
    if (vatEl) vatEl.textContent = formatCurrency(summary.vat);
    if (totalEl) totalEl.textContent = formatCurrency(summary.total);
}

function initializeSalesInvoiceItemsTable() {
    const container = document.getElementById('salesInvoiceItemsContainer');
    if (!container) {
        setTimeout(initializeSalesInvoiceItemsTable, 100);
        return;
    }
    
    const items = documentItems.length > 0 
        ? documentItems.map(item => ({
            id: item.item_id,
            item_id: item.item_id,
            item_name: item.item_name,
            item_sku: item.item_sku,
            item_code: item.item_code || item.item_sku,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price: item.unit_price,
            total: item.total,
            is_empty: false
        }))
        : [];
    
    salesInvoiceItemsTable = new window.TransactionItemsTable({
        mountEl: container,
        mode: 'sale',
        items: items,
        priceType: 'sale_price',
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
                tax_percent: item.tax_percent || 0,
                total: item.total
            }));
            updateSalesInvoiceSummary();
        },
        onTotalChange: (total) => {
            console.log('Sales invoice total changed:', total);
            updateSalesInvoiceSummary();
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
    
    // Auto-focus on first item field after table is initialized
    setTimeout(() => {
        if (salesInvoiceItemsTable && typeof salesInvoiceItemsTable.autoFocusFirstItemField === 'function') {
            salesInvoiceItemsTable.autoFocusFirstItemField();
        }
    }, 150);
}

// Save Sales Invoice
async function saveSalesInvoice(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    // Check if we're in edit mode
    const isEditMode = currentInvoice && currentInvoice.mode === 'edit' && currentInvoice.id;
    
    // Get items from the component instance (more reliable than documentItems)
    let validItems = [];
    if (salesInvoiceItemsTable && typeof salesInvoiceItemsTable.getItems === 'function') {
        validItems = salesInvoiceItemsTable.getItems();
    } else {
        // Fallback to documentItems
        validItems = documentItems.filter(item => item.item_id && item.item_id !== null);
    }
    
    if (validItems.length === 0) {
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    // Validate credit payment mode requirements
    const paymentMode = formData.get('payment_mode') || 'cash';
    if (paymentMode === 'credit') {
        const customerName = formData.get('customer_name') || '';
        const customerPhone = formData.get('customer_phone') || '';
        
        if (!customerName || !customerName.trim()) {
            showToast('Customer name is required when payment mode is Credit', 'error');
            const nameInput = document.querySelector('input[name="customer_name"]');
            if (nameInput) {
                nameInput.focus();
                nameInput.style.borderColor = 'var(--danger-color)';
            }
            return;
        }
        
        if (!customerPhone || !customerPhone.trim()) {
            showToast('Customer phone number is required when payment mode is Credit', 'error');
            const phoneInput = document.getElementById('customerPhoneInput');
            if (phoneInput) {
                phoneInput.focus();
                phoneInput.style.borderColor = 'var(--danger-color)';
            }
            return;
        }
        
        // Basic phone validation
        const phoneDigits = customerPhone.replace(/\D/g, '');
        if (phoneDigits.length < 9) {
            showToast('Customer phone number must be valid (at least 9 digits)', 'error');
            const phoneInput = document.getElementById('customerPhoneInput');
            if (phoneInput) {
                phoneInput.focus();
                phoneInput.style.borderColor = 'var(--danger-color)';
            }
            return;
        }
    }
    
    if (isEditMode) {
        // Update existing invoice
        try {
            showToast('Updating invoice...', 'info');
            
            // Update invoice details
            await API.sales.updateInvoice(currentInvoice.id, {
                customer_name: formData.get('customer_name') || null,
                customer_pin: formData.get('customer_pin') || null,
                customer_phone: formData.get('customer_phone') || null,
                payment_mode: formData.get('payment_mode') || 'cash',
                payment_status: 'UNPAID'  // Keep as UNPAID for DRAFT
            });
            
            // Note: Items update would require deleting and recreating items
            // For now, we'll just update the header fields
            // TODO: Implement full item update if needed
            
            showToast('Invoice updated successfully', 'success');
            // Refresh the invoice view
            await viewSalesInvoice(currentInvoice.id);
        } catch (error) {
            console.error('Error updating sales invoice:', error);
            showToast(error.message || 'Error updating sales invoice', 'error');
        }
    } else {
        // Create new invoice
        const invoiceData = {
            company_id: CONFIG.COMPANY_ID,
            branch_id: CONFIG.BRANCH_ID,
            invoice_date: formData.get('invoice_date'),
        customer_name: formData.get('customer_name') || null,
        customer_pin: formData.get('customer_pin') || null,
        customer_phone: formData.get('customer_phone') || null,
        payment_mode: formData.get('payment_mode') || 'cash',
        sales_type: formData.get('sales_type') || 'RETAIL',
            payment_status: 'UNPAID',  // Always start as UNPAID (will be PAID after payment collection)
            status: 'DRAFT',  // Save as DRAFT (will be BATCHED when committed)
            discount_amount: 0,  // TODO: Add discount field if needed
            items: validItems.map(item => ({
                item_id: item.item_id,
                unit_name: item.unit_name,
                quantity: item.quantity,
                unit_price_exclusive: item.unit_price,
                discount_percent: item.discount_percent || 0,
                discount_amount: item.discount_amount || 0
            })),
            created_by: CONFIG.USER_ID
        };
        
        try {
            showToast('Creating invoice...', 'info');
            const invoice = await API.sales.createInvoice(invoiceData);
            showToast('Sales invoice created as DRAFT. Batch it to reduce stock.', 'success');
            loadSalesSubPage('invoices');
        } catch (error) {
            console.error('Error creating sales invoice:', error);
            showToast(error.message || 'Error creating sales invoice', 'error');
        }
    }
}

// =====================================================
// CREATE QUOTATION PAGE
// =====================================================

async function renderCreateSalesQuotationPage() {
    console.log('renderCreateSalesQuotationPage() called');
    const page = document.getElementById('sales');
    if (!page) return;
    
    // Check if we're in edit mode
    const isEditMode = currentQuotation && currentQuotation.mode === 'edit' && currentQuotation.id;
    let quotationData = isEditMode ? currentQuotation.quotationData : null;
    const quotationId = currentQuotation?.id || null;
    const quotationStatus = quotationData?.status || 'draft';
    const canEdit = quotationStatus === 'draft';
    
    // If not editing, reset quotation state
    if (!isEditMode) {
        currentQuotation = null;
        quotationItems = [];
    }
    
    const today = new Date().toISOString().split('T')[0];
    const validUntil = new Date();
    validUntil.setDate(validUntil.getDate() + 30); // Default 30 days validity
    const validUntilStr = validUntil.toISOString().split('T')[0];
    
    // Prepare buttons for top bar based on mode and status
    const topButtonsHtml = isEditMode ? `
        ${canEdit ? `
            <button type="button" class="btn btn-primary btn-save-quotation" onclick="if(window.updateSalesQuotation) { const form = document.getElementById('salesQuotationForm'); if(form) updateSalesQuotation({preventDefault:()=>{},target:form}, '${quotationId}'); }">
                <i class="fas fa-save"></i> Update Quotation
            </button>
            <button type="button" class="btn btn-outline btn-danger" onclick="if(window.deleteQuotation) window.deleteQuotation('${quotationId}')" title="Delete Quotation (Only for draft)">
                <i class="fas fa-trash"></i> Delete
            </button>
        ` : `
            <button type="button" class="btn btn-outline btn-danger" disabled title="Cannot delete quotation with status ${quotationStatus}">
                <i class="fas fa-trash"></i> Delete (Disabled)
            </button>
            <span style="color: var(--text-secondary); font-size: 0.875rem; align-self: center; margin-left: 0.5rem;">
                Quotation is ${quotationStatus} - cannot be edited or deleted
            </span>
        `}
        <button type="button" class="btn btn-outline" onclick="if(window.printQuotation) window.printQuotation('${quotationId}')" title="Print">
            <i class="fas fa-print"></i> Print
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('quotations')">
            <i class="fas fa-arrow-left"></i> Back
        </button>
    ` : `
        <button type="submit" class="btn btn-primary" form="salesQuotationForm">
            <i class="fas fa-save"></i> Save Quotation
        </button>
        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('quotations')">
            <i class="fas fa-arrow-left"></i> Back
        </button>
    `;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice"></i> ${isEditMode ? 'Edit' : 'Create'} Quotation
                    ${isEditMode && quotationData?.quotation_no ? `: ${quotationData.quotation_no}` : ''}
                </h3>
                <div style="display: flex; gap: 0.5rem;">
                    ${topButtonsHtml}
                </div>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <form id="salesQuotationForm" ${isEditMode ? '' : 'onsubmit="saveSalesQuotation(event)"'}>
                    <!-- Document Header -->
                    <div style="margin-bottom: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;">
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Date *</label>
                                <input type="date" class="form-input" name="quotation_date" 
                                       value="${quotationData?.quotation_date ? new Date(quotationData.quotation_date).toISOString().split('T')[0] : today}" required>
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Customer</label>
                                <input type="text" class="form-input" name="customer_name" 
                                       value="${quotationData?.customer_name || ''}"
                                       placeholder="Customer name (optional)">
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Reference</label>
                                <input type="text" class="form-input" name="reference" 
                                       value="${quotationData?.reference || ''}"
                                       placeholder="Reference number">
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-top: 1rem;">
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Valid Until</label>
                                <input type="date" class="form-input" name="valid_until" 
                                       value="${quotationData?.valid_until ? new Date(quotationData.valid_until).toISOString().split('T')[0] : validUntilStr}">
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Notes</label>
                                <input type="text" class="form-input" name="notes" 
                                       value="${quotationData?.notes || ''}"
                                       placeholder="Additional notes">
                            </div>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table and Summary -->
                    <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem;">
                        <div>
                            <div id="salesQuotationItemsContainer">
                                <!-- TransactionItemsTable component will render here -->
                            </div>
                        </div>
                        <div>
                            <div class="card" style="position: sticky; top: 1rem;">
                                <div class="card-header" style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                                    <h4 style="margin: 0; font-size: 1.1rem;">Quotation Summary</h4>
                                </div>
                                <div class="card-body" style="padding: 1rem;">
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                        <span style="font-weight: 500;">Net:</span>
                                        <strong id="quotationSummaryNett">Ksh 0.00</strong>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                        <span style="font-weight: 500;">VAT:</span>
                                        <strong id="quotationSummaryVat">Ksh 0.00</strong>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; padding-top: 0.75rem; border-top: 2px solid var(--border-color);">
                                        <span style="font-weight: 600; font-size: 1.1rem;">Total:</span>
                                        <strong id="quotationSummaryTotal" style="font-size: 1.2rem; color: var(--primary-color);">Ksh 0.00</strong>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Form Actions -->
                    <div style="display: flex; gap: 1rem; justify-content: flex-end; padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <button type="button" class="btn btn-outline" onclick="if(window.addQuotationItemsToOrderBook) window.addQuotationItemsToOrderBook()" title="Add all quotation items to Order Book">
                            <i class="fas fa-clipboard-list"></i> Add to Order Book
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('quotations')">
                            Cancel
                        </button>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Quotation
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize TransactionItemsTable component for quotations (mode: 'quotation' - no stock validation)
    initializeSalesQuotationItemsTable();
    
    // If in edit mode, populate items after table is initialized
    if (isEditMode && quotationData && quotationData.items && quotationData.items.length > 0) {
        setTimeout(() => {
            // Map quotation items to component format
            quotationItems = quotationData.items.map(item => ({
                item_id: item.item_id,
                item_name: item.item_name || item.item?.name || '',
                item_sku: item.item_code || item.item?.sku || '',
                item_code: item.item_code || item.item?.sku || '',
                unit_name: item.unit_name,
                quantity: item.quantity,
                unit_price: item.unit_price_exclusive || 0,
                purchase_price: item.unit_cost_used != null ? parseFloat(item.unit_cost_used) : null,
                discount_percent: item.discount_percent || 0,
                total: item.line_total_inclusive || 0,
                is_empty: false
            }));
            
            // Update TransactionItemsTable with items
            if (salesQuotationItemsTable && quotationItems.length > 0) {
                salesQuotationItemsTable.items = salesQuotationItemsTable.normalizeItems(quotationItems);
                salesQuotationItemsTable.render();
                salesQuotationItemsTable.attachEventListeners();
                updateSalesQuotationSummary();
            }
        }, 300);
    }
    
    // Set form submit handler for edit mode
    if (isEditMode && quotationId) {
        setTimeout(() => {
            const form = document.getElementById('salesQuotationForm');
            if (form) {
                form.onsubmit = (e) => {
                    e.preventDefault();
                    updateSalesQuotation(e, quotationId);
                };
            }
        }, 100);
    }
}

// Initialize TransactionItemsTable for Sales Quotation
let salesQuotationItemsTable = null;

function initializeSalesQuotationItemsTable() {
    const container = document.getElementById('salesQuotationItemsContainer');
    if (!container) {
        console.error('salesQuotationItemsContainer not found');
        return;
    }
    
    salesQuotationItemsTable = new TransactionItemsTable({
        mountEl: container,
        mode: 'quotation', // Quotations don't affect stock, so no stock validation
        items: quotationItems.length > 0 ? quotationItems : [],
        onItemsChange: (validItems) => {
            // Update quotationItems
            quotationItems = validItems.map(item => ({
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
            
            updateSalesQuotationSummary();
            
            // Auto-save when items change (if in edit mode and quotation is draft)
            if (currentQuotation && currentQuotation.id && currentQuotation.quotationData?.status === 'draft') {
                // Debounce auto-save to avoid too many requests
                clearTimeout(window.autoSaveQuotationTimeout);
                window.autoSaveQuotationTimeout = setTimeout(() => {
                    autoSaveQuotation();
                }, 2000); // Auto-save 2 seconds after last change
            }
        },
        onTotalChange: () => {
            updateSalesQuotationSummary();
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
    
    // Auto-focus on first item field after table is initialized
    setTimeout(() => {
        if (salesQuotationItemsTable && typeof salesQuotationItemsTable.autoFocusFirstItemField === 'function') {
            salesQuotationItemsTable.autoFocusFirstItemField();
        }
    }, 150);
}

// Update sales quotation summary (Net, VAT, Total)
function updateSalesQuotationSummary() {
    if (!salesQuotationItemsTable) return;
    
    const summary = salesQuotationItemsTable.calculateSummary();
    const nettEl = document.getElementById('quotationSummaryNett');
    const vatEl = document.getElementById('quotationSummaryVat');
    const totalEl = document.getElementById('quotationSummaryTotal');
    
    if (nettEl) nettEl.textContent = formatCurrency(summary.nett);
    if (vatEl) vatEl.textContent = formatCurrency(summary.vat);
    if (totalEl) totalEl.textContent = formatCurrency(summary.total);
}

async function saveSalesQuotation(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    // Get items from the component instance
    let validItems = [];
    if (salesQuotationItemsTable && typeof salesQuotationItemsTable.getItems === 'function') {
        validItems = salesQuotationItemsTable.getItems();
    }
    
    if (validItems.length === 0) {
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    const quotationData = {
        company_id: CONFIG.COMPANY_ID,
        branch_id: CONFIG.BRANCH_ID,
        quotation_date: formData.get('quotation_date'),
        customer_name: formData.get('customer_name') || null,
        customer_pin: formData.get('customer_pin') || null,
        reference: formData.get('reference') || null,
        notes: formData.get('notes') || null,
        status: 'draft',
        valid_until: formData.get('valid_until') || null,
        discount_amount: 0, // Can be added later if needed
        items: validItems.map(item => ({
            item_id: item.item_id,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price_exclusive: item.unit_price,
            discount_percent: item.discount_percent || 0
        })),
        created_by: CONFIG.USER_ID
    };
    
    try {
        const quotation = await API.quotations.create(quotationData);
        showToast('Quotation created successfully!', 'success');
        loadSalesSubPage('quotations');
    } catch (error) {
        console.error('Error creating quotation:', error);
        showToast(error.message || 'Error creating quotation', 'error');
    }
}

// Update Sales Quotation
async function updateSalesQuotation(event, quotationId) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    // Get items from the component instance
    let validItems = [];
    if (salesQuotationItemsTable && typeof salesQuotationItemsTable.getItems === 'function') {
        validItems = salesQuotationItemsTable.getItems();
    }
    
    if (validItems.length === 0) {
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    // QuotationUpdate schema expects optional fields and items
    const quotationUpdateData = {
        customer_name: formData.get('customer_name') || null,
        customer_pin: formData.get('customer_pin') || null,
        reference: formData.get('reference') || null,
        notes: formData.get('notes') || null,
        status: 'draft',
        valid_until: formData.get('valid_until') || null,
        discount_amount: 0,
        items: validItems.map(item => ({
            item_id: item.item_id,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price_exclusive: item.unit_price,
            discount_percent: item.discount_percent || 0
        }))
    };
    
    try {
        const updatedQuotation = await API.quotations.update(quotationId, quotationUpdateData);
        showToast('Quotation updated successfully!', 'success');
        loadSalesSubPage('quotations');
    } catch (error) {
        console.error('Error updating quotation:', error);
        showToast(error.message || 'Error updating quotation', 'error');
    }
}

// Auto-save quotation when changes occur
async function autoSaveQuotation() {
    if (!currentQuotation || !currentQuotation.id) {
        return;
    }
    
    if (currentQuotation.quotationData?.status !== 'draft') {
        return; // Only auto-save draft quotations
    }
    
    const form = document.getElementById('salesQuotationForm');
    if (!form) {
        return;
    }
    
    const formData = new FormData(form);
    const items = salesQuotationItemsTable ? salesQuotationItemsTable.getItems() : [];
    
    if (items.length === 0) {
        return; // Don't auto-save empty quotations
    }
    
    try {
        const quotationUpdateData = {
            customer_name: formData.get('customer_name') || null,
            customer_pin: formData.get('customer_pin') || null,
            reference: formData.get('reference') || null,
            notes: formData.get('notes') || null,
            status: 'draft',
            valid_until: formData.get('valid_until') || null,
            discount_amount: 0,
            items: items.map(item => ({
                item_id: item.item_id,
                unit_name: item.unit_name,
                quantity: item.quantity,
                unit_price_exclusive: item.unit_price,
                discount_percent: item.discount_percent || 0
            }))
        };
        
        await API.quotations.update(currentQuotation.id, quotationUpdateData);
        console.log('✅ [Auto-save] Quotation updated automatically');
        // Don't show toast for auto-save to avoid annoying the user
    } catch (error) {
        console.error('❌ [Auto-save] Error auto-saving quotation:', error);
        // Don't show error toast for auto-save failures
    }
}

// Date filter functions
function applySalesDateFilter() {
    fetchAndRenderSalesInvoicesData();
}

function clearSalesDateFilter() {
    const today = new Date().toISOString().split('T')[0];
    const dateFromInput = document.getElementById('filterDateFrom');
    const dateToInput = document.getElementById('filterDateTo');
    if (dateFromInput) dateFromInput.value = today;
    if (dateToInput) dateToInput.value = today;
    applySalesDateFilter();
}

function filterSalesInvoices() {
    renderSalesInvoicesTableBody();
}

// View Sales Invoice (READ-ONLY - KRA Compliant)
async function viewSalesInvoice(invoiceId) {
    try {
        const invoice = await API.sales.getInvoice(invoiceId);
        const status = invoice.status || 'DRAFT';
        const isDraft = status === 'DRAFT';
        
        if (isDraft) {
            // For DRAFT invoices, navigate to edit page (same as create page)
            currentInvoice = { 
                id: invoiceId, 
                mode: 'edit',
                invoiceData: invoice  // Store invoice data to populate form
            };
            
            // Convert invoice items to documentItems format
            documentItems = invoice.items ? invoice.items.map(item => ({
                item_id: item.item_id,
                item_name: item.item_name || item.item?.name || '',
                item_code: item.item_code || item.item?.sku || '',
                item_sku: item.item_code || item.item?.sku || '',
                unit_name: item.unit_name,
                quantity: parseFloat(item.quantity) || 0,
                unit_price: parseFloat(item.unit_price_exclusive) || 0,
                discount_percent: parseFloat(item.discount_percent) || 0,
                discount_amount: parseFloat(item.discount_amount) || 0,
                total: parseFloat(item.line_total_inclusive) || 0,
                is_empty: false
            })) : [];
            
            // Navigate to create page (will load as edit mode)
            await loadSalesSubPage('create-invoice');
            return;
        }
        
        // For BATCHED/PAID invoices, show read-only view
        const page = document.getElementById('sales');
        if (!page) return;
        
        const invoiceDate = new Date(invoice.invoice_date).toLocaleDateString();
        const statusBadge = getSalesInvoiceStatusBadge(status);
        const paymentStatusBadge = getPaymentStatusBadge(invoice.payment_status || 'UNPAID');
        
        // Determine which buttons to show
        const showPrint = status === 'BATCHED' || status === 'PAID';
        const showPayment = status === 'BATCHED' && invoice.payment_status !== 'PAID';
        
        page.innerHTML = `
            <div class="card">
                <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                    <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                        <i class="fas fa-file-invoice-dollar"></i> Sales Invoice: ${invoice.invoice_no}
                        <span style="margin-left: 0.5rem;">${statusBadge}</span>
                        <span style="margin-left: 0.5rem;">${paymentStatusBadge}</span>
                    </h3>
                    <div style="display: flex; gap: 0.5rem;">
                        ${showPayment ? `
                            <button type="button" class="btn btn-success" onclick="if(window.collectPayment) window.collectPayment('${invoiceId}')" title="Collect Payment">
                                <i class="fas fa-money-bill-wave"></i> Collect Payment
                            </button>
                        ` : ''}
                        ${showPrint ? `
                            <button type="button" class="btn btn-outline" onclick="if(window.printSalesInvoice) window.printSalesInvoice('${invoiceId}')" title="Print">
                                <i class="fas fa-print"></i> Print
                            </button>
                        ` : ''}
                        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('invoices')">
                            <i class="fas fa-arrow-left"></i> Back
                        </button>
                    </div>
                </div>
                
                <div class="card-body" style="padding: 1.5rem;">
                    <!-- Invoice Details -->
                    <div class="card" style="margin-bottom: 1.5rem;">
                        <div class="card-header">
                            <h4>Invoice Details</h4>
                        </div>
                        <div class="card-body">
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">Invoice Number</label>
                                    <input type="text" class="form-input" value="${invoice.invoice_no}" readonly>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Date</label>
                                    <input type="text" class="form-input" value="${invoiceDate}" readonly>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Customer</label>
                                    <input type="text" class="form-input" value="${invoice.customer_name || '—'}" readonly>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">Payment Mode</label>
                                    <input type="text" class="form-input" value="${invoice.payment_mode || '—'}" readonly>
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Payment Status</label>
                                    <input type="text" class="form-input" value="${invoice.payment_status || '—'}" readonly>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Items Table -->
                    <div class="card" style="margin-bottom: 1.5rem;">
                        <div class="card-header">
                            <h4>Items</h4>
                        </div>
                        <div class="card-body">
                            <table style="width: 100%; border-collapse: collapse;">
                                <thead>
                                    <tr style="border-bottom: 2px solid var(--border-color);">
                                        <th style="padding: 0.75rem; text-align: left;">Item</th>
                                        <th style="padding: 0.75rem; text-align: right;">Qty</th>
                                        <th style="padding: 0.75rem; text-align: right;">Unit Price</th>
                                        <th style="padding: 0.75rem; text-align: right;">VAT</th>
                                        <th style="padding: 0.75rem; text-align: right;">Total</th>
                                        <th style="padding: 0.75rem; text-align: center;">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${invoice.items && invoice.items.length > 0 ? invoice.items.map(item => {
                                        const itemName = item.item_name || item.item?.name || 'Item';
                                        const itemCode = item.item_code || item.item?.sku || '';
                                        const itemId = item.item_id;
                                        const itemDisplay = itemCode 
                                            ? `${escapeHtml(itemName)} <small style="color: var(--text-secondary);">(${escapeHtml(itemCode)})</small>`
                                            : escapeHtml(itemName);
                                        return `
                                        <tr style="border-bottom: 1px solid var(--border-color);">
                                            <td style="padding: 0.75rem;">
                                                <div>
                                                    <strong>${itemDisplay}</strong>
                                                    <div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.25rem;">
                                                        Unit: ${escapeHtml(item.unit_name)}
                                                    </div>
                                                </div>
                                            </td>
                                            <td style="padding: 0.75rem; text-align: right;">${parseFloat(item.quantity).toFixed(4)} ${escapeHtml(item.unit_name)}</td>
                                            <td style="padding: 0.75rem; text-align: right;">${formatCurrency(item.unit_price_exclusive || 0)}</td>
                                            <td style="padding: 0.75rem; text-align: right;">${formatCurrency(item.vat_amount || 0)}</td>
                                            <td style="padding: 0.75rem; text-align: right;"><strong>${formatCurrency(item.line_total_inclusive || 0)}</strong></td>
                                            <td style="padding: 0.75rem; text-align: center;">
                                                <button class="btn btn-outline btn-sm" 
                                                        onclick="if(window.addItemToOrderBookFromSale) window.addItemToOrderBookFromSale('${itemId}', '${escapeHtml(itemName)}', '${escapeHtml(item.unit_name)}', '${invoiceId}')" 
                                                        title="Add to Order Book">
                                                    <i class="fas fa-clipboard-list"></i> Add to Order Book
                                                </button>
                                            </td>
                                        </tr>
                                    `;
                                    }).join('') : '<tr><td colspan="6" style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items</td></tr>'}
                                </tbody>
                                <tfoot>
                                    <tr style="border-top: 2px solid var(--border-color);">
                                        <td colspan="5" style="padding: 0.75rem; text-align: right; font-weight: 600;">Total:</td>
                                        <td style="padding: 0.75rem; text-align: right; font-weight: 600; font-size: 1.1rem;">${formatCurrency(invoice.total_inclusive || 0)}</td>
                                    </tr>
                                </tfoot>
                            </table>
                        </div>
                    </div>
                    
                    <div style="padding: 1rem; background: #f8f9fa; border-radius: 0.5rem; color: var(--text-secondary); font-size: 0.875rem;">
                        <i class="fas fa-info-circle"></i> 
                        ${invoice.status === 'DRAFT' 
                            ? 'This invoice is in DRAFT status and can be edited or deleted. Batch it to reduce stock.'
                            : invoice.status === 'BATCHED' && invoice.payment_status !== 'PAID'
                            ? 'This invoice is BATCHED and ready for payment collection. Stock has been reduced.'
                            : invoice.status === 'PAID'
                            ? 'This invoice is PAID and KRA compliant. It cannot be edited or deleted.'
                            : 'This invoice is KRA compliant and cannot be edited or deleted after creation.'}
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('Error loading sales invoice:', error);
        showToast(error.message || 'Error loading invoice', 'error');
    }
}

// POS Functions (existing)
let searchTimeout;
let allItems = [];

async function searchItems(event) {
    const query = event.target.value.trim();
    
    if (query.length < 2) {
        document.getElementById('itemsList').innerHTML = 
            '<p class="text-center">Type at least 2 characters to search</p>';
        return;
    }
    
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            // OPTIMIZED: Use API search with caching
            if (!CONFIG || !CONFIG.COMPANY_ID || !window.API) {
                document.getElementById('itemsList').innerHTML = 
                    '<p class="text-center" style="color: var(--danger-color);">Configuration error. Please set Company ID in Settings.</p>';
                return;
            }
            
            // Check cache first
            const cache = window.searchCache || null;
            let items = null;
            
            if (cache) {
                items = cache.get(query, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, 20);
            }
            
            if (!items) {
                // OPTIMIZED: Don't include pricing for faster search
                items = await API.items.search(query, CONFIG.COMPANY_ID, 20, CONFIG.BRANCH_ID || null, false);
                
                // Cache the results
                if (cache && items) {
                    cache.set(query, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, 20, items);
                }
            }
            
            renderItemsList(items);
        } catch (error) {
            console.error('Error searching items:', error);
            document.getElementById('itemsList').innerHTML = 
                `<p class="text-center" style="color: var(--danger-color);">Error: ${error.message || 'Search failed'}</p>`;
        }
    }, 150); // OPTIMIZED: Reduced debounce from 300ms to 150ms
}

function renderItemsList(items) {
    const container = document.getElementById('itemsList');
    if (!container) return;
    
    if (items.length === 0) {
        container.innerHTML = '<p class="text-center">No items found</p>';
        return;
    }
    
    container.innerHTML = items.map(item => `
        <div class="card" style="margin-bottom: 0.5rem; cursor: pointer;" onclick="addToCart('${item.id}')">
            <div class="flex-between">
                <div>
                    <strong>${item.name}</strong>
                    <p style="margin: 0.25rem 0; color: var(--text-secondary); font-size: 0.875rem;">
                        ${item.sku || ''} | ${item.base_unit || ''} | ${item.category || 'Uncategorized'}
                    </p>
                </div>
                <button class="btn btn-primary">
                    <i class="fas fa-plus"></i> Add
                </button>
            </div>
        </div>
    `).join('');
}

async function addToCart(itemId) {
    // Find item in allItems or fetch it
    let item = allItems.find(i => i.id === itemId);
    
    if (!item) {
        try {
            item = await API.items.get(itemId);
            allItems.push(item);
        } catch (error) {
            console.error('Error getting item:', error);
            showToast('Error loading item details', 'error');
            return;
        }
    }
    
    // Get stock availability
    try {
        const availability = await API.inventory.getAvailability(itemId, CONFIG.BRANCH_ID);
        
        if (availability.total_base_units <= 0) {
            showToast('Item out of stock', 'warning');
            return;
        }
        
        const salesTypeSelect = document.getElementById('salesTypeSelect');
        const salesType = (salesTypeSelect && salesTypeSelect.value) ? salesTypeSelect.value : 'RETAIL';
        const tier = salesType.toLowerCase();
        const wups = Math.max(0.0001, parseFloat(item.wholesale_units_per_supplier) || 1);
        const packSize = Math.max(1, parseInt(item.pack_size, 10) || 1);
        const baseQty = availability.total_base_units;
        let unitForTier = item.base_unit || 'piece';
        let displayQty = baseQty;
        if (salesType === 'WHOLESALE') {
            unitForTier = item.wholesale_unit || item.base_unit || 'piece';
            displayQty = baseQty;
        } else if (salesType === 'RETAIL') {
            unitForTier = item.retail_unit || item.base_unit || 'piece';
            displayQty = baseQty * packSize;
        } else if (salesType === 'SUPPLIER') {
            if (wups > 1 && item.supplier_unit) {
                unitForTier = item.supplier_unit;
                displayQty = Math.floor(baseQty / wups);
            } else {
                unitForTier = item.wholesale_unit || item.base_unit || 'piece';
                displayQty = baseQty;
            }
        }
        
        const priceInfo = await API.items.getRecommendedPrice(
            itemId, CONFIG.BRANCH_ID, CONFIG.COMPANY_ID, unitForTier, tier
        );
        
        showAddToCartModal(item, availability, priceInfo, { salesType, unitForTier, displayQty });
    } catch (error) {
        console.error('Error getting item details:', error);
        showToast('Error loading item details', 'error');
    }
}

function showAddToCartModal(item, availability, priceInfo, tierInfo) {
    tierInfo = tierInfo || {};
    const salesType = tierInfo.salesType || 'RETAIL';
    const unitForTier = tierInfo.unitForTier || (item.wholesale_unit || item.base_unit || 'piece');
    const displayQty = tierInfo.displayQty != null ? tierInfo.displayQty : (availability.total_base_units || 0);
    const unitOptions = `<option value="${unitForTier}">${unitForTier} (${displayQty} available)</option>`;
    
    const content = `
        <form id="addToCartForm" onsubmit="confirmAddToCart(event, '${item.id}')">
            <div class="form-group">
                <label class="form-label">Item</label>
                <input type="text" class="form-input" value="${item.name}" disabled>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Unit (${salesType})</label>
                    <select class="form-select" name="unit_name" id="cartUnitSelect" required>
                        ${unitOptions}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Quantity</label>
                    <input type="number" class="form-input" name="quantity" 
                           min="0.01" step="0.01" value="1" required 
                           onchange="updateCartPrice('${item.id}')">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Unit Price</label>
                <input type="number" class="form-input" name="unit_price" 
                       id="cartUnitPrice" step="0.01" min="0" 
                       value="${priceInfo?.recommended_unit_price || 0}" required
                       onchange="updateCartPrice('${item.id}')">
                <small style="color: var(--text-secondary);">
                    Recommended: ${formatCurrency(priceInfo?.recommended_unit_price || 0)}
                    ${priceInfo?.margin_percent ? `(Margin: ${priceInfo.margin_percent.toFixed(1)}%)` : ''}
                </small>
            </div>
            <div class="form-group">
                <label class="form-label">Discount (%)</label>
                <input type="number" class="form-input" name="discount_percent" 
                       value="0" min="0" max="100" step="0.01"
                       onchange="updateCartPrice('${item.id}')">
            </div>
            <div id="cartItemTotal" style="padding: 1rem; background: var(--bg-color); border-radius: 0.5rem;">
                <strong>Total: ${formatCurrency(priceInfo?.recommended_unit_price || 0)}</strong>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="addToCartForm">Add to Cart</button>
    `;
    
    showModal('Add to Cart', content, footer);
}

function updateCartPrice(itemId) {
    const quantity = parseFloat(document.querySelector('[name="quantity"]').value) || 0;
    const unitPrice = parseFloat(document.querySelector('[name="unit_price"]').value) || 0;
    const discountPercent = parseFloat(document.querySelector('[name="discount_percent"]').value) || 0;
    
    const subtotal = quantity * unitPrice;
    const discount = subtotal * (discountPercent / 100);
    const total = subtotal - discount;
    
    document.getElementById('cartItemTotal').innerHTML = `
        <strong>Total: ${formatCurrency(total)}</strong>
        ${discount > 0 ? `<br><small>Discount: ${formatCurrency(discount)}</small>` : ''}
    `;
}

function confirmAddToCart(event, itemId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const item = allItems.find(i => i.id === itemId);
    const quantity = parseFloat(formData.get('quantity'));
    const unitPrice = parseFloat(formData.get('unit_price'));
    const discountPercent = parseFloat(formData.get('discount_percent') || 0);
    
    const subtotal = quantity * unitPrice;
    const discount = subtotal * (discountPercent / 100);
    const lineTotal = subtotal - discount;
    
    cart.push({
        item_id: itemId,
        item_name: item.name,
        unit_name: formData.get('unit_name'),
        quantity: quantity,
        unit_price_exclusive: unitPrice,
        discount_percent: discountPercent,
        discount_amount: discount,
        line_total: lineTotal
    });
    
    renderCart();
    closeModal();
    showToast('Item added to cart', 'success');
}

function renderCart() {
    const container = document.getElementById('cartItems');
    const summary = document.getElementById('cartSummary');
    const checkoutBtn = document.getElementById('checkoutBtn');
    
    if (!container) return;
    
    if (cart.length === 0) {
        container.innerHTML = '<p class="text-center">Cart is empty</p>';
        if (summary) summary.innerHTML = '';
        if (checkoutBtn) checkoutBtn.disabled = true;
        return;
    }
    
    container.innerHTML = cart.map((item, index) => `
        <div class="flex-between" style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
            <div>
                <strong>${item.item_name}</strong>
                <p style="margin: 0.25rem 0; font-size: 0.875rem; color: var(--text-secondary);">
                    ${item.quantity} ${item.unit_name} × ${formatCurrency(item.unit_price_exclusive)}
                    ${item.discount_percent > 0 ? ` (${item.discount_percent}% off)` : ''}
                </p>
            </div>
            <div class="text-right">
                <strong>${formatCurrency(item.line_total)}</strong>
                <button class="btn btn-danger" style="padding: 0.25rem 0.5rem; margin-top: 0.5rem;" 
                        onclick="removeFromCart(${index})">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `).join('');
    
    const subtotal = cart.reduce((sum, item) => sum + item.line_total, 0);
    const vat = calculateVAT(subtotal);
    const total = subtotal + vat;
    
    if (summary) {
        summary.innerHTML = `
            <div class="flex-between mb-1">
                <span>Subtotal:</span>
                <strong>${formatCurrency(subtotal)}</strong>
            </div>
            <div class="flex-between mb-1">
                <span>VAT (${CONFIG.VAT_RATE}%):</span>
                <strong>${formatCurrency(vat)}</strong>
            </div>
            <div class="flex-between" style="padding-top: 0.5rem; border-top: 1px solid var(--border-color);">
                <span><strong>Total:</strong></span>
                <strong style="font-size: 1.25rem;">${formatCurrency(total)}</strong>
            </div>
        `;
    }
    
    if (checkoutBtn) checkoutBtn.disabled = false;
}

function removeFromCart(index) {
    cart.splice(index, 1);
    renderCart();
}

async function processSale() {
    if (cart.length === 0) {
        showToast('Cart is empty', 'warning');
        return;
    }
    
    if (!CONFIG.USER_ID) {
        showToast('User ID not configured', 'error');
        return;
    }
    
    const invoiceData = {
        company_id: CONFIG.COMPANY_ID,
        branch_id: CONFIG.BRANCH_ID,
        invoice_date: new Date().toISOString().split('T')[0],
        payment_mode: 'cash',
        payment_status: 'PAID',
        sales_type: 'RETAIL',  // POS defaults to retail
        discount_amount: 0,
        items: cart.map(item => ({
            item_id: item.item_id,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_price_exclusive: item.unit_price_exclusive,
            discount_percent: item.discount_percent,
            discount_amount: item.discount_amount
        })),
        created_by: CONFIG.USER_ID
    };
    
    try {
        const invoice = await API.sales.createInvoice(invoiceData);
        showToast('Sale processed successfully!', 'success');
        cart = [];
        renderCart();
        const itemSearch = document.getElementById('itemSearch');
        if (itemSearch) itemSearch.value = '';
        const itemsList = document.getElementById('itemsList');
        if (itemsList) itemsList.innerHTML = '<p class="text-center">Search for items to add to cart</p>';
        
        // Show invoice details
        showInvoiceDetails(invoice);
    } catch (error) {
        console.error('Error processing sale:', error);
        showToast(error.message || 'Error processing sale', 'error');
    }
}

function showInvoiceDetails(invoice) {
    const content = `
        <div>
            <h4>Invoice #${invoice.invoice_no || invoice.id.substring(0, 8)}</h4>
            <p><strong>Date:</strong> ${formatDate(invoice.invoice_date)}</p>
            <p><strong>Total:</strong> ${formatCurrency(invoice.total_inclusive || invoice.total || 0)}</p>
            <p><strong>Payment:</strong> ${invoice.payment_mode}</p>
        </div>
    `;
    
    showModal('Sale Complete', content, '<button class="btn btn-primary" onclick="closeModal()">OK</button>');
}

// =====================================================
// SALES INVOICE ACTIONS (BATCH, DELETE, PAYMENT)
// =====================================================

async function batchSalesInvoice(invoiceId) {
    if (!confirm('Batch this invoice? This will reduce stock from inventory and make it ready for payment collection.')) {
        return;
    }
    
    try {
        showToast('Batching invoice...', 'info');
        const userId = CONFIG.USER_ID;
        if (!userId) {
            throw new Error('User ID not found. Please log in again.');
        }
        
        const invoice = await API.sales.batchInvoice(invoiceId, userId);
        showToast('Invoice batched successfully! Stock has been reduced.', 'success');
        
        // Refresh the invoices list
        await fetchAndRenderSalesInvoicesData();
        
        // Optionally print receipt
        if (confirm('Print thermal receipt?')) {
            await printSalesInvoice(invoiceId);
        }
    } catch (error) {
        console.error('Error batching invoice:', error);
        const errorMsg = error.message || 'Failed to batch invoice';
        showToast(errorMsg, 'error');
    }
}

async function deleteSalesInvoice(invoiceId) {
    // First check if invoice is DRAFT
    try {
        const invoice = await API.sales.getInvoice(invoiceId);
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
        showToast('Deleting invoice...', 'info');
        await API.sales.deleteInvoice(invoiceId);
        showToast('Invoice deleted successfully', 'success');
        
        // Clear current invoice if we're editing it
        if (currentInvoice && currentInvoice.id === invoiceId) {
            currentInvoice = null;
            documentItems = [];
        }
        
        // Navigate back to invoices list
        await loadSalesSubPage('invoices');
    } catch (error) {
        console.error('Error deleting invoice:', error);
        const errorMsg = error.message || 'Failed to delete invoice';
        showToast(errorMsg, 'error');
    }
}

async function collectPayment(invoiceId) {
    try {
        // Load invoice details
        const invoice = await API.sales.getInvoice(invoiceId);
        
        // Show split payment modal
        showSplitPaymentModal(invoice);
    } catch (error) {
        console.error('Error loading invoice for payment:', error);
        showToast(error.message || 'Failed to load invoice', 'error');
    }
}

function showSplitPaymentModal(invoice) {
    const totalAmount = parseFloat(invoice.total_inclusive || 0);
    const isCreditInvoice = invoice.payment_mode === 'credit';
    
    // Load existing payments
    API.sales.getPayments(invoice.id).then(async payments => {
        const paidSoFar = payments.reduce((sum, p) => sum + parseFloat(p.amount || 0), 0);
        const balance = totalAmount - paidSoFar;
        const isAdminOrManager = await checkIfAdminOrManager();
        
        // Warning for non-credit invoices requiring full payment
        const paymentWarning = !isCreditInvoice && balance > 0 
            ? `<div style="margin-bottom: 1rem; padding: 0.75rem; background: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 0.25rem;">
                <i class="fas fa-exclamation-triangle" style="color: #f59e0b;"></i>
                <strong style="margin-left: 0.5rem;">Full Payment Required</strong>
                <p style="margin: 0.5rem 0 0 0; font-size: 0.875rem;">
                    This invoice was batched with payment mode "${invoice.payment_mode}". 
                    ${isAdminOrManager 
                        ? 'As admin/manager, you can approve partial payments.' 
                        : 'Cashier must collect full payment unless approved by admin/manager.'}
                </p>
            </div>`
            : '';
        
        const modalContent = `
            <div style="max-width: 600px;">
                <div style="margin-bottom: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                        <span style="font-weight: 600;">Total Amount:</span>
                        <strong>${formatCurrency(totalAmount)}</strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                        <span>Paid so far:</span>
                        <span>${formatCurrency(paidSoFar)}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding-top: 0.5rem; border-top: 2px solid var(--border-color);">
                        <span style="font-weight: 600;">Balance:</span>
                        <strong style="color: ${balance > 0 ? 'var(--danger-color)' : 'var(--success-color)'};">${formatCurrency(balance)}</strong>
                    </div>
                </div>
                
                ${paymentWarning}
                
                ${payments.length > 0 ? `
                    <div style="margin-bottom: 1.5rem;">
                        <h5 style="margin-bottom: 0.5rem;">Payment Summary:</h5>
                        <div style="max-height: 150px; overflow-y: auto;">
                            ${payments.map(p => `
                                <div style="display: flex; justify-content: space-between; padding: 0.5rem; border-bottom: 1px solid var(--border-color);">
                                    <span>${p.payment_mode.toUpperCase()}: ${p.payment_reference || ''}</span>
                                    <span>${formatCurrency(p.amount)}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
                
                <form id="splitPaymentForm" onsubmit="submitSplitPayment(event, '${invoice.id}')">
                    <div style="margin-bottom: 1rem;">
                        <label class="form-label">Payment Mode *</label>
                        <select class="form-select" id="paymentMode" required>
                            <option value="cash">Cash</option>
                            <option value="mpesa">M-Pesa</option>
                            <option value="card">Card</option>
                            <option value="credit">Credit</option>
                            <option value="insurance">Insurance</option>
                        </select>
                    </div>
                    
                    <div style="margin-bottom: 1rem;">
                        <label class="form-label">Amount *</label>
                        <input type="number" class="form-input" id="paymentAmount" 
                               step="0.01" min="0.01" max="${balance}" 
                               value="${balance > 0 ? balance.toFixed(2) : ''}" required
                               ${!isCreditInvoice && !isAdminOrManager ? 'readonly' : ''}>
                        ${!isCreditInvoice && !isAdminOrManager 
                            ? '<small style="color: var(--text-secondary);">Full payment required. Amount locked to balance.</small>' 
                            : ''}
                    </div>
                    
                    <div style="margin-bottom: 1rem;">
                        <label class="form-label">Reference (Optional)</label>
                        <input type="text" class="form-input" id="paymentReference" 
                               placeholder="M-Pesa code, transaction ID, etc.">
                    </div>
                    
                    <div style="display: flex; gap: 1rem; justify-content: flex-end; margin-top: 1.5rem;">
                        <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-check"></i> Add Payment
                        </button>
                    </div>
                </form>
            </div>
        `;
        
        showModal('Collect Payment', modalContent);
        
        // If non-credit and not admin, lock amount to full balance
        if (!isCreditInvoice && !isAdminOrManager && balance > 0) {
            const amountInput = document.getElementById('paymentAmount');
            if (amountInput) {
                amountInput.value = balance.toFixed(2);
            }
        }
    }).catch(error => {
        console.error('Error loading payments:', error);
        showToast('Error loading payment details', 'error');
    });
}

async function submitSplitPayment(event, invoiceId) {
    event.preventDefault();
    
    const paymentMode = document.getElementById('paymentMode').value;
    const amount = parseFloat(document.getElementById('paymentAmount').value);
    const reference = document.getElementById('paymentReference').value;
    const userId = CONFIG.USER_ID;
    
    if (!userId) {
        showToast('User ID not found. Please log in again.', 'error');
        return;
    }
    
    try {
        // Load invoice to check payment mode and balance
        const invoice = await API.sales.getInvoice(invoiceId);
        const existingPayments = await API.sales.getPayments(invoiceId);
        const paidSoFar = existingPayments.reduce((sum, p) => sum + parseFloat(p.amount || 0), 0);
        const balance = parseFloat(invoice.total_inclusive || 0) - paidSoFar;
        const isCreditInvoice = invoice.payment_mode === 'credit';
        
        // Check if this is a partial payment on a non-credit invoice
        if (!isCreditInvoice && amount < balance) {
            // Require admin/manager approval for partial payment
            const isAdminOrManager = await checkIfAdminOrManager();
            
            if (!isAdminOrManager) {
                showToast('Partial payment requires admin or manager approval. Please collect full payment or contact an administrator.', 'error');
                return;
            }
            
            // Admin/manager can approve partial payment
            if (!confirm(`You are about to collect a partial payment (${formatCurrency(amount)} of ${formatCurrency(balance)}). Continue?`)) {
                return;
            }
        }
        
        showToast('Processing payment...', 'info');
        
        const payment = await API.sales.addPayment(invoiceId, {
            invoice_id: invoiceId,
            payment_mode: paymentMode,
            amount: amount,
            payment_reference: reference || null,
            paid_by: userId
        });
        
        showToast('Payment added successfully!', 'success');
        
        // Reload invoice to check if fully paid
        const updatedInvoice = await API.sales.getInvoice(invoiceId);
        
        if (updatedInvoice.status === 'PAID') {
            showToast('Invoice fully paid!', 'success');
            closeModal();
            await fetchAndRenderSalesInvoicesData();
        } else {
            // Show updated payment modal
            showSplitPaymentModal(updatedInvoice);
        }
    } catch (error) {
        console.error('Error adding payment:', error);
        const errorMsg = error.message || 'Failed to add payment';
        showToast(errorMsg, 'error');
    }
}

// Check if current user is admin or manager
async function checkIfAdminOrManager() {
    try {
        if (!CONFIG.USER_ID) {
            return false;
        }
        
        // Try to get user directly first
        let currentUser = null;
        try {
            currentUser = await API.users.get(CONFIG.USER_ID);
        } catch (e) {
            // Fallback to listing all users
            const usersResponse = await API.users.list();
            currentUser = usersResponse.users?.find(u => u.id === CONFIG.USER_ID);
        }
        
        if (!currentUser) {
            return false;
        }
        
        // Check branch_roles - can be array of objects or array of role names
        let userRoles = [];
        if (currentUser.branch_roles && Array.isArray(currentUser.branch_roles)) {
            userRoles = currentUser.branch_roles.map(br => {
                if (typeof br === 'string') {
                    return br.toLowerCase();
                }
                // Handle object with role_name property
                return (br.role_name || br.role || '').toLowerCase();
            });
        }
        
        // Check if user has admin or manager role
        const adminRoles = ['super admin', 'admin', 'manager', 'administrator'];
        return userRoles.some(role => adminRoles.includes(role));
    } catch (error) {
        console.error('Error checking user role:', error);
        return false; // Default to false for security
    }
}

async function printSalesInvoice(invoiceId) {
    try {
        const invoice = await API.sales.getInvoice(invoiceId);
        
        // Create printable HTML
        const printWindow = window.open('', '_blank');
        const printContent = generateInvoicePrintHTML(invoice);
        
        printWindow.document.write(printContent);
        printWindow.document.close();
        
        // Wait for content to load, then print
        printWindow.onload = function() {
            setTimeout(() => {
                printWindow.print();
            }, 250);
        };
    } catch (error) {
        console.error('Error printing invoice:', error);
        showToast('Error loading invoice for printing', 'error');
    }
}

function generateInvoicePrintHTML(invoice) {
    const invoiceDate = new Date(invoice.invoice_date).toLocaleDateString();
    const itemsHTML = invoice.items && invoice.items.length > 0 
        ? invoice.items.map(item => {
            const itemName = item.item_name || item.item?.name || 'Item';
            const itemCode = item.item_code || item.item?.sku || '';
            return `
                <tr>
                    <td>${escapeHtml(itemName)} ${itemCode ? `(${escapeHtml(itemCode)})` : ''}</td>
                    <td style="text-align: right;">${parseFloat(item.quantity).toFixed(4)} ${escapeHtml(item.unit_name)}</td>
                    <td style="text-align: right;">${formatCurrency(item.unit_price_exclusive || 0)}</td>
                    <td style="text-align: right;">${formatCurrency(item.vat_amount || 0)}</td>
                    <td style="text-align: right;">${formatCurrency(item.line_total_inclusive || 0)}</td>
                </tr>
            `;
        }).join('')
        : '<tr><td colspan="5" style="text-align: center;">No items</td></tr>';
    
    return `
<!DOCTYPE html>
<html>
<head>
    <title>Invoice ${invoice.invoice_no}</title>
    <style>
        @media print {
            @page { size: 80mm auto; margin: 0; }
            body { margin: 0; padding: 10px; }
        }
        body {
            font-family: Arial, sans-serif;
            font-size: 12px;
            max-width: 80mm;
            margin: 0 auto;
            padding: 10px;
        }
        .header {
            text-align: center;
            border-bottom: 2px solid #000;
            padding-bottom: 10px;
            margin-bottom: 10px;
        }
        .invoice-info {
            margin: 10px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }
        th, td {
            padding: 5px;
            border-bottom: 1px solid #ddd;
            text-align: left;
        }
        th {
            background: #f0f0f0;
            font-weight: bold;
        }
        .total {
            font-weight: bold;
            font-size: 14px;
            border-top: 2px solid #000;
            padding-top: 5px;
        }
        .footer {
            margin-top: 20px;
            text-align: center;
            font-size: 10px;
            border-top: 1px solid #ddd;
            padding-top: 10px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>PharmaSight</h2>
        <p>Sales Invoice</p>
    </div>
    
    <div class="invoice-info">
        <p><strong>Invoice #:</strong> ${escapeHtml(invoice.invoice_no)}</p>
        <p><strong>Date:</strong> ${invoiceDate}</p>
        ${invoice.customer_name ? `<p><strong>Customer:</strong> ${escapeHtml(invoice.customer_name)}</p>` : ''}
        <p><strong>Status:</strong> ${invoice.status || 'DRAFT'}</p>
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Item</th>
                <th style="text-align: right;">Qty</th>
                <th style="text-align: right;">Price</th>
                <th style="text-align: right;">VAT</th>
                <th style="text-align: right;">Total</th>
            </tr>
        </thead>
        <tbody>
            ${itemsHTML}
        </tbody>
        <tfoot>
            <tr>
                <td colspan="4" class="total">Total:</td>
                <td class="total" style="text-align: right;">${formatCurrency(invoice.total_inclusive || 0)}</td>
            </tr>
        </tfoot>
    </table>
    
    <div class="footer">
        <p>Thank you for your business!</p>
        <p>Generated: ${new Date().toLocaleString()}</p>
    </div>
</body>
</html>
    `;
}

async function convertSalesInvoiceToQuotation(invoiceId) {
    if (!confirm('Convert this sales invoice to a quotation? The invoice will be removed from the sales list and added to quotations as a draft.')) {
        return;
    }
    
    try {
        showToast('Converting invoice to quotation...', 'info');
        const result = await API.sales.convertToQuotation(invoiceId);
        showToast(`Invoice converted to quotation: ${result.quotation_no}`, 'success');
        
        // Clear current invoice if we're editing it
        if (currentInvoice && currentInvoice.id === invoiceId) {
            currentInvoice = null;
            documentItems = [];
        }
        
        // Navigate to quotations page
        await loadSalesSubPage('quotations');
    } catch (error) {
        console.error('Error converting invoice to quotation:', error);
        const errorMsg = error.message || 'Failed to convert invoice to quotation';
        showToast(errorMsg, 'error');
    }
}

// Print Quotation (enabled for all statuses including draft)
// printType: 'normal' (A4) or 'thermal' (narrow) - from CONFIG.PRINT_TYPE or default 'normal'
async function printQuotation(quotationId, printType) {
    try {
        const quotation = await API.quotations.get(quotationId);
        const layout = printType || (typeof CONFIG !== 'undefined' && CONFIG.PRINT_TYPE) || 'normal';
        
        const printWindow = window.open('', '_blank');
        const printContent = generateQuotationPrintHTML(quotation, layout);
        
        printWindow.document.write(printContent);
        printWindow.document.close();
        
        printWindow.onload = function() {
            setTimeout(() => {
                printWindow.print();
            }, 250);
        };
    } catch (error) {
        console.error('Error printing quotation:', error);
        showToast('Error loading quotation for printing', 'error');
    }
}

function generateQuotationPrintHTML(quotation, printType) {
    const isThermal = printType === 'thermal';
    const quotationDate = new Date(quotation.quotation_date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    const validUntil = quotation.valid_until ? new Date(quotation.valid_until).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : 'N/A';
    const generatedTime = new Date().toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
    
    const companyName = quotation.company_name || 'PharmaSight';
    const companyAddress = quotation.company_address || '';
    const branchName = quotation.branch_name || '';
    const branchAddress = quotation.branch_address || '';
    const branchPhone = quotation.branch_phone || '';
    const createdByUser = quotation.created_by_username || '';
    const transactionMessage = (typeof CONFIG !== 'undefined' && CONFIG.TRANSACTION_MESSAGE) ? CONFIG.TRANSACTION_MESSAGE : '';
    
    const hasMargin = quotation.items && quotation.items.some(item => item.margin_percent != null);
    const itemsHTML = quotation.items && quotation.items.length > 0 
        ? quotation.items.map(item => {
            const itemName = item.item_name || item.item?.name || '';
            const itemCode = item.item_code || item.item?.sku || '';
            const marginCell = hasMargin 
                ? `<td style="text-align: right;">${item.margin_percent != null ? (parseFloat(item.margin_percent).toFixed(1) + '%') : '—'}</td>` 
                : '';
            return `
                <tr>
                    <td>${escapeHtml(itemName)}${itemCode ? ' (' + escapeHtml(itemCode) + ')' : ''}</td>
                    <td style="text-align: right;">${parseFloat(item.quantity).toFixed(4)} ${escapeHtml(item.unit_name)}</td>
                    <td style="text-align: right;">${formatCurrency(item.unit_price_exclusive || 0)}</td>
                    ${marginCell}
                    <td style="text-align: right;">${formatCurrency(item.vat_amount || 0)}</td>
                    <td style="text-align: right;">${formatCurrency(item.line_total_inclusive || 0)}</td>
                </tr>
            `;
        }).join('')
        : '<tr><td colspan="' + (hasMargin ? 6 : 5) + '" style="text-align: center;">No items</td></tr>';
    
    const marginHeader = hasMargin ? '<th style="text-align: right;">Margin</th>' : '';
    const colSpanTotal = hasMargin ? 5 : 4;
    
    const pageStyle = isThermal 
        ? `@page { size: 80mm auto; margin: 0; }
           body { font-size: 10px; max-width: 72mm; padding: 8px; margin: 0 auto; }
           .header, .footer { font-size: 9px; }
           th, td { padding: 4px; }`
        : `@page { size: A4; margin: 1cm; }
           body { font-size: 12px; max-width: 210mm; padding: 20px; margin: 0 auto; }
           th, td { padding: 8px; }`;
    
    return `
<!DOCTYPE html>
<html>
<head>
    <title>Quotation ${escapeHtml(quotation.quotation_no)}</title>
    <style>
        @media print { ${pageStyle} }
        body { font-family: Arial, sans-serif; }
        .header { border-bottom: 2px solid #000; padding-bottom: 10px; margin-bottom: 15px; }
        .company-name { font-size: 1.25em; font-weight: bold; margin-bottom: 4px; }
        .company-details { font-size: 0.9em; color: #333; line-height: 1.4; }
        .quotation-info { margin: 12px 0; }
        table { width: 100%; border-collapse: collapse; margin: 12px 0; }
        th, td { border-bottom: 1px solid #ddd; text-align: left; }
        th { background: #f0f0f0; font-weight: bold; }
        .total { font-weight: bold; border-top: 2px solid #000; padding-top: 8px; }
        .footer { margin-top: 20px; text-align: center; font-size: 0.85em; border-top: 1px solid #ddd; padding-top: 12px; color: #555; }
    </style>
</head>
<body>
    <div class="header">
        <div class="company-name">${escapeHtml(companyName)}</div>
        ${companyAddress ? `<div class="company-details">${escapeHtml(companyAddress)}</div>` : ''}
        ${branchName ? `<div class="company-details"><strong>Branch:</strong> ${escapeHtml(branchName)}${branchAddress ? ' — ' + escapeHtml(branchAddress) : ''}${branchPhone ? ' | Ph: ' + escapeHtml(branchPhone) : ''}</div>` : ''}
        ${createdByUser ? `<div class="company-details"><strong>Prepared by:</strong> ${escapeHtml(createdByUser)}</div>` : ''}
        <p style="margin: 8px 0 0 0; font-weight: bold;">Sales Quotation</p>
    </div>
    
    <div class="quotation-info">
        <p><strong>Quotation #:</strong> ${escapeHtml(quotation.quotation_no)} &nbsp; <strong>Date:</strong> ${quotationDate} &nbsp; <strong>Valid Until:</strong> ${validUntil}</p>
        ${quotation.customer_name ? `<p><strong>Customer:</strong> ${escapeHtml(quotation.customer_name)}</p>` : ''}
        <p><strong>Status:</strong> ${(quotation.status || 'draft')}</p>
    </div>
    
    <table>
        <thead>
            <tr>
                <th>Item</th>
                <th style="text-align: right;">Qty</th>
                <th style="text-align: right;">Price/Unit</th>
                ${marginHeader}
                <th style="text-align: right;">VAT</th>
                <th style="text-align: right;">Total</th>
            </tr>
        </thead>
        <tbody>
            ${itemsHTML}
        </tbody>
        <tfoot>
            <tr>
                <td colspan="${colSpanTotal}" class="total">Total:</td>
                <td class="total" style="text-align: right;">${formatCurrency(quotation.total_inclusive || 0)}</td>
            </tr>
        </tfoot>
    </table>
    
    <div class="footer">
        ${transactionMessage ? `<p>${escapeHtml(transactionMessage)}</p>` : ''}
        <p>Generated: ${generatedTime}</p>
    </div>
</body>
</html>
    `;
}

// Utility function
function escapeHtml(text) {
    if (!text) return '—';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Add quotation items to order book (bulk from current quotation form)
async function addQuotationItemsToOrderBook() {
    try {
        if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID || !CONFIG.USER_ID) {
            showToast('Configuration error: Missing company, branch, or user ID', 'error');
            return;
        }
        if (!salesQuotationItemsTable || typeof salesQuotationItemsTable.getItems !== 'function') {
            showToast('No quotation items to add', 'warning');
            return;
        }
        const items = salesQuotationItemsTable.getItems();
        const validItems = items.filter(i => i.item_id && !i.is_empty);
        if (validItems.length === 0) {
            showToast('Add at least one item to the quotation first', 'warning');
            return;
        }
        const itemIds = validItems.map(i => i.item_id);
        await API.orderBook.bulkCreate(
            { item_ids: itemIds, reason: 'MANUAL_QUOTATION', notes: 'Added from quotation' },
            CONFIG.COMPANY_ID,
            CONFIG.BRANCH_ID,
            CONFIG.USER_ID
        );
        showToast(`${validItems.length} item(s) added to order book`, 'success');
    } catch (error) {
        console.error('Error adding quotation items to order book:', error);
        showToast(`Error: ${error.message || 'Failed to add to order book'}`, 'error');
    }
}

// Add item to order book from sales invoice
async function addItemToOrderBookFromSale(itemId, itemName, unitName, invoiceId) {
    try {
        if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID || !CONFIG.USER_ID) {
            showToast('Configuration error: Missing company, branch, or user ID', 'error');
            return;
        }
        
        // Get current stock to determine quantity needed
        let quantityNeeded = 1; // Default
        try {
            const stock = await API.inventory.getStock(itemId, CONFIG.BRANCH_ID);
            if (stock && stock.stock !== undefined) {
                // If stock is zero or negative, suggest ordering
                if (stock.stock <= 0) {
                    quantityNeeded = 10; // Suggest ordering 10 units if out of stock
                }
            }
        } catch (error) {
            console.warn('Could not get stock info, using default quantity:', error);
        }
        
        // Create order book entry
        const entryData = {
            item_id: itemId,
            quantity_needed: quantityNeeded,
            unit_name: unitName,
            reason: 'MANUAL_SALE',
            source_reference_type: 'sales_invoice',
            source_reference_id: invoiceId,
            notes: `Added from sales invoice`
        };
        
        await API.orderBook.create(entryData, CONFIG.COMPANY_ID, CONFIG.BRANCH_ID, CONFIG.USER_ID);
        showToast(`${itemName} added to order book`, 'success');
    } catch (error) {
        console.error('Error adding item to order book:', error);
        showToast(`Error: ${error.message || 'Failed to add to order book'}`, 'error');
    }
}

// Export functions
if (typeof window !== 'undefined') {
    window.loadSales = loadSales;
    window.loadSalesSubPage = loadSalesSubPage;
    window.switchSalesSubPage = switchSalesSubPage;
    window.updateSalesSubNavActiveState = updateSalesSubNavActiveState;
    window.createNewSalesInvoice = createNewSalesInvoice;
    window.renderCreateSalesInvoicePage = renderCreateSalesInvoicePage;
    window.saveSalesInvoice = saveSalesInvoice;
    window.applySalesDateFilter = applySalesDateFilter;
    window.clearSalesDateFilter = clearSalesDateFilter;
    window.filterSalesInvoices = filterSalesInvoices;
    window.viewSalesInvoice = viewSalesInvoice;
    window.addItemToOrderBookFromSale = addItemToOrderBookFromSale;
    window.addQuotationItemsToOrderBook = addQuotationItemsToOrderBook;
    window.fetchAndRenderSalesInvoicesData = fetchAndRenderSalesInvoicesData;
    window.viewQuotation = viewQuotation;
    window.editQuotation = editQuotation;
    window.deleteQuotation = deleteQuotation;
    window.updateSalesQuotation = updateSalesQuotation;
    window.autoSaveQuotation = autoSaveQuotation;
    window.renderCreateSalesQuotationPage = renderCreateSalesQuotationPage;
    window.saveSalesQuotation = saveSalesQuotation;
    window.searchItems = searchItems;
    window.addToCart = addToCart;
    window.updateCartPrice = updateCartPrice;
    window.confirmAddToCart = confirmAddToCart;
    window.removeFromCart = removeFromCart;
    window.processSale = processSale;
    window.batchSalesInvoice = batchSalesInvoice;
    window.deleteSalesInvoice = deleteSalesInvoice;
    window.collectPayment = collectPayment;
    window.printSalesInvoice = printSalesInvoice;
    window.submitSplitPayment = submitSplitPayment;
    window.convertSalesInvoiceToQuotation = convertSalesInvoiceToQuotation;
    window.handlePaymentModeChange = handlePaymentModeChange;
    window.handleSalesTypeChange = handleSalesTypeChange;
    window.printQuotation = printQuotation;
}
