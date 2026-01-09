// Inventory/Stock Page

let inventoryItems = [];

async function loadInventory() {
    const page = document.getElementById('inventory');
    
    if (!CONFIG.BRANCH_ID) {
        page.innerHTML = '<div class="card"><p>Please configure Branch in Settings</p></div>';
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title">Inventory Stock</h3>
                <div>
                    <input type="text" class="form-input" id="inventorySearch" 
                           placeholder="Search items..." style="width: 300px;"
                           onkeyup="searchInventory(event)">
                </div>
            </div>
            <div id="inventoryTableContainer">
                <div class="spinner"></div>
            </div>
        </div>
    `;
    
    await loadInventoryData();
}

async function loadInventoryData() {
    try {
        const stock = await API.inventory.getAllStock(CONFIG.BRANCH_ID);
        inventoryItems = stock;
        renderInventoryTable();
    } catch (error) {
        console.error('Error loading inventory:', error);
        showToast('Error loading inventory', 'error');
        document.getElementById('inventoryTableContainer').innerHTML = 
            '<p>Error loading inventory. Please try again.</p>';
    }
}

function searchInventory(event) {
    const query = event.target.value.toLowerCase();
    const filtered = inventoryItems.filter(item => 
        item.item_name.toLowerCase().includes(query)
    );
    renderInventoryTable(filtered);
}

async function renderInventoryTable(items = inventoryItems) {
    const container = document.getElementById('inventoryTableContainer');
    
    if (items.length === 0) {
        container.innerHTML = '<p class="text-center">No stock found</p>';
        return;
    }
    
    // Load detailed availability for each item
    const tableRows = await Promise.all(items.map(async (item) => {
        try {
            const availability = await API.inventory.getAvailability(item.item_id, CONFIG.BRANCH_ID);
            const stockDisplay = formatStockDisplay(availability);
            
            return `
                <tr>
                    <td>${item.item_name}</td>
                    <td>${item.base_unit}</td>
                    <td>${stockDisplay}</td>
                    <td>
                        <button class="btn btn-outline" onclick="viewItemStock('${item.item_id}')">
                            <i class="fas fa-eye"></i> View Details
                        </button>
                    </td>
                </tr>
            `;
        } catch (error) {
            return `
                <tr>
                    <td>${item.item_name}</td>
                    <td>${item.base_unit}</td>
                    <td>${item.stock} ${item.base_unit}</td>
                    <td>
                        <button class="btn btn-outline" onclick="viewItemStock('${item.item_id}')">
                            <i class="fas fa-eye"></i> View Details
                        </button>
                    </td>
                </tr>
            `;
        }
    }));
    
    container.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Item Name</th>
                        <th>Base Unit</th>
                        <th>Available Stock</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${tableRows.join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function viewItemStock(itemId) {
    try {
        const availability = await API.inventory.getAvailability(itemId, CONFIG.BRANCH_ID);
        const batches = await API.inventory.getBatches(itemId, CONFIG.BRANCH_ID);
        
        const batchesList = batches.map(batch => `
            <tr>
                <td>${batch.batch_number || '-'}</td>
                <td>${batch.expiry_date ? formatDate(batch.expiry_date) : '-'}</td>
                <td>${batch.quantity} ${availability.base_unit}</td>
                <td>${formatCurrency(batch.unit_cost)}</td>
                <td>${formatCurrency(batch.total_cost)}</td>
            </tr>
        `).join('');
        
        const unitsList = availability.unit_breakdown.map(u => 
            `<li>${u.display}</li>`
        ).join('');
        
        const content = `
            <div>
                <h4>${availability.item_name}</h4>
                <p><strong>Base Unit:</strong> ${availability.base_unit}</p>
                <p><strong>Total Stock:</strong> ${availability.total_base_units} ${availability.base_unit}</p>
                
                <h5 style="margin-top: 1rem;">Stock by Unit:</h5>
                <ul>${unitsList}</ul>
                
                ${batches.length > 0 ? `
                    <h5 style="margin-top: 1rem;">Stock by Batch (FEFO Order):</h5>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>Batch</th>
                                    <th>Expiry</th>
                                    <th>Quantity</th>
                                    <th>Unit Cost</th>
                                    <th>Total Cost</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${batchesList}
                            </tbody>
                        </table>
                    </div>
                ` : '<p>No batch information available</p>'}
            </div>
        `;
        
        showModal('Stock Details', content, '<button class="btn btn-secondary" onclick="closeModal()">Close</button>');
    } catch (error) {
        console.error('Error loading stock details:', error);
        showToast('Error loading stock details', 'error');
    }
}

// Export
window.loadInventory = loadInventory;
window.searchInventory = searchInventory;
window.viewItemStock = viewItemStock;

