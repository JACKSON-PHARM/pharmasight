// Items Management Page

let itemsList = [];

async function loadItems() {
    const page = document.getElementById('items');
    
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
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-box"></i> Inventory Items</h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-outline" onclick="downloadItemTemplate()">
                        <i class="fas fa-download"></i> Download Template
                    </button>
                    <button class="btn btn-secondary" onclick="showImportExcelModal()">
                        <i class="fas fa-file-excel"></i> Import Excel
                    </button>
                    <button class="btn btn-primary" onclick="showAddItemModal()">
                        <i class="fas fa-plus"></i> New Item
                    </button>
                </div>
            </div>
            <div style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                <div class="form-group" style="margin: 0;">
                    <input 
                        type="text" 
                        id="itemsSearchInput" 
                        class="form-input" 
                        placeholder="Search by name, SKU, or category..." 
                        oninput="filterItems()"
                        style="max-width: 400px;"
                    >
                </div>
            </div>
            <div id="itemsTableContainer">
                <div class="spinner"></div>
            </div>
        </div>
    `;
    
    try {
        // Load items with overview data (stock, supplier, cost)
        itemsList = await API.items.overview(CONFIG.COMPANY_ID, CONFIG.BRANCH_ID);
        renderItemsTable();
    } catch (error) {
        console.error('Error loading items:', error);
        showToast('Error loading items', 'error');
        document.getElementById('itemsTableContainer').innerHTML = 
            '<p>Error loading items. Please try again.</p>';
    }
}

let filteredItemsList = [];

function filterItems() {
    const searchTerm = document.getElementById('itemsSearchInput')?.value.toLowerCase() || '';
    if (!searchTerm) {
        filteredItemsList = [];
    } else {
        filteredItemsList = itemsList.filter(item => 
            (item.name || '').toLowerCase().includes(searchTerm) ||
            (item.sku || '').toLowerCase().includes(searchTerm) ||
            (item.category || '').toLowerCase().includes(searchTerm)
        );
    }
    renderItemsTable();
}

function renderItemsTable() {
    const container = document.getElementById('itemsTableContainer');
    
    // Use filtered list if search is active, otherwise use full list
    const displayList = filteredItemsList.length > 0 || document.getElementById('itemsSearchInput')?.value ? filteredItemsList : itemsList;
    
    if (displayList.length === 0) {
        container.innerHTML = '<p>No items found. Add your first item to get started.</p>';
        return;
    }
    
    container.innerHTML = `
        <div class="table-container" style="max-height: calc(100vh - 300px); overflow-y: auto; position: relative;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead style="position: sticky; top: 0; background: white; z-index: 20; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <tr>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Name</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">SKU</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Base Unit</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Category</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Current Stock</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Last Supplier</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Last Unit Cost</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Default Cost</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Status</th>
                        <th style="background: white; padding: 0.75rem; border-bottom: 2px solid var(--border-color); font-weight: 600; text-align: left;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${displayList.map(item => {
                        const isLowStock = item.minimum_stock !== null && item.current_stock !== null && item.current_stock < item.minimum_stock;
                        const rowClass = isLowStock ? 'style="background-color: #fff3cd;"' : '';
                        return `
                        <tr ${rowClass}>
                            <td>${escapeHtml(item.name)}</td>
                            <td><code>${escapeHtml(item.sku || '—')}</code></td>
                            <td>${escapeHtml(item.base_unit)}</td>
                            <td>${escapeHtml(item.category || '—')}</td>
                            <td>
                                ${item.current_stock !== null && item.current_stock !== undefined 
                                    ? `<strong ${isLowStock ? 'style="color: #dc3545;"' : ''}>${formatNumber(item.current_stock)} ${item.base_unit}</strong>`
                                    : '—'}
                            </td>
                            <td>${escapeHtml(item.last_supplier || '—')}</td>
                            <td>${item.last_unit_cost !== null && item.last_unit_cost !== undefined ? formatCurrency(item.last_unit_cost) : '—'}</td>
                            <td>${formatCurrency(item.default_cost || 0)}</td>
                            <td>
                                <span class="badge ${item.is_active ? 'badge-success' : 'badge-danger'}">
                                    ${item.is_active ? 'Active' : 'Inactive'}
                                </span>
                            </td>
                            <td>
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
        ${filteredItemsList.length > 0 && filteredItemsList.length < itemsList.length 
            ? `<p style="padding: 1rem; color: var(--text-secondary);">Showing ${filteredItemsList.length} of ${itemsList.length} items</p>`
            : ''}
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num === null || num === undefined) return '—';
    return Number(num).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function showAddItemModal() {
    const content = `
        <form id="itemForm" onsubmit="saveItem(event)" style="max-height: 70vh; overflow-y: auto;">
            <!-- Item Details Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-info-circle"></i> Item Details
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Item Code</label>
                        <input type="text" class="form-input" name="sku" placeholder="Auto-generated or manual">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Barcode</label>
                        <input type="text" class="form-input" name="barcode" placeholder="Scan or enter barcode">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Item Name *</label>
                    <input type="text" class="form-input" name="name" required placeholder="Enter item name">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Generic Name</label>
                        <input type="text" class="form-input" name="generic_name" placeholder="Enter generic name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Category/SubGroup</label>
                        <input type="text" class="form-input" name="category" placeholder="Enter category">
                    </div>
                </div>
            </div>

            <!-- Item Nature & Type Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-tag"></i> Item Classification
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Item Nature *</label>
                        <div style="display: flex; gap: 2rem; margin-top: 0.5rem;">
                            <label class="checkbox-item">
                                <input type="radio" name="item_nature" value="physical" checked>
                                <span>Physical Item</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="radio" name="item_nature" value="service">
                                <span>Service Item</span>
                            </label>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Type *</label>
                        <div style="display: flex; gap: 2rem; margin-top: 0.5rem;">
                            <label class="checkbox-item">
                                <input type="radio" name="item_type" value="branded">
                                <span>Branded</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="radio" name="item_type" value="generic" checked>
                                <span>Generic</span>
                            </label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Item Specifications Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-flask"></i> Specifications
                </div>
                <div class="form-group">
                    <label class="form-label">Ingredients/Composition</label>
                    <textarea class="form-textarea" name="ingredients" rows="3" placeholder="Enter active ingredients and composition"></textarea>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Strength</label>
                        <input type="text" class="form-input" name="strength" placeholder="Enter strength">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Base Unit/Unit Measure *</label>
                        <select class="form-select" name="base_unit" required>
                            <option value="tablet">Tablet</option>
                            <option value="capsule">Capsule</option>
                            <option value="ml">ML (Milliliter)</option>
                            <option value="gram">Gram</option>
                            <option value="piece">Piece</option>
                            <option value="bottle">Bottle</option>
                            <option value="tube">Tube</option>
                            <option value="sachet">Sachet</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Pack Size</label>
                        <input type="text" class="form-input" name="pack_size" placeholder="Enter pack size">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Standard Pack</label>
                        <input type="text" class="form-input" name="std_pack" placeholder="Standard packaging unit">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Main Formulation</label>
                        <select class="form-select" name="formulation">
                            <option value="">Select Formulation</option>
                            <option value="tablet">Tablet</option>
                            <option value="capsule">Capsule</option>
                            <option value="syrup">Syrup</option>
                            <option value="injection">Injection</option>
                            <option value="cream">Cream</option>
                            <option value="ointment">Ointment</option>
                            <option value="drops">Drops</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Weight (Kgs)</label>
                        <input type="number" class="form-input" name="weight" step="0.001" min="0" placeholder="0.000">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Manufacturer</label>
                        <input type="text" class="form-input" name="manufacturer" placeholder="Manufacturer name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Production Class</label>
                        <select class="form-select" name="production_class">
                            <option value="normal" selected>Normal</option>
                            <option value="controlled">Controlled</option>
                            <option value="scheduled">Scheduled</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Registration Number</label>
                        <input type="text" class="form-input" name="registration_no" placeholder="PPB Registration No">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Class Code</label>
                        <input type="text" class="form-input" name="class_code" placeholder="Product class code">
                    </div>
                </div>
            </div>

            <!-- Pricing Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-dollar-sign"></i> Pricing
                </div>
                <div class="form-group">
                    <label class="form-label">Default Cost per Base Unit</label>
                    <input type="number" class="form-input" name="default_cost" step="0.01" min="0" value="0" placeholder="0.00">
                </div>
            </div>

            <!-- Unit Conversions (Breaking Bulk) Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-cubes"></i> Unit Conversions (Breaking Bulk)
                </div>
                <div id="unitsContainer">
                    <div class="form-row" id="unitRow0">
                        <div class="form-group">
                            <label class="form-label">Unit Name</label>
                            <input type="text" class="form-input" name="unit_name_0" placeholder="Enter unit name" value="tablet">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Multiplier to Base</label>
                            <input type="number" class="form-input" name="multiplier_0" placeholder="Enter multiplier" step="0.01" min="0.01" value="1">
                        </div>
                        <div class="form-group" style="display: flex; align-items: flex-end;">
                            <label class="checkbox-item">
                                <input type="checkbox" name="is_default_0" checked>
                                <span>Default</span>
                            </label>
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-outline" onclick="addUnitRow()">
                    <i class="fas fa-plus"></i> Add Unit Conversion
                </button>
            </div>

            <!-- Item Attributes Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-check-square"></i> Item Attributes
                </div>
                <div class="checkbox-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="has_refill" value="1">
                        <span>Has Refill</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="not_for_sale" value="1">
                        <span>Not For Sale</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="high_value" value="1">
                        <span>High Value</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="fast_moving" value="1">
                        <span>Fast Moving</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="controlled" value="1">
                        <span>Controlled Substance</span>
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" name="track_expiry" value="1" checked>
                        <span>Track Expiry Dates</span>
                    </label>
                </div>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="itemForm">
            <i class="fas fa-save"></i> Save Item
        </button>
    `;
    
    showModal('New Inventory Item', content, footer);
    unitRowCount = 1; // Reset counter
}

let unitRowCount = 1;

function addUnitRow() {
    const container = document.getElementById('unitsContainer');
    const row = document.createElement('div');
    row.className = 'form-row';
    row.id = `unitRow${unitRowCount}`;
    row.innerHTML = `
        <div class="form-group">
            <input type="text" class="form-input" name="unit_name_${unitRowCount}" placeholder="Enter unit name">
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
    
    // Build item data - map fields to our schema
    const itemData = {
        company_id: CONFIG.COMPANY_ID,
        name: formData.get('name'),
        generic_name: formData.get('generic_name') || null,
        sku: formData.get('sku') || null,
        barcode: formData.get('barcode') || null,
        // Store additional info in category (or extend schema later)
        // For now, combine category with other metadata
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
        // Show loading state
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn?.innerHTML;
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        }
        
        await API.items.create(itemData);
        showToast('Item created successfully!', 'success');
        closeModal();
        
        // Reload with delay to allow modal close animation
        setTimeout(() => {
            if (window.loadItems) window.loadItems();
            if (window.loadInventory) window.loadInventory();
        }, 100);
    } catch (error) {
        console.error('Error saving item:', error);
        showToast(error.message || 'Error creating item', 'error');
        
        // Re-enable button on error
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Save Item';
        }
    }
}

function downloadItemTemplate() {
    if (typeof XLSX === 'undefined') {
        showToast('Excel library not loaded. Please refresh the page.', 'error');
        return;
    }
    
    // Template headers exactly matching pharmasight_template.xlsx
    const headers = [
        'Item name*',
        'Item code',
        'Description',
        'Category',
        'Base Unit (x)',
        'Secondary Unit (y)',
        'Conversion Rate (n) (x = ny)',
        'Supplier',
        'markup_Margin',
        'Price_List_Retail_Price',
        'Price_List_Wholesale_Price',
        'Price_List_Trade_Price',
        'Price_List_Last_Cost',
        'Price_List_Average_Cost',
        'Price_List_Retail_Unit_Price',
        'Price_List_Wholesale_Unit_Price',
        'Price_List_Trade_Unit_Price',
        'Price_List_Tax_Code',
        'Price_List_Tax_Percentage',
        'Price_List_Tax_Description',
        'Price_List_Tax_Type',
        'Price_List_Price_Inclusive',
        'Current stock quantity',
        'Minimum stock quantity',
        'HSN',
        'Sale Discount',
        'Tax Rate',
        'Inclusive Of Tax',
        'Price_List_Min_Price',
        'Price_List_Special_Price',
        'Price_List_Has_Refill',
        'Price_List_Not_For_Sale',
        'Price_List_Is_Physical_Item',
        'Price_List_Min_Wholesale_Price',
        'Price_List_Min_Wholesale_Unit_Price',
        'Price_List_Min_Retail_Price',
        'Price_List_Min_Retail_Unit_Price',
        'Price_List_Min_Trade_Price',
        'Price_List_Min_Trade_Unit_Price'
    ];
    
    // Create workbook and worksheet
    const wb = XLSX.utils.book_new();
    const ws = XLSX.utils.aoa_to_sheet([headers]);
    
    // Set column widths for better readability
    const colWidths = headers.map((header, idx) => {
        // Calculate width based on header length, with minimums
        const baseWidth = Math.max(header.length + 2, 12);
        return { wch: Math.min(baseWidth, 40) };
    });
    ws['!cols'] = colWidths;
    
    // Add worksheet to workbook with exact sheet name
    XLSX.utils.book_append_sheet(wb, ws, 'Pharmasight Template');
    
    // Generate file and download (matching original filename)
    const fileName = `pharmasight_template.xlsx`;
    XLSX.writeFile(wb, fileName);
    
    showToast('Template downloaded! Fill it with your items and upload.', 'success');
}

function showImportExcelModal() {
    const content = `
        <div>
            <div class="alert alert-info">
                <i class="fas fa-info-circle"></i>
                <p><strong>Excel Import Instructions:</strong></p>
                <ol style="margin-top: 0.5rem; padding-left: 1.5rem;">
                    <li>Click "Download Template" to get the Excel template with required headers</li>
                    <li>Fill in your items (don't change the headers)</li>
                    <li>Select your filled file below and click Import</li>
                    <li><strong>Required:</strong> Item name*, Purchase price, Base Unit (x)</li>
                </ol>
            </div>
            <div class="form-group">
                <label class="form-label">Select Excel File (.xlsx or .xls)</label>
                <input type="file" id="excelFileInput" class="form-input" accept=".xlsx,.xls" onchange="handleFileSelect(event)">
            </div>
            <div id="excelPreview" style="display: none; margin-top: 1rem;">
                <h4>Preview (first 5 rows):</h4>
                <div id="excelPreviewContent" class="table-container" style="max-height: 300px; overflow-y: auto;"></div>
                <p style="margin-top: 0.5rem; color: var(--text-secondary);">
                    <span id="excelRowCount">0</span> rows found. Ready to import?
                </p>
            </div>
            <div id="excelError" class="alert alert-danger" style="display: none; margin-top: 1rem;"></div>
        </div>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" id="importExcelBtn" onclick="importExcelFile()" disabled>
            <i class="fas fa-upload"></i> Import Items
        </button>
    `;
    
    showModal('Import Items from Excel', content, footer);
    
    // Reset file input
    setTimeout(() => {
        const fileInput = document.getElementById('excelFileInput');
        if (fileInput) fileInput.value = '';
        window.excelFileData = null;
    }, 100);
}

let excelFileData = null;

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const errorDiv = document.getElementById('excelError');
    const previewDiv = document.getElementById('excelPreview');
    const previewContent = document.getElementById('excelPreviewContent');
    const rowCount = document.getElementById('excelRowCount');
    const importBtn = document.getElementById('importExcelBtn');
    
    errorDiv.style.display = 'none';
    previewDiv.style.display = 'none';
    importBtn.disabled = true;
    excelFileData = null;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            if (typeof XLSX === 'undefined') {
                throw new Error('XLSX library not loaded. Please refresh the page.');
            }
            
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, {type: 'array'});
            const sheetName = workbook.SheetNames[0];
            const worksheet = workbook.Sheets[sheetName];
            const jsonData = XLSX.utils.sheet_to_json(worksheet, {defval: ''});
            
            if (jsonData.length === 0) {
                throw new Error('No data found in Excel file');
            }
            
            excelFileData = jsonData;
            
            // Show preview
            const previewRows = jsonData.slice(0, 5);
            const headers = Object.keys(jsonData[0]);
            
            let previewHTML = '<table style="width: 100%; font-size: 0.875rem;"><thead><tr>';
            headers.forEach(h => previewHTML += `<th style="padding: 0.5rem; border: 1px solid var(--border-color);">${h}</th>`);
            previewHTML += '</tr></thead><tbody>';
            
            previewRows.forEach(row => {
                previewHTML += '<tr>';
                headers.forEach(h => {
                    previewHTML += `<td style="padding: 0.5rem; border: 1px solid var(--border-color);">${row[h] || ''}</td>`;
                });
                previewHTML += '</tr>';
            });
            previewHTML += '</tbody></table>';
            
            previewContent.innerHTML = previewHTML;
            rowCount.textContent = jsonData.length;
            previewDiv.style.display = 'block';
            importBtn.disabled = false;
            
        } catch (error) {
            console.error('Excel parsing error:', error);
            errorDiv.style.display = 'block';
            errorDiv.innerHTML = `<strong>Error:</strong> ${error.message}`;
        }
    };
    
    reader.readAsArrayBuffer(file);
}

// Prevent multiple simultaneous imports
let isImporting = false;

async function importExcelFile() {
    // Prevent multiple simultaneous imports
    if (isImporting) {
        showToast('Import already in progress. Please wait...', 'warning');
        return;
    }
    
    if (!excelFileData || excelFileData.length === 0) {
        showToast('No data to import', 'error');
        return;
    }
    
    const importBtn = document.getElementById('importExcelBtn');
    const modalBody = document.querySelector('.modal-body');
    
    if (!modalBody) {
        showToast('Error: Modal not found', 'error');
        return;
    }
    
    // Set importing flag
    isImporting = true;
    
    // Add progress indicator
    let progressHTML = `
        <div id="importProgress" style="margin-top: 1rem; padding: 1rem; background: var(--bg-secondary); border-radius: 4px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                <span>Processing items...</span>
                <span id="progressText">0 / ${excelFileData.length}</span>
            </div>
            <div style="width: 100%; height: 20px; background: var(--border-color); border-radius: 10px; overflow: hidden;">
                <div id="progressBar" style="height: 100%; background: var(--primary); width: 0%; transition: width 0.3s;"></div>
            </div>
            <div id="importStatus" style="margin-top: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);"></div>
        </div>
    `;
    modalBody.insertAdjacentHTML('beforeend', progressHTML);
    
    importBtn.disabled = true;
    importBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importing...';
    
    // Helper function to safely get string value (defined at function scope)
    const safeString = (value, defaultValue = '') => {
        if (value === null || value === undefined || value === 'None') {
            return defaultValue;
        }
        const str = String(value).trim();
        return str || defaultValue;
    };
    
    // ============================================
    // STEP 1: Extract and create suppliers FIRST (INDEPENDENT of items)
    // ============================================
    const supplierMap = new Map(); // Map supplier name -> supplier_id
    let supplierExtractionComplete = false;
    let supplierStats = { created: 0, skipped: 0, errors: 0 };
    
    try {
        const uniqueSuppliers = new Set();
        
        // First, let's check what column names exist in the Excel file
        const firstRow = excelFileData[0];
        const allColumnNames = Object.keys(firstRow || {});
        console.log('Excel column names:', allColumnNames);
        
        // Try multiple possible column names for supplier
        const supplierColumnNames = [
            'Supplier', 'supplier', 'SUPPLIER',
            'Supplier Name', 'supplier name', 'SUPPLIER NAME',
            'Supplier_Name', 'supplier_name', 'SUPPLIER_NAME',
            'Vendor', 'vendor', 'VENDOR',
            'Vendor Name', 'vendor name', 'VENDOR NAME'
        ];
        
        // Find the actual supplier column name
        let supplierColumnName = null;
        for (const colName of supplierColumnNames) {
            if (allColumnNames.includes(colName)) {
                supplierColumnName = colName;
                console.log(`Found supplier column: "${colName}"`);
                break;
            }
        }
        
        // Collect unique suppliers from Excel
        if (supplierColumnName) {
            for (let idx = 0; idx < excelFileData.length; idx++) {
                const row = excelFileData[idx];
                const supplierName = safeString(row[supplierColumnName]);
                if (supplierName && supplierName.trim() !== '' && supplierName.trim() !== 'None') {
                    uniqueSuppliers.add(supplierName.trim());
                }
            }
            console.log(`Found ${uniqueSuppliers.size} unique suppliers in Excel`);
        } else {
            console.warn('Supplier column not found in Excel. Available columns:', allColumnNames);
            showToast('Warning: Supplier column not found in Excel file. Suppliers will not be imported.', 'warning');
        }
        
        // Create suppliers in bulk (INDEPENDENT of item processing)
        if (uniqueSuppliers.size > 0) {
            const progressStatus = document.getElementById('importStatus');
            if (progressStatus) {
                progressStatus.innerHTML = `Step 1/2: Creating ${uniqueSuppliers.size} suppliers...`;
            }
            
            // Load existing suppliers once
            let existingSuppliers = [];
            try {
                existingSuppliers = await API.suppliers.list(CONFIG.COMPANY_ID);
                console.log(`Loaded ${existingSuppliers.length} existing suppliers`);
            } catch (error) {
                console.error('Error loading existing suppliers:', error);
                showToast('Error loading existing suppliers. Will create new ones.', 'warning');
            }
            
            for (const supplierName of uniqueSuppliers) {
                try {
                    // Check if supplier already exists
                    const existing = existingSuppliers.find(s => s.name.toLowerCase() === supplierName.toLowerCase());
                    
                    if (existing) {
                        supplierMap.set(supplierName, existing.id);
                        supplierStats.skipped++;
                        console.log(`Supplier already exists: ${supplierName}`);
                    } else {
                        // Create new supplier
                        console.log(`Creating supplier: ${supplierName}`);
                        const newSupplier = await API.suppliers.create({
                            company_id: CONFIG.COMPANY_ID,
                            name: supplierName
                        });
                        supplierMap.set(supplierName, newSupplier.id);
                        // Add to existing list to avoid duplicates in same import
                        existingSuppliers.push(newSupplier);
                        supplierStats.created++;
                        console.log(`✅ Created supplier: ${supplierName} (ID: ${newSupplier.id})`);
                    }
                } catch (error) {
                    console.error(`❌ Error creating supplier ${supplierName}:`, error);
                    supplierStats.errors++;
                    // Continue with other suppliers even if one fails
                }
            }
            
            supplierExtractionComplete = true;
            
            if (progressStatus) {
                progressStatus.innerHTML = `Step 1/2 Complete: Suppliers - ${supplierStats.created} created, ${supplierStats.skipped} skipped, ${supplierStats.errors} errors. Starting item import...`;
            }
            
            // Show supplier results
            if (supplierStats.created > 0) {
                showToast(`✅ Successfully created ${supplierStats.created} supplier(s)`, 'success');
            }
            if (supplierStats.skipped > 0) {
                console.log(`ℹ️ ${supplierStats.skipped} supplier(s) already existed and were skipped`);
            }
            if (supplierStats.errors > 0) {
                showToast(`⚠️ Failed to create ${supplierStats.errors} supplier(s). Check console for details.`, 'warning');
            }
        } else {
            console.warn('No suppliers found in Excel file');
            supplierExtractionComplete = true; // Mark as complete even if no suppliers found
        }
    } catch (error) {
        console.error('❌ Critical error during supplier extraction:', error);
        showToast('Error extracting suppliers, but continuing with item import...', 'warning');
        supplierExtractionComplete = true; // Mark as complete to allow item processing to continue
    }
    
    // ============================================
    // STEP 2: Process items (even if supplier extraction had issues)
    // ============================================
    try {
        let totalSuccessCount = 0;
        let totalErrorCount = 0;
        const allErrors = [];
        
        // Process in batches of 100 items for better performance
        const BATCH_SIZE = 100;
        const batches = [];
        
        // First, map all rows to item data
        const itemDataList = [];
        for (let idx = 0; idx < excelFileData.length; idx++) {
            const row = excelFileData[idx];
            
            // Map template headers to item data (matching pharmasight_template.xlsx structure)
            // Safely convert to string and handle null/undefined/None
            const itemNameRaw = row['Item name*'] || row['Item name'] || '';
            const itemName = (itemNameRaw === null || itemNameRaw === undefined || itemNameRaw === 'None') 
                ? '' 
                : String(itemNameRaw).trim();
            
            // Skip rows without item name
            if (!itemName || itemName === '') {
                totalErrorCount++;
                allErrors.push({ index: idx, name: 'Missing name', error: 'Missing "Item name*" (required)' });
                continue;
            }
            
            // Use Price_List_Last_Cost as purchase price, fallback to Price_List_Average_Cost
            let purchasePrice = parseFloat(
                row['Price_List_Last_Cost'] || 
                row['Price_List_Average_Cost'] || 
                row['Purchase price'] || 
                0
            );
            // Validate purchase price (must be >= 0, not NaN)
            if (isNaN(purchasePrice) || purchasePrice < 0) {
                purchasePrice = 0;
            }
            
            // Get base unit - must not be empty
            // Handle None/null values from Excel (openpyxl returns None for empty cells)
            let baseUnitRaw = row['Base Unit (x)'] || row['Base Unit'] || row['Base unit'];
            if (baseUnitRaw === null || baseUnitRaw === undefined || baseUnitRaw === 'None' || baseUnitRaw === '') {
                baseUnitRaw = 'PCS'; // Default fallback
            }
            let baseUnit = String(baseUnitRaw).trim();
            if (!baseUnit || baseUnit === '' || baseUnit === 'None') {
                baseUnit = 'PCS'; // Default fallback
            }
            baseUnit = baseUnit.toUpperCase();
            
            // Map Excel row to item data
            // VAT Classification (Kenya Pharmacy Context)
            // Handle None/null values properly
            let taxPercentageRaw = row['Price_List_Tax_Percentage'];
            if (taxPercentageRaw === null || taxPercentageRaw === undefined || taxPercentageRaw === 'None' || taxPercentageRaw === '') {
                taxPercentageRaw = row['Tax Rate'] || 0;
            }
            let taxPercentage = parseFloat(taxPercentageRaw) || 0;
            // Validate VAT rate (must be 0-100)
            if (isNaN(taxPercentage) || taxPercentage < 0) {
                taxPercentage = 0;
            } else if (taxPercentage > 100) {
                taxPercentage = 16; // Default to standard rate if invalid
            }
            
            // Handle tax code - if None/null, infer from percentage
            let taxCodeRaw = row['Price_List_Tax_Code'];
            let taxCode;
            if (taxCodeRaw === null || taxCodeRaw === undefined || taxCodeRaw === 'None' || taxCodeRaw === '') {
                taxCode = (taxPercentage === 0 ? 'ZERO_RATED' : taxPercentage === 16 ? 'STANDARD' : null);
            } else {
                taxCode = taxCodeRaw;
            }
            
            // Handle price inclusive - check for None/null
            let priceInclusiveRaw = row['Price_List_Price_Inclusive'];
            const priceInclusive = (priceInclusiveRaw !== null && priceInclusiveRaw !== undefined && priceInclusiveRaw !== 'None' && priceInclusiveRaw !== '')
                ? (String(priceInclusiveRaw).toLowerCase() === 'true' || String(priceInclusiveRaw) === '1')
                : false;
            
            // Helper function to safely get string value
            const safeString = (value, defaultValue = '') => {
                if (value === null || value === undefined || value === 'None') {
                    return defaultValue;
                }
                const str = String(value).trim();
                return str || defaultValue;
            };
            
            const itemData = {
                company_id: CONFIG.COMPANY_ID,
                name: itemName,
                generic_name: safeString(row['Description']) || null,
                sku: safeString(row['Item code'] || row['Item Code']) || null,
                category: safeString(row['Category']) || null,
                base_unit: baseUnit,
                default_cost: purchasePrice,
                // VAT Classification (from Excel)
                is_vatable: taxCode !== 'EXEMPT',  // EXEMPT items are not vatable
                vat_rate: taxPercentage,
                // Only include vat_code if it's a valid string (not null/undefined)
                ...(taxCode && typeof taxCode === 'string' ? { vat_code: taxCode } : {}),
                price_includes_vat: priceInclusive,
                units: []
            };
            
            // Add base unit conversion (always required)
            // Validate base_unit is not empty (already validated above, but double-check)
            if (!itemData.base_unit || itemData.base_unit === '') {
                totalErrorCount++;
                allErrors.push({ 
                    index: idx, 
                    name: itemName || 'Unknown', 
                    error: 'Base Unit is required and cannot be empty' 
                });
                continue;
            }
            
            itemData.units.push({
                unit_name: itemData.base_unit,
                multiplier_to_base: 1.0,
                is_default: true
            });
            
            // Add secondary unit conversion if provided
            const secondaryUnitRaw = row['Secondary Unit (y)'] || row['Secondary Unit'] || row['Secondary unit'];
            const secondaryUnit = safeString(secondaryUnitRaw);
            let conversionRate = parseFloat(row['Conversion Rate (n) (x = ny)'] || row['Conversion Rate'] || row['Conversion rate'] || 0);
            
            // Validate conversion rate
            if (isNaN(conversionRate) || conversionRate <= 0) {
                conversionRate = 0;
            }
            
            if (secondaryUnit && secondaryUnit !== '' && conversionRate > 0) {
                itemData.units.push({
                    unit_name: secondaryUnit.toUpperCase(),
                    multiplier_to_base: conversionRate,
                    is_default: false
                });
            }
            
            // Final validation before adding to list
            // Ensure all required fields are valid
            if (!itemData.name || itemData.name.trim() === '') {
                totalErrorCount++;
                allErrors.push({ 
                    index: idx, 
                    name: 'Unknown', 
                    error: 'Item name is required and cannot be empty' 
                });
                continue;
            }
            
            if (!itemData.base_unit || itemData.base_unit.trim() === '') {
                totalErrorCount++;
                allErrors.push({ 
                    index: idx, 
                    name: itemData.name, 
                    error: 'Base unit is required and cannot be empty' 
                });
                continue;
            }
            
            // Validate units array - ensure all multipliers are > 0
            const invalidUnits = itemData.units.filter(u => !u.multiplier_to_base || u.multiplier_to_base <= 0);
            if (invalidUnits.length > 0) {
                totalErrorCount++;
                allErrors.push({ 
                    index: idx, 
                    name: itemData.name, 
                    error: `Invalid unit multipliers: ${invalidUnits.map(u => u.unit_name).join(', ')}` 
                });
                continue;
            }
            
            // Ensure name is not too long (backend max is 255)
            if (itemData.name.length > 255) {
                itemData.name = itemData.name.substring(0, 255);
            }
            
            // Ensure default_cost is valid (>= 0)
            if (isNaN(itemData.default_cost) || itemData.default_cost < 0) {
                itemData.default_cost = 0;
            }
            
            itemDataList.push(itemData);
        }
        
        // Split into batches
        for (let i = 0; i < itemDataList.length; i += BATCH_SIZE) {
            batches.push(itemDataList.slice(i, i + BATCH_SIZE));
        }
        
        // Process batches
        for (let batchIdx = 0; batchIdx < batches.length; batchIdx++) {
            const batch = batches[batchIdx];
            const processedCount = batchIdx * BATCH_SIZE;
            const progress = Math.round((processedCount / excelFileData.length) * 100);
            
            // Update progress
            document.getElementById('progressText').textContent = `${processedCount} / ${excelFileData.length}`;
            document.getElementById('progressBar').style.width = `${progress}%`;
            document.getElementById('importStatus').textContent = `Processing batch ${batchIdx + 1} of ${batches.length} (${batch.length} items)...`;
            
            try {
                // Send batch to backend
                const result = await API.items.bulkCreate({
                    company_id: CONFIG.COMPANY_ID,
                    items: batch
                });
                
                totalSuccessCount += result.created || 0;
                totalErrorCount += result.errors || 0;
                
                // Handle skipped items (duplicates)
                if (result.skipped && result.skipped > 0) {
                    console.log(`Batch ${batchIdx + 1}: ${result.skipped} items skipped (already exist)`);
                }
                
                if (result.error_details && result.error_details.length > 0) {
                    allErrors.push(...result.error_details);
                }
                
            } catch (error) {
                // If batch fails, extract detailed error information
                console.warn(`Batch ${batchIdx + 1} failed:`, error);
                
                // Try to extract validation errors from response
                let errorDetails = error.message || 'Unknown error';
                if (error.data && error.data.detail) {
                    if (Array.isArray(error.data.detail)) {
                        // Pydantic validation errors
                        errorDetails = error.data.detail.map(err => {
                            const field = err.loc ? err.loc.join('.') : 'unknown';
                            return `${field}: ${err.msg}`;
                        }).join('; ');
                    } else {
                        errorDetails = error.data.detail;
                    }
                }
                
                // If batch fails, try individual items to get specific errors
                console.log(`Trying individual items for batch ${batchIdx + 1}...`);
                for (let itemIdx = 0; itemIdx < batch.length; itemIdx++) {
                    const item = batch[itemIdx];
                    try {
                        const result = await API.items.bulkCreate({
                            company_id: CONFIG.COMPANY_ID,
                            items: [item]
                        });
                        if (result.created > 0) {
                            totalSuccessCount++;
                        } else {
                            totalErrorCount++;
                            allErrors.push({
                                index: processedCount + itemIdx,
                                name: item.name,
                                error: result.error_details?.[0]?.error || errorDetails
                            });
                        }
                    } catch (itemError) {
                        totalErrorCount++;
                        let itemErrorMsg = itemError.message || 'Validation failed';
                        if (itemError.data && itemError.data.detail) {
                            if (Array.isArray(itemError.data.detail)) {
                                // Pydantic validation errors
                                itemErrorMsg = itemError.data.detail.map(err => {
                                    const field = err.loc ? err.loc.join('.') : 'unknown';
                                    return `${field}: ${err.msg}`;
                                }).join('; ');
                            } else if (typeof itemError.data.detail === 'string') {
                                itemErrorMsg = itemError.data.detail;
                            } else {
                                itemErrorMsg = JSON.stringify(itemError.data.detail);
                            }
                        }
                        // Log detailed error for debugging
                        console.warn(`Item validation failed:`, {
                            name: item.name,
                            error: itemErrorMsg,
                            itemData: {
                                name: item.name,
                                base_unit: item.base_unit,
                                default_cost: item.default_cost,
                                units_count: item.units?.length,
                                units: item.units?.map(u => ({
                                    unit_name: u.unit_name,
                                    multiplier: u.multiplier_to_base
                                }))
                            }
                        });
                        allErrors.push({
                            index: processedCount + itemIdx,
                            name: item.name,
                            error: itemErrorMsg
                        });
                    }
                }
            }
            
            // Small delay to prevent overwhelming the server
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        
        // Final progress update
        const progressStatus = document.getElementById('importStatus');
        if (progressStatus) {
            progressStatus.innerHTML = `Step 2/2 Complete: Items - ${totalSuccessCount} imported, ${totalErrorCount} failed. Import completed!`;
        }
        document.getElementById('progressText').textContent = `${excelFileData.length} / ${excelFileData.length}`;
        document.getElementById('progressBar').style.width = '100%';
        
        closeModal();
        
        // Show supplier results summary
        if (supplierExtractionComplete) {
            console.log(`\n📊 SUPPLIER IMPORT SUMMARY:`);
            console.log(`   ✅ Created: ${supplierStats.created}`);
            console.log(`   ⏭️  Skipped (already exist): ${supplierStats.skipped}`);
            console.log(`   ❌ Errors: ${supplierStats.errors}`);
        }
        
        // Show item results
        if (totalSuccessCount > 0) {
            let message = `✅ Items: ${totalSuccessCount} imported`;
            if (totalErrorCount > 0) {
                message += `, ${totalErrorCount} failed`;
            }
            if (supplierStats.created > 0) {
                message += ` | ✅ Suppliers: ${supplierStats.created} created`;
            }
            showToast(message, 'success');
            loadItems();
        } else if (totalErrorCount === 0 && excelFileData.length > 0) {
            // All items were skipped (duplicates)
            let message = `ℹ️ All items already exist (skipped duplicates)`;
            if (supplierStats.created > 0) {
                message += ` | ✅ Suppliers: ${supplierStats.created} created`;
            }
            showToast(message, 'info');
            loadItems();
        } else {
            let message = `❌ Items: All ${totalErrorCount} failed`;
            if (supplierStats.created > 0) {
                message += ` | ✅ Suppliers: ${supplierStats.created} created successfully`;
            }
            showToast(message, 'error');
        }
        
        if (totalErrorCount > 0 && allErrors.length > 0) {
            console.log('Item import errors:', allErrors.slice(0, 50)); // Log first 50 errors
            if (allErrors.length > 50) {
                console.log(`... and ${allErrors.length - 50} more errors`);
            }
        }
        
    } catch (error) {
        console.error('❌ Item import error:', error);
        
        // Show supplier results even if items failed
        if (supplierExtractionComplete && supplierStats.created > 0) {
            showToast(`⚠️ Item import failed, but ${supplierStats.created} supplier(s) were created successfully`, 'warning');
        } else {
            showToast(`Import failed: ${error.message}`, 'error');
        }
        
        importBtn.disabled = false;
        importBtn.innerHTML = '<i class="fas fa-upload"></i> Import Items';
    } finally {
        // Always reset importing flag
        isImporting = false;
    }
}

async function editItem(itemId) {
    // Fetch full item details from API (works from any page)
    let item;
    try {
        item = await API.items.get(itemId);
        // Also check if we have overview data (for has_transactions flag)
        if (!item.has_transactions && itemsList.length > 0) {
            const overviewItem = itemsList.find(i => i.id === itemId);
            if (overviewItem && overviewItem.has_transactions !== undefined) {
                item.has_transactions = overviewItem.has_transactions;
            }
        }
    } catch (error) {
        console.error('Error fetching item details:', error);
        showToast('Item not found', 'error');
        return;
    }
    
    const hasTransactions = item.has_transactions || false;
    const isLocked = hasTransactions;
    
    const content = `
        <form id="editItemForm" onsubmit="updateItem(event, '${itemId}')" style="max-height: 70vh; overflow-y: auto;">
            ${isLocked ? `
                <div class="alert alert-warning" style="margin-bottom: 1rem;">
                    <i class="fas fa-lock"></i>
                    <strong>Locked Fields:</strong> This item has inventory transactions. 
                    Base unit and unit conversions cannot be modified to maintain data integrity.
                </div>
            ` : ''}
            
            <!-- Item Details Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-info-circle"></i> Item Details
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">
                            Item Code (SKU)
                            <i class="fas fa-lock" style="color: #dc3545; margin-left: 0.25rem;" title="SKU is immutable once created"></i>
                        </label>
                        <input 
                            type="text" 
                            class="form-input" 
                            name="sku" 
                            value="${escapeHtml(item.sku || '')}" 
                            readonly 
                            disabled
                            style="background-color: #f5f5f5; cursor: not-allowed;"
                            title="SKU cannot be modified once created"
                        >
                    </div>
                    <div class="form-group">
                        <label class="form-label">Barcode</label>
                        <input type="text" class="form-input" name="barcode" value="${escapeHtml(item.barcode || '')}" placeholder="Scan or enter barcode">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Item Name *</label>
                    <input type="text" class="form-input" name="name" value="${escapeHtml(item.name)}" required>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">Generic Name</label>
                        <input type="text" class="form-input" name="generic_name" value="${escapeHtml(item.generic_name || '')}" placeholder="Enter generic name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Category</label>
                        <input type="text" class="form-input" name="category" value="${escapeHtml(item.category || '')}" placeholder="Enter category">
                    </div>
                </div>
            </div>

            <!-- Base Unit Section (Locked if has transactions) -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-ruler"></i> Unit Configuration
                    ${isLocked ? '<i class="fas fa-lock" style="color: #dc3545; margin-left: 0.5rem;" title="Locked after first transaction"></i>' : ''}
                </div>
                <div class="form-group">
                    <label class="form-label">
                        Base Unit *
                        ${isLocked ? '<i class="fas fa-lock" style="color: #dc3545; margin-left: 0.25rem;" title="Cannot be modified after item has transactions"></i>' : ''}
                    </label>
                    <select 
                        class="form-select" 
                        name="base_unit" 
                        required
                        ${isLocked ? 'disabled style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                        title="${isLocked ? 'Base unit is locked because item has inventory transactions' : 'Base unit for this item'}"
                    >
                        <option value="tablet" ${item.base_unit === 'tablet' ? 'selected' : ''}>Tablet</option>
                        <option value="capsule" ${item.base_unit === 'capsule' ? 'selected' : ''}>Capsule</option>
                        <option value="ml" ${item.base_unit === 'ml' ? 'selected' : ''}>ML (Milliliter)</option>
                        <option value="gram" ${item.base_unit === 'gram' ? 'selected' : ''}>Gram</option>
                        <option value="piece" ${item.base_unit === 'piece' ? 'selected' : ''}>Piece</option>
                        <option value="packet" ${item.base_unit === 'packet' ? 'selected' : ''}>Packet</option>
                        <option value="bottle" ${item.base_unit === 'bottle' ? 'selected' : ''}>Bottle</option>
                        <option value="tube" ${item.base_unit === 'tube' ? 'selected' : ''}>Tube</option>
                        <option value="sachet" ${item.base_unit === 'sachet' ? 'selected' : ''}>Sachet</option>
                        <option value="vial" ${item.base_unit === 'vial' ? 'selected' : ''}>Vial</option>
                        <option value="box" ${item.base_unit === 'box' ? 'selected' : ''}>Box</option>
                    </select>
                    ${isLocked ? '<input type="hidden" name="base_unit" value="' + escapeHtml(item.base_unit) + '">' : ''}
                </div>
                
                <!-- Units Display - Editable -->
                <div class="form-group" style="margin-top: 1rem;">
                    <label class="form-label">Unit Conversions</label>
                    <p style="color: var(--text-secondary); font-size: 0.875rem; margin: 0.5rem 0;">
                        Base unit: <strong>${escapeHtml(item.base_unit)}</strong> (Price is per ${escapeHtml(item.base_unit)})
                    </p>
                    <div id="unitsEditContainer" style="margin-top: 0.5rem;">
                        ${(item.units && item.units.length > 0) ? `
                            ${item.units.map((u, idx) => {
                                const multiplier = Number(u.multiplier_to_base);
                                const isLargerUnit = multiplier >= 1;
                                return `
                                <div class="unit-edit-row" data-unit-id="${u.id || ''}" style="display: flex; gap: 0.5rem; align-items: center; padding: 0.75rem; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 0.25rem; margin-bottom: 0.5rem;">
                                    <div style="flex: 1;">
                                        <label class="form-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">Unit Name</label>
                                        <input 
                                            type="text" 
                                            class="form-input unit-name-input" 
                                            value="${escapeHtml(u.unit_name)}" 
                                            placeholder="e.g., TAB, CARTON"
                                            ${isLocked ? 'readonly style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                                            data-unit-id="${u.id || ''}"
                                        >
                                    </div>
                                    <div style="flex: 1;">
                                        <label class="form-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">
                                            ${isLargerUnit ? `1 ${escapeHtml(u.unit_name)} = ? ${escapeHtml(item.base_unit)}` : `1 ${escapeHtml(item.base_unit)} = ? ${escapeHtml(u.unit_name)}`}
                                        </label>
                                        <input 
                                            type="number" 
                                            class="form-input unit-multiplier-input" 
                                            value="${isLargerUnit ? multiplier : (1 / multiplier)}" 
                                            step="0.01" 
                                            min="0.01"
                                            placeholder="Enter rate"
                                            ${isLocked ? 'readonly style="background-color: #f5f5f5; cursor: not-allowed;"' : ''}
                                            data-unit-id="${u.id || ''}"
                                            data-is-larger="${isLargerUnit}"
                                        >
                                    </div>
                                    <div style="display: flex; flex-direction: column; gap: 0.25rem; align-items: center; min-width: 120px;">
                                        <label class="checkbox-item" style="margin: 0;">
                                            <input 
                                                type="checkbox" 
                                                class="unit-default-checkbox" 
                                                ${u.is_default ? 'checked' : ''}
                                                ${isLocked ? 'disabled' : ''}
                                                data-unit-id="${u.id || ''}"
                                            >
                                            <span style="font-size: 0.875rem;">Default</span>
                                        </label>
                                        ${!isLocked ? `
                                            <button 
                                                type="button" 
                                                class="btn btn-outline btn-sm remove-unit-btn" 
                                                style="padding: 0.25rem 0.5rem; font-size: 0.75rem;"
                                                data-unit-id="${u.id || ''}"
                                                onclick="removeEditUnitRow(this)"
                                            >
                                                <i class="fas fa-trash"></i> Remove
                                            </button>
                                        ` : ''}
                                    </div>
                                    <input type="hidden" class="unit-id-input" value="${u.id || ''}">
                                </div>
                            `;
                            }).join('')}
                        ` : `
                            <p style="color: var(--text-secondary); padding: 0.75rem; background: var(--bg-color); border-radius: 0.25rem; text-align: center;">
                                No secondary units. Item uses base unit (${escapeHtml(item.base_unit)}) only.
                            </p>
                        `}
                    </div>
                    ${!isLocked ? `
                        <button 
                            type="button" 
                            class="btn btn-outline" 
                            onclick="addEditUnitRow('${itemId}', '${escapeHtml(item.base_unit)}')"
                            style="margin-top: 0.5rem;"
                        >
                            <i class="fas fa-plus"></i> Add Secondary Unit
                        </button>
                    ` : ''}
                    ${isLocked ? `
                        <div class="alert alert-info" style="margin-top: 0.5rem;">
                            <i class="fas fa-lock"></i>
                            Unit conversions cannot be modified after item has inventory transactions. 
                            View units using the <i class="fas fa-cubes"></i> button.
                        </div>
                    ` : ''}
                </div>
            </div>

            <!-- Pricing Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-dollar-sign"></i> Pricing
                </div>
                <div class="form-group">
                    <label class="form-label">Default Cost per Base Unit</label>
                    <input type="number" class="form-input" name="default_cost" value="${item.default_cost || 0}" step="0.01" min="0" required>
                </div>
            </div>

            <!-- VAT Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-receipt"></i> VAT Classification
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">VAT Rate (%)</label>
                        <input type="number" class="form-input" name="vat_rate" value="${item.vat_rate || 0}" step="0.01" min="0" max="100">
                    </div>
                    <div class="form-group">
                        <label class="form-label">VAT Code</label>
                        <select class="form-select" name="vat_code">
                            <option value="">Select VAT Code</option>
                            <option value="ZERO_RATED" ${item.vat_code === 'ZERO_RATED' ? 'selected' : ''}>Zero Rated</option>
                            <option value="STANDARD" ${item.vat_code === 'STANDARD' ? 'selected' : ''}>Standard (16%)</option>
                            <option value="EXEMPT" ${item.vat_code === 'EXEMPT' ? 'selected' : ''}>Exempt</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="price_includes_vat" ${item.price_includes_vat ? 'checked' : ''}>
                        <span>Price includes VAT</span>
                    </label>
                </div>
            </div>

            <!-- Status Section -->
            <div class="form-section">
                <div class="form-section-title">
                    <i class="fas fa-toggle-on"></i> Status & Attributes
                </div>
                <div class="form-group">
                    <label class="checkbox-item">
                        <input type="checkbox" name="is_active" ${item.is_active ? 'checked' : ''}>
                        <span>Item is active</span>
                    </label>
                </div>
                <div class="form-group" style="margin-top: 1rem;">
                    <div class="checkbox-group">
                        <label class="checkbox-item">
                            <input type="checkbox" name="is_controlled" ${item.is_controlled ? 'checked' : ''}>
                            <span>Controlled Substance</span>
                        </label>
                        <label class="checkbox-item">
                            <input type="checkbox" name="is_cold_chain" ${item.is_cold_chain ? 'checked' : ''}>
                            <span>Cold Chain Required</span>
                        </label>
                    </div>
                </div>
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button type="submit" form="editItemForm" class="btn btn-primary">
            <i class="fas fa-save"></i> Update Item
        </button>
    `;
    
    showModal('Edit Item', content, footer, 'modal-large');
    
    // Store has_transactions in modal for quick access during update (avoids extra API call)
    const modal = document.getElementById('modal');
    if (modal) {
        modal.setAttribute('data-has-transactions', hasTransactions.toString());
    }
    
    // Add event listeners to existing unit name inputs for dynamic label updates
    setTimeout(() => {
        const allNameInputs = document.querySelectorAll('.unit-name-input');
        allNameInputs.forEach(input => {
            if (!input.hasAttribute('data-listener-added')) {
                input.setAttribute('data-listener-added', 'true');
                input.addEventListener('input', function() {
                    const row = this.closest('.unit-edit-row');
                    const nameDisplay = row?.querySelector('.unit-name-display');
                    if (nameDisplay) {
                        nameDisplay.textContent = this.value || this.getAttribute('value') || 'UNIT';
                    }
                });
            }
        });
    }, 100);
}

async function updateItem(event, itemId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    // Get has_transactions from the form data attribute (set when modal opens)
    // This avoids an extra API call
    const formElement = form.closest('.modal') || form;
    const hasTransactionsAttr = formElement.getAttribute('data-has-transactions');
    let hasTransactions = false;
    
    if (hasTransactionsAttr !== null) {
        hasTransactions = hasTransactionsAttr === 'true';
    } else {
        // Fallback: try to get from cached item data if available
        // This is a last resort - normally we set it when opening the modal
        try {
            const item = await API.items.get(itemId);
            hasTransactions = item.has_transactions || false;
        } catch (error) {
            console.warn('Could not fetch item for transaction check, assuming false:', error);
            hasTransactions = false;
        }
    }
    
    const updateData = {
        name: formData.get('name'),
        generic_name: formData.get('generic_name') || null,
        barcode: formData.get('barcode') || null,
        category: formData.get('category') || null,
        default_cost: parseFloat(formData.get('default_cost')) || 0,
        vat_rate: parseFloat(formData.get('vat_rate')) || 0,
        vat_code: formData.get('vat_code') || null,
        price_includes_vat: formData.has('price_includes_vat'),
        is_active: formData.has('is_active')
    };
    
    // Only include base_unit if item doesn't have transactions
    if (!hasTransactions && formData.get('base_unit')) {
        updateData.base_unit = formData.get('base_unit');
    }
    
    // Collect units data (only if not locked)
    if (!hasTransactions) {
        const units = [];
        const unitRows = document.querySelectorAll('.unit-edit-row');
        
        unitRows.forEach(row => {
            const unitId = row.querySelector('.unit-id-input')?.value || null;
            const unitName = row.querySelector('.unit-name-input')?.value?.trim();
            const multiplierInput = row.querySelector('.unit-multiplier-input');
            const multiplierValue = parseFloat(multiplierInput?.value);
            const isLarger = multiplierInput?.dataset.isLarger === 'true';
            const isDefault = row.querySelector('.unit-default-checkbox')?.checked || false;
            
            if (unitName && multiplierValue && multiplierValue > 0) {
                // Convert multiplier based on unit type
                // If isLarger: multiplier is already correct (e.g., 100 means 1 CARTON = 100 packets)
                // If not isLarger: we need to invert (e.g., if user enters 100, it means 1 packet = 100 tabs, so multiplier = 1/100 = 0.01)
                const multiplier = isLarger ? multiplierValue : (1 / multiplierValue);
                
                units.push({
                    id: unitId || null,
                    unit_name: unitName,
                    multiplier_to_base: multiplier,
                    is_default: isDefault
                });
            }
        });
        
        // Only include units if there are any (or if explicitly empty to remove all)
        updateData.units = units;
    }
    
    // SKU is never included (immutable)
    
    try {
        await API.items.update(itemId, updateData);
        showToast('Item updated successfully!', 'success');
        closeModal();
        // Reload current page - works for both items.js and inventory.js
        if (window.loadItems) window.loadItems();
        if (window.loadInventory) window.loadInventory();
    } catch (error) {
        console.error('Error updating item:', error);
        const errorMsg = error.data?.detail || error.message || 'Error updating item';
        showToast(errorMsg, 'error');
    }
}

async function viewItemUnits(itemId) {
    // Fetch item from API (works from any page)
    let item;
    try {
        item = await API.items.get(itemId);
    } catch (error) {
        console.error('Error fetching item for units view:', error);
        showToast('Item not found', 'error');
        return;
    }
    
    const unitsList = (item.units || []).map(u => 
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

// Add unit row function for edit modal
function addEditUnitRow(itemId, baseUnit) {
    const container = document.getElementById('unitsEditContainer');
    if (!container) return;
    
    // Check if container has the "no units" message
    const noUnitsMsg = container.querySelector('p');
    if (noUnitsMsg) {
        container.innerHTML = '';
    }
    
    const newRow = document.createElement('div');
    newRow.className = 'unit-edit-row';
    newRow.setAttribute('data-unit-id', '');
    newRow.style.cssText = 'display: flex; gap: 0.5rem; align-items: center; padding: 0.75rem; background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 0.25rem; margin-bottom: 0.5rem;';
    
    newRow.innerHTML = `
        <div style="flex: 1;">
            <label class="form-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">Unit Name</label>
            <input 
                type="text" 
                class="form-input unit-name-input" 
                placeholder="e.g., TAB, CARTON"
                data-unit-id=""
            >
        </div>
        <div style="flex: 1;">
            <label class="form-label unit-conversion-label" style="font-size: 0.875rem; margin-bottom: 0.25rem;">
                1 <span class="unit-name-display">NEW_UNIT</span> = ? ${escapeHtml(baseUnit)}
            </label>
            <input 
                type="number" 
                class="form-input unit-multiplier-input" 
                value="1" 
                step="0.01" 
                min="0.01"
                placeholder="Enter rate"
                data-unit-id=""
                data-is-larger="true"
            >
        </div>
        <div style="display: flex; flex-direction: column; gap: 0.25rem; align-items: center; min-width: 120px;">
            <label class="checkbox-item" style="margin: 0;">
                <input 
                    type="checkbox" 
                    class="unit-default-checkbox" 
                    data-unit-id=""
                >
                <span style="font-size: 0.875rem;">Default</span>
            </label>
            <button 
                type="button" 
                class="btn btn-outline btn-sm remove-unit-btn" 
                style="padding: 0.25rem 0.5rem; font-size: 0.75rem;"
                data-unit-id=""
                onclick="removeEditUnitRow(this)"
            >
                <i class="fas fa-trash"></i> Remove
            </button>
        </div>
        <input type="hidden" class="unit-id-input" value="">
    `;
    
    container.appendChild(newRow);
    
    // Update unit name display when user types
    const nameInput = newRow.querySelector('.unit-name-input');
    const nameDisplay = newRow.querySelector('.unit-name-display');
    const baseUnitText = baseUnit;
    
    if (nameInput && nameDisplay) {
        nameInput.addEventListener('input', function() {
            const unitName = this.value || 'NEW_UNIT';
            nameDisplay.textContent = unitName;
        });
    }
}

// Remove unit row function for edit modal
function removeEditUnitRow(button) {
    const row = button.closest('.unit-edit-row');
    if (row) {
        row.remove();
        
        // If no units left, show message
        const container = document.getElementById('unitsEditContainer');
        if (container && container.querySelectorAll('.unit-edit-row').length === 0) {
            const baseUnit = document.querySelector('select[name="base_unit"]')?.value || 'base unit';
            container.innerHTML = `
                <p style="color: var(--text-secondary); padding: 0.75rem; background: var(--bg-color); border-radius: 0.25rem; text-align: center;">
                    No secondary units. Item uses base unit (${escapeHtml(baseUnit)}) only.
                </p>
            `;
        }
    }
}

// Export
window.loadItems = loadItems;
window.showAddItemModal = showAddItemModal;
window.showImportExcelModal = showImportExcelModal;
window.downloadItemTemplate = downloadItemTemplate;
window.handleFileSelect = handleFileSelect;
window.importExcelFile = importExcelFile;
window.addUnitRow = addUnitRow;
window.removeUnitRow = removeUnitRow;
window.saveItem = saveItem;
window.editItem = editItem;
window.updateItem = updateItem;
window.viewItemUnits = viewItemUnits;
window.filterItems = filterItems;
// Export unit editing functions (for edit modal)
window.addEditUnitRow = addEditUnitRow;
window.removeEditUnitRow = removeEditUnitRow;

