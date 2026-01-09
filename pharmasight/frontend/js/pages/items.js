// Items Management Page

let itemsList = [];

async function loadItems() {
    const page = document.getElementById('items');
    
    if (!CONFIG.COMPANY_ID) {
        page.innerHTML = '<div class="card"><p>Please configure Company ID in Settings</p></div>';
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Items</h3>
                <button class="btn btn-primary" onclick="showAddItemModal()">
                    <i class="fas fa-plus"></i> Add Item
                </button>
            </div>
            <div id="itemsTableContainer">
                <div class="spinner"></div>
            </div>
        </div>
    `;
    
    try {
        itemsList = await API.items.list(CONFIG.COMPANY_ID);
        renderItemsTable();
    } catch (error) {
        console.error('Error loading items:', error);
        showToast('Error loading items', 'error');
        document.getElementById('itemsTableContainer').innerHTML = 
            '<p>Error loading items. Please try again.</p>';
    }
}

function renderItemsTable() {
    const container = document.getElementById('itemsTableContainer');
    
    if (itemsList.length === 0) {
        container.innerHTML = '<p>No items found. Add your first item to get started.</p>';
        return;
    }
    
    container.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>SKU</th>
                        <th>Base Unit</th>
                        <th>Category</th>
                        <th>Default Cost</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${itemsList.map(item => `
                        <tr>
                            <td>${item.name}</td>
                            <td>${item.sku || '-'}</td>
                            <td>${item.base_unit}</td>
                            <td>${item.category || '-'}</td>
                            <td>${formatCurrency(item.default_cost || 0)}</td>
                            <td>
                                <span class="badge ${item.is_active ? 'badge-success' : 'badge-danger'}">
                                    ${item.is_active ? 'Active' : 'Inactive'}
                                </span>
                            </td>
                            <td>
                                <button class="btn btn-outline" onclick="editItem('${item.id}')">
                                    <i class="fas fa-edit"></i>
                                </button>
                                <button class="btn btn-outline" onclick="viewItemUnits('${item.id}')">
                                    <i class="fas fa-cubes"></i>
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function showAddItemModal() {
    const content = `
        <form id="itemForm" onsubmit="saveItem(event)">
            <div class="form-group">
                <label class="form-label">Item Name *</label>
                <input type="text" class="form-input" name="name" required>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Generic Name</label>
                    <input type="text" class="form-input" name="generic_name">
                </div>
                <div class="form-group">
                    <label class="form-label">SKU</label>
                    <input type="text" class="form-input" name="sku">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Base Unit *</label>
                    <select class="form-select" name="base_unit" required>
                        <option value="tablet">Tablet</option>
                        <option value="capsule">Capsule</option>
                        <option value="ml">ML</option>
                        <option value="gram">Gram</option>
                        <option value="piece">Piece</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Category</label>
                    <input type="text" class="form-input" name="category">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Default Cost</label>
                <input type="number" class="form-input" name="default_cost" step="0.01" min="0" value="0">
            </div>
            <div class="form-group">
                <label class="form-label">Units (Breaking Bulk)</label>
                <div id="unitsContainer">
                    <div class="form-row" id="unitRow0">
                        <div class="form-group">
                            <input type="text" class="form-input" name="unit_name_0" placeholder="Unit name (e.g., box)" value="tablet">
                        </div>
                        <div class="form-group">
                            <input type="number" class="form-input" name="multiplier_0" placeholder="Multiplier" step="0.01" min="0.01" value="1">
                        </div>
                        <div class="form-group">
                            <input type="checkbox" name="is_default_0" checked> Default
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-outline mt-2" onclick="addUnitRow()">
                    <i class="fas fa-plus"></i> Add Unit
                </button>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="itemForm">Save Item</button>
    `;
    
    showModal('Add New Item', content, footer);
}

let unitRowCount = 1;

function addUnitRow() {
    const container = document.getElementById('unitsContainer');
    const row = document.createElement('div');
    row.className = 'form-row';
    row.id = `unitRow${unitRowCount}`;
    row.innerHTML = `
        <div class="form-group">
            <input type="text" class="form-input" name="unit_name_${unitRowCount}" placeholder="Unit name (e.g., box)">
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
    
    // Build item data
    const itemData = {
        company_id: CONFIG.COMPANY_ID,
        name: formData.get('name'),
        generic_name: formData.get('generic_name') || null,
        sku: formData.get('sku') || null,
        category: formData.get('category') || null,
        base_unit: formData.get('base_unit'),
        default_cost: parseFloat(formData.get('default_cost') || 0),
        units: []
    };
    
    // Collect units
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
        await API.items.create(itemData);
        showToast('Item created successfully', 'success');
        closeModal();
        loadItems();
    } catch (error) {
        showToast(error.message || 'Error creating item', 'error');
    }
}

function editItem(itemId) {
    const item = itemsList.find(i => i.id === itemId);
    if (!item) return;
    
    showToast('Edit functionality coming soon', 'info');
}

function viewItemUnits(itemId) {
    const item = itemsList.find(i => i.id === itemId);
    if (!item) return;
    
    const unitsList = item.units.map(u => 
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

// Export
window.loadItems = loadItems;
window.showAddItemModal = showAddItemModal;
window.addUnitRow = addUnitRow;
window.removeUnitRow = removeUnitRow;
window.saveItem = saveItem;
window.editItem = editItem;
window.viewItemUnits = viewItemUnits;

