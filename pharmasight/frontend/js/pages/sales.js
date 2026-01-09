// Sales (POS) Page

let cart = [];
let currentInvoice = null;

async function loadSales() {
    const page = document.getElementById('sales');
    
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
        page.innerHTML = '<div class="card"><p>Please configure Company and Branch in Settings</p></div>';
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Point of Sale</h3>
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
            if (allItems.length === 0) {
                allItems = await API.items.list(CONFIG.COMPANY_ID);
            }
            
            const filtered = allItems.filter(item => 
                item.name.toLowerCase().includes(query.toLowerCase()) ||
                (item.sku && item.sku.toLowerCase().includes(query.toLowerCase())) ||
                (item.barcode && item.barcode.toLowerCase().includes(query.toLowerCase()))
            );
            
            renderItemsList(filtered);
        } catch (error) {
            console.error('Error searching items:', error);
            showToast('Error searching items', 'error');
        }
    }, 300);
}

function renderItemsList(items) {
    const container = document.getElementById('itemsList');
    
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
                        ${item.base_unit} | ${item.category || 'Uncategorized'}
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
    const item = allItems.find(i => i.id === itemId);
    if (!item) return;
    
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
    
    if (cart.length === 0) {
        container.innerHTML = '<p class="text-center">Cart is empty</p>';
        summary.innerHTML = '';
        checkoutBtn.disabled = true;
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
    
    checkoutBtn.disabled = false;
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
        document.getElementById('itemSearch').value = '';
        document.getElementById('itemsList').innerHTML = '<p class="text-center">Search for items to add to cart</p>';
        
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
            <h4>Invoice #${invoice.invoice_no}</h4>
            <p><strong>Date:</strong> ${formatDate(invoice.invoice_date)}</p>
            <p><strong>Total:</strong> ${formatCurrency(invoice.total_inclusive)}</p>
            <p><strong>Payment:</strong> ${invoice.payment_mode}</p>
        </div>
    `;
    
    showModal('Sale Complete', content, '<button class="btn btn-primary" onclick="closeModal()">OK</button>');
}

// Export
window.loadSales = loadSales;
window.searchItems = searchItems;
window.addToCart = addToCart;
window.updateCartPrice = updateCartPrice;
window.confirmAddToCart = confirmAddToCart;
window.removeFromCart = removeFromCart;
window.processSale = processSale;

