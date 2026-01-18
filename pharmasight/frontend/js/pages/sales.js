// Sales Page - Point of Sale and Sales Invoices

let currentSalesSubPage = 'pos'; // 'pos', 'invoices'
let cart = [];
let currentInvoice = null;
let salesInvoices = [];
let salesDocuments = [];

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
        case 'pos':
            await renderPOSPage();
            break;
        case 'invoices':
            await renderSalesInvoicesPage();
            break;
        case 'create-invoice':
            await renderCreateSalesInvoicePage();
            break;
        default:
            await renderPOSPage();
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
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Amount</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Payment</th>
                                <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
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
                <td colspan="7" style="padding: 3rem; text-align: center;">
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
    
    tbody.innerHTML = salesInvoices.map(invoice => `
        <tr style="cursor: pointer;" onclick="if(window.viewSalesInvoice) window.viewSalesInvoice('${invoice.id}')">
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                <strong style="color: var(--primary-color);">${invoice.invoice_no || invoice.id.substring(0, 8)}</strong>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatDate(invoice.invoice_date || invoice.created_at)}</td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${invoice.customer_name || 'Walk-in Customer'}</td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>${formatCurrency(invoice.total_inclusive || invoice.total || 0)}</strong></td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${invoice.payment_mode || 'Cash'}</td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                <span class="badge ${invoice.payment_status === 'PAID' ? 'badge-success' : 'badge-warning'}">
                    ${invoice.payment_status || 'PENDING'}
                </span>
            </td>
            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                <button class="btn btn-outline" onclick="event.stopPropagation(); if(window.viewSalesInvoice) window.viewSalesInvoice('${invoice.id}')" title="View">
                    <i class="fas fa-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

// Create new Sales Invoice
function createNewSalesInvoice() {
    console.log('createNewSalesInvoice() called');
    currentDocument = { type: 'invoice', items: [] };
    documentItems = [];
    loadSalesSubPage('create-invoice');
}

// Render Create Sales Invoice Page
async function renderCreateSalesInvoicePage() {
    console.log('renderCreateSalesInvoicePage() called');
    const page = document.getElementById('sales');
    if (!page) return;
    
    // Reset document state
    currentDocument = { type: 'invoice', items: [] };
    documentItems = [];
    
    const today = new Date().toISOString().split('T')[0];
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.5rem; border-bottom: 1px solid var(--border-color);">
                <h3 class="card-title" style="margin: 0; font-size: 1.5rem;">
                    <i class="fas fa-file-invoice-dollar"></i> Create Sales Invoice
                </h3>
                <button class="btn btn-outline" onclick="loadSalesSubPage('invoices')">
                    <i class="fas fa-arrow-left"></i> Back to Invoices
                </button>
            </div>
            
            <div class="card-body" style="padding: 1.5rem;">
                <form id="salesInvoiceForm" onsubmit="saveSalesInvoice(event)">
                    <!-- Document Header -->
                    <div style="margin-bottom: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;">
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;">
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Date *</label>
                                <input type="date" class="form-input" name="invoice_date" 
                                       value="${today}" required>
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Customer</label>
                                <input type="text" class="form-input" name="customer_name" 
                                       placeholder="Customer name (optional)">
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Reference</label>
                                <input type="text" class="form-input" name="reference" 
                                       placeholder="Reference number">
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-top: 1rem;">
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Payment Mode</label>
                                <select class="form-select" name="payment_mode">
                                    <option value="cash">Cash</option>
                                    <option value="card">Card</option>
                                    <option value="mpesa">M-Pesa</option>
                                    <option value="credit">Credit</option>
                                </select>
                            </div>
                            <div class="form-group" style="margin: 0;">
                                <label class="form-label" style="font-weight: 600;">Notes</label>
                                <input type="text" class="form-input" name="notes" 
                                       placeholder="Additional notes">
                            </div>
                        </div>
                    </div>
                    
                    <!-- Transaction Items Table -->
                    <div style="margin-bottom: 1.5rem;">
                        <div id="salesInvoiceItemsContainer">
                            <!-- TransactionItemsTable component will render here -->
                        </div>
                    </div>
                    
                    <!-- Form Actions -->
                    <div style="display: flex; gap: 1rem; justify-content: flex-end; padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <button type="button" class="btn btn-secondary" onclick="loadSalesSubPage('invoices')">
                            Cancel
                        </button>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Sales Invoice
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize TransactionItemsTable component
    initializeSalesInvoiceItemsTable();
}

// Initialize TransactionItemsTable for Sales Invoice
let salesInvoiceItemsTable = null;

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
                total: item.total
            }));
        },
        onTotalChange: (total) => {
            console.log('Sales invoice total changed:', total);
        },
        onItemCreate: (query, rowIndex, callback) => {
            showToast(`To create item "${query}", please go to Items page`, 'info');
        }
    });
}

// Save Sales Invoice
async function saveSalesInvoice(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
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
    
    const invoiceData = {
        company_id: CONFIG.COMPANY_ID,
        branch_id: CONFIG.BRANCH_ID,
        invoice_date: formData.get('invoice_date'),
        customer_name: formData.get('customer_name') || null,
        reference: formData.get('reference') || null,
        payment_mode: formData.get('payment_mode') || 'cash',
        payment_status: formData.get('payment_mode') === 'credit' ? 'PENDING' : 'PAID',
        notes: formData.get('notes') || null,
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
        const invoice = await API.sales.createInvoice(invoiceData);
        showToast('Sales invoice created successfully!', 'success');
        loadSalesSubPage('invoices');
    } catch (error) {
        console.error('Error creating sales invoice:', error);
        showToast(error.message || 'Error creating sales invoice', 'error');
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

function viewSalesInvoice(invoiceId) {
    showToast('Invoice details coming soon', 'info');
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
            // Use API search instead of loading all items
            if (!CONFIG || !CONFIG.COMPANY_ID || !window.API) {
                document.getElementById('itemsList').innerHTML = 
                    '<p class="text-center" style="color: var(--danger-color);">Configuration error. Please set Company ID in Settings.</p>';
                return;
            }
            
            const items = await API.items.search(query, CONFIG.COMPANY_ID, 20);
            renderItemsList(items);
        } catch (error) {
            console.error('Error searching items:', error);
            document.getElementById('itemsList').innerHTML = 
                `<p class="text-center" style="color: var(--danger-color);">Error: ${error.message || 'Search failed'}</p>`;
        }
    }, 300);
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
        
        // Get recommended price
        const priceInfo = await API.items.getRecommendedPrice(
            itemId, CONFIG.BRANCH_ID, CONFIG.COMPANY_ID, item.base_unit
        );
        
        // Show add to cart modal
        showAddToCartModal(item, availability, priceInfo);
    } catch (error) {
        console.error('Error getting item details:', error);
        showToast('Error loading item details', 'error');
    }
}

function showAddToCartModal(item, availability, priceInfo) {
    const units = availability.unit_breakdown || [];
    const unitOptions = units.map(u => 
        `<option value="${u.unit_name}">${u.unit_name} (${u.display})</option>`
    ).join('');
    
    const content = `
        <form id="addToCartForm" onsubmit="confirmAddToCart(event, '${item.id}')">
            <div class="form-group">
                <label class="form-label">Item</label>
                <input type="text" class="form-input" value="${item.name}" disabled>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Unit</label>
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
    window.fetchAndRenderSalesInvoicesData = fetchAndRenderSalesInvoicesData;
    window.searchItems = searchItems;
    window.addToCart = addToCart;
    window.updateCartPrice = updateCartPrice;
    window.confirmAddToCart = confirmAddToCart;
    window.removeFromCart = removeFromCart;
    window.processSale = processSale;
}
