// Purchases (GRN) Page

let grnItems = [];
let allSuppliers = [];

async function loadPurchases() {
    const page = document.getElementById('purchases');
    
    if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
        page.innerHTML = '<div class="card"><p>Please configure Company and Branch in Settings</p></div>';
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Goods Received Notes (GRN)</h3>
            </div>
            <div id="grnFormContainer">
                <form id="grnForm" onsubmit="saveGRN(event)">
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Supplier *</label>
                            <select class="form-select" name="supplier_id" id="supplierSelect" required>
                                <option value="">Select Supplier</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Date Received *</label>
                            <input type="date" class="form-input" name="date_received" 
                                   value="${new Date().toISOString().split('T')[0]}" required>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Notes</label>
                        <textarea class="form-textarea" name="notes" rows="2"></textarea>
                    </div>
                    
                    <div class="card" style="margin-top: 1.5rem;">
                        <div class="card-header">
                            <h4>Items</h4>
                            <button type="button" class="btn btn-primary" onclick="showAddGRNItemModal()">
                                <i class="fas fa-plus"></i> Add Item
                            </button>
                        </div>
                        <div id="grnItemsList">
                            <p class="text-center">No items added yet</p>
                        </div>
                        <div id="grnSummary" style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color);"></div>
                    </div>
                    
                    <div style="margin-top: 1.5rem;">
                        <button type="submit" class="btn btn-primary" id="saveGRNBtn" disabled>
                            <i class="fas fa-save"></i> Save GRN
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="clearGRNForm()">
                            <i class="fas fa-times"></i> Clear
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    grnItems = [];
    await loadSuppliers();
    renderGRNItems();
}

async function loadSuppliers() {
    // TODO: Implement supplier API
    // For now, use placeholder
    allSuppliers = [];
    const select = document.getElementById('supplierSelect');
    if (select) {
        select.innerHTML = '<option value="">Select Supplier</option>';
        allSuppliers.forEach(supplier => {
            const option = document.createElement('option');
            option.value = supplier.id;
            option.textContent = supplier.name;
            select.appendChild(option);
        });
    }
}

function showAddGRNItemModal() {
    const content = `
        <form id="grnItemForm" onsubmit="addGRNItem(event)">
            <div class="form-group">
                <label class="form-label">Item *</label>
                <input type="text" class="form-input" id="grnItemSearch" 
                       placeholder="Search item..." onkeyup="searchGRNItems(event)">
                <div id="grnItemSearchResults" style="max-height: 200px; overflow-y: auto; margin-top: 0.5rem;"></div>
            </div>
            <div id="grnItemDetails" style="display: none;">
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Unit *</label>
                        <select class="form-select" name="unit_name" id="grnItemUnit" required></select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Quantity *</label>
                        <input type="number" class="form-input" name="quantity" 
                               step="0.01" min="0.01" required>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Unit Cost *</label>
                        <input type="number" class="form-input" name="unit_cost" 
                               step="0.01" min="0" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Batch Number</label>
                        <input type="text" class="form-input" name="batch_number">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Expiry Date</label>
                    <input type="date" class="form-input" name="expiry_date">
                </div>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="grnItemForm" id="addGRNItemBtn" disabled>Add Item</button>
    `;
    
    showModal('Add Item to GRN', content, footer);
}

let grnSelectedItem = null;
let grnAllItems = [];

async function searchGRNItems(event) {
    const query = event.target.value.trim();
    const results = document.getElementById('grnItemSearchResults');
    
    if (query.length < 2) {
        results.innerHTML = '';
        return;
    }
    
    try {
        if (grnAllItems.length === 0) {
            grnAllItems = await API.items.list(CONFIG.COMPANY_ID);
        }
        
        const filtered = grnAllItems.filter(item => 
            item.name.toLowerCase().includes(query.toLowerCase()) ||
            (item.sku && item.sku.toLowerCase().includes(query.toLowerCase()))
        );
        
        if (filtered.length === 0) {
            results.innerHTML = '<p>No items found</p>';
            return;
        }
        
        results.innerHTML = filtered.map(item => `
            <div class="card" style="margin-bottom: 0.5rem; cursor: pointer; padding: 0.75rem;" 
                 onclick="selectGRNItem('${item.id}')">
                <strong>${item.name}</strong>
                <p style="margin: 0.25rem 0; font-size: 0.875rem; color: var(--text-secondary);">
                    ${item.base_unit} | ${item.category || 'Uncategorized'}
                </p>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error searching items:', error);
    }
}

async function selectGRNItem(itemId) {
    const item = grnAllItems.find(i => i.id === itemId);
    if (!item) return;
    
    grnSelectedItem = item;
    
    // Get item units
    const availability = await API.inventory.getAvailability(itemId, CONFIG.BRANCH_ID);
    const units = availability.unit_breakdown || [];
    
    const unitSelect = document.getElementById('grnItemUnit');
    unitSelect.innerHTML = units.map(u => 
        `<option value="${u.unit_name}">${u.unit_name}</option>`
    ).join('');
    
    document.getElementById('grnItemDetails').style.display = 'block';
    document.getElementById('addGRNItemBtn').disabled = false;
    document.getElementById('grnItemSearchResults').innerHTML = '';
}

function addGRNItem(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    if (!grnSelectedItem) {
        showToast('Please select an item', 'warning');
        return;
    }
    
    const quantity = parseFloat(formData.get('quantity'));
    const unitCost = parseFloat(formData.get('unit_cost'));
    const totalCost = quantity * unitCost;
    
    grnItems.push({
        item_id: grnSelectedItem.id,
        item_name: grnSelectedItem.name,
        unit_name: formData.get('unit_name'),
        quantity: quantity,
        unit_cost: unitCost,
        batch_number: formData.get('batch_number') || null,
        expiry_date: formData.get('expiry_date') || null,
        total_cost: totalCost
    });
    
    renderGRNItems();
    closeModal();
    showToast('Item added to GRN', 'success');
}

function renderGRNItems() {
    const container = document.getElementById('grnItemsList');
    const summary = document.getElementById('grnSummary');
    const saveBtn = document.getElementById('saveGRNBtn');
    
    if (grnItems.length === 0) {
        container.innerHTML = '<p class="text-center">No items added yet</p>';
        summary.innerHTML = '';
        saveBtn.disabled = true;
        return;
    }
    
    container.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Unit</th>
                        <th>Quantity</th>
                        <th>Unit Cost</th>
                        <th>Batch</th>
                        <th>Expiry</th>
                        <th>Total</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${grnItems.map((item, index) => `
                        <tr>
                            <td>${item.item_name}</td>
                            <td>${item.unit_name}</td>
                            <td>${item.quantity}</td>
                            <td>${formatCurrency(item.unit_cost)}</td>
                            <td>${item.batch_number || '-'}</td>
                            <td>${item.expiry_date ? formatDate(item.expiry_date) : '-'}</td>
                            <td>${formatCurrency(item.total_cost)}</td>
                            <td>
                                <button class="btn btn-danger" onclick="removeGRNItem(${index})">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
    
    const total = grnItems.reduce((sum, item) => sum + item.total_cost, 0);
    summary.innerHTML = `
        <div class="flex-between">
            <strong>Total Cost:</strong>
            <strong style="font-size: 1.25rem;">${formatCurrency(total)}</strong>
        </div>
    `;
    
    saveBtn.disabled = false;
}

function removeGRNItem(index) {
    grnItems.splice(index, 1);
    renderGRNItems();
}

function clearGRNForm() {
    grnItems = [];
    document.getElementById('grnForm').reset();
    renderGRNItems();
}

async function saveGRN(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    if (grnItems.length === 0) {
        showToast('Please add at least one item', 'warning');
        return;
    }
    
    if (!CONFIG.USER_ID) {
        showToast('User ID not configured', 'error');
        return;
    }
    
    const grnData = {
        company_id: CONFIG.COMPANY_ID,
        branch_id: CONFIG.BRANCH_ID,
        supplier_id: formData.get('supplier_id'),
        date_received: formData.get('date_received'),
        notes: formData.get('notes') || null,
        items: grnItems.map(item => ({
            item_id: item.item_id,
            unit_name: item.unit_name,
            quantity: item.quantity,
            unit_cost: item.unit_cost,
            batch_number: item.batch_number,
            expiry_date: item.expiry_date
        })),
        created_by: CONFIG.USER_ID
    };
    
    try {
        const grn = await API.purchases.createGRN(grnData);
        showToast(`GRN ${grn.grn_no} created successfully!`, 'success');
        clearGRNForm();
    } catch (error) {
        console.error('Error creating GRN:', error);
        showToast(error.message || 'Error creating GRN', 'error');
    }
}

// Export
window.loadPurchases = loadPurchases;
window.showAddGRNItemModal = showAddGRNItemModal;
window.searchGRNItems = searchGRNItems;
window.selectGRNItem = selectGRNItem;
window.addGRNItem = addGRNItem;
window.removeGRNItem = removeGRNItem;
window.clearGRNForm = clearGRNForm;
window.saveGRN = saveGRN;

