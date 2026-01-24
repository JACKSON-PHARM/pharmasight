// Stock Take Counter Interface
// For counters to count items in assigned sessions

let currentSession = null;
let currentUserId = null;
let itemLocks = {};
let progressPollingInterval = null;

async function loadStockTakeCounter() {
    // Support both stock-take-counter and unified stock-take page
    const page = document.getElementById('stock-take-counter') || document.getElementById('stock-take');
    if (!page) return;
    
    try {
        if (!CONFIG.COMPANY_ID || !CONFIG.BRANCH_ID) {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>Please set up your company and branch first.</p>
                    </div>
                </div>
            `;
            return;
        }
        
        // Get current user
        currentUserId = await getCurrentUserId();
        if (!currentUserId) {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle"></i>
                        <p>Unable to identify current user. Please log in again.</p>
                    </div>
                </div>
            `;
            return;
        }
        
        renderStockTakeCounterPage();
        await checkActiveSession();
    } catch (error) {
        console.error('Error loading stock take counter:', error);
        page.innerHTML = `
            <div class="card">
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>Error loading stock take counter: ${error.message}</p>
                </div>
            </div>
        `;
    }
}

function renderStockTakeCounterPage() {
    // Support both stock-take-counter and unified stock-take page
    const page = document.getElementById('stock-take-counter') || document.getElementById('stock-take');
    if (!page) return;
    
    page.innerHTML = `
        <div style="background: white; border-radius: 8px; padding: 1.5rem; box-shadow: var(--shadow);">
            <div id="sessionStatus" style="margin-bottom: 2rem;">
                <div class="spinner"></div>
            </div>
            
            <div id="counterInterface" style="display: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                    <h2 style="margin: 0;">
                        <i class="fas fa-clipboard-check"></i> 
                        Stock Take: <span id="sessionCodeDisplay"></span>
                    </h2>
                    <div>
                        <span id="progressDisplay" class="badge badge-info" style="font-size: 1rem; padding: 0.5rem 1rem;"></span>
                    </div>
                </div>
                
                <div class="card" style="margin-bottom: 1.5rem;">
                    <h4>Your Assignment</h4>
                    <div id="assignedShelves"></div>
                </div>
                
                <div style="margin-bottom: 1.5rem;">
                    <label style="display: block; margin-bottom: 0.5rem; font-weight: bold;">
                        <i class="fas fa-search"></i> Search Item to Count
                    </label>
                    <input 
                        type="text" 
                        id="itemSearchInput" 
                        class="form-input" 
                        placeholder="Type item name or SKU to search..."
                        style="max-width: 400px;"
                        oninput="searchItemForCounting()"
                    >
                </div>
                
                <div id="itemSearchResults" style="margin-bottom: 2rem;"></div>
                
                <div id="countingInterface" style="display: none;">
                    <div class="card" style="background: #f8f9fa;">
                        <h4 id="countingItemName"></h4>
                        <div id="countingItemDetails"></div>
                        <div style="margin-top: 1rem;">
                            <label>Counted Quantity (Base Units)</label>
                            <input 
                                type="number" 
                                id="countedQuantity" 
                                class="form-input" 
                                min="0"
                                style="max-width: 200px;"
                            >
                        </div>
                        <div style="margin-top: 1rem;">
                            <label>Shelf Location (Optional)</label>
                            <input 
                                type="text" 
                                id="shelfLocation" 
                                class="form-input" 
                                placeholder="e.g., A1, B3, etc."
                                style="max-width: 200px;"
                            >
                        </div>
                        <div style="margin-top: 1rem;">
                            <label>Notes (Optional)</label>
                            <textarea 
                                id="countNotes" 
                                class="form-input" 
                                rows="2"
                                placeholder="Any additional notes..."
                            ></textarea>
                        </div>
                        <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
                            <button class="btn btn-primary" onclick="saveCount()">
                                <i class="fas fa-save"></i> Save Count
                            </button>
                            <button class="btn btn-secondary" onclick="cancelCounting()">
                                Cancel
                            </button>
                        </div>
                    </div>
                </div>
                
                <div id="myCountsList" style="margin-top: 2rem;">
                    <h4>My Counts</h4>
                    <div id="myCountsTable"></div>
                </div>
            </div>
            
            <div id="joinSessionInterface" style="display: none;">
                <div class="card" style="text-align: center; padding: 3rem;">
                    <h3>Join Stock Take Session</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        Enter the session code provided by your supervisor
                    </p>
                    <div style="max-width: 300px; margin: 0 auto;">
                        <input 
                            type="text" 
                            id="sessionCodeInput" 
                            class="form-input" 
                            placeholder="e.g., ST-MAR25A"
                            style="text-transform: uppercase; text-align: center; font-size: 1.2rem; letter-spacing: 0.1em;"
                        >
                        <button class="btn btn-primary" style="width: 100%; margin-top: 1rem;" onclick="joinSession()">
                            <i class="fas fa-sign-in-alt"></i> Join Session
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

async function checkActiveSession() {
    try {
        const sessions = await API.stockTake.listSessions(CONFIG.BRANCH_ID, 'ACTIVE');
        
        // Find session where current user is an allowed counter
        const mySession = sessions.find(s => 
            s.allowed_counters && s.allowed_counters.includes(currentUserId)
        );
        
        if (mySession) {
            currentSession = mySession;
            await loadCounterInterface();
        } else {
            showJoinSessionInterface();
        }
    } catch (error) {
        console.error('Error checking active session:', error);
        showJoinSessionInterface();
    }
}

async function loadCounterInterface() {
    if (!currentSession) return;
    
    document.getElementById('sessionStatus').style.display = 'none';
    document.getElementById('counterInterface').style.display = 'block';
    document.getElementById('joinSessionInterface').style.display = 'none';
    
    document.getElementById('sessionCodeDisplay').textContent = currentSession.session_code;
    
    // Show assigned shelves
    const assignedShelves = currentSession.assigned_shelves[currentUserId] || [];
    const shelvesContainer = document.getElementById('assignedShelves');
    if (assignedShelves.length > 0) {
        shelvesContainer.innerHTML = `
            <p><strong>Assigned Shelves:</strong> ${assignedShelves.join(', ')}</p>
        `;
    } else {
        shelvesContainer.innerHTML = `
            <p style="color: var(--text-secondary);">
                <i class="fas fa-info-circle"></i> 
                You can count items from any shelf in this session.
            </p>
        `;
    }
    
    // Load my counts
    await loadMyCounts();
    
    // Start polling for locks and progress
    startProgressPolling();
}

function showJoinSessionInterface() {
    document.getElementById('sessionStatus').style.display = 'none';
    document.getElementById('counterInterface').style.display = 'none';
    document.getElementById('joinSessionInterface').style.display = 'block';
}

async function joinSession() {
    try {
        const sessionCode = document.getElementById('sessionCodeInput').value.trim().toUpperCase();
        if (!sessionCode) {
            alert('Please enter a session code');
            return;
        }
        
        const result = await API.stockTake.joinSession(sessionCode, currentUserId);
        
        if (result.success) {
            currentSession = result.session;
            await loadCounterInterface();
            showNotification('Successfully joined session', 'success');
        } else {
            alert(result.message || 'Failed to join session');
        }
    } catch (error) {
        console.error('Error joining session:', error);
        alert('Error joining session: ' + error.message);
    }
}

let searchTimeout = null;
async function searchItemForCounting() {
    const input = document.getElementById('itemSearchInput');
    if (!input) return;
    
    const searchTerm = input.value.trim();
    const resultsContainer = document.getElementById('itemSearchResults');
    
    if (searchTerm.length < 2) {
        resultsContainer.innerHTML = '';
        return;
    }
    
    // Debounce search
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            resultsContainer.innerHTML = '<div class="spinner"></div>';
            
            const items = await API.items.search(searchTerm, CONFIG.COMPANY_ID, 10, CONFIG.BRANCH_ID, false);
            
            if (items.length === 0) {
                resultsContainer.innerHTML = '<p style="color: var(--text-secondary);">No items found</p>';
                return;
            }
            
            resultsContainer.innerHTML = `
                <div class="table-container" style="max-height: 400px; overflow-y: auto;">
                    <table style="width: 100%;">
                        <thead>
                            <tr>
                                <th>Item Name</th>
                                <th>SKU</th>
                                <th>Base Unit</th>
                                <th>System Stock</th>
                                <th>Status</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${items.map(item => {
                                const isLocked = itemLocks[item.id];
                                const lockInfo = isLocked ? `<small style="color: orange;"><i class="fas fa-lock"></i> Being counted by ${isLocked.counter_name}</small>` : '';
                                
                                return `
                                    <tr>
                                        <td>${escapeHtml(item.name)}</td>
                                        <td><code>${escapeHtml(item.sku || '—')}</code></td>
                                        <td>${escapeHtml(item.base_unit)}</td>
                                        <td>—</td>
                                        <td>${lockInfo}</td>
                                        <td>
                                            ${!isLocked ? `
                                                <button class="btn btn-primary btn-sm" onclick="startCountingItem('${item.id}', '${escapeHtml(item.name)}', '${escapeHtml(item.base_unit)}')">
                                                    <i class="fas fa-edit"></i> Count
                                                </button>
                                            ` : `
                                                <button class="btn btn-secondary btn-sm" disabled>
                                                    <i class="fas fa-lock"></i> Locked
                                                </button>
                                            `}
                                        </td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (error) {
            console.error('Error searching items:', error);
            resultsContainer.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i>
                    Error searching items: ${error.message}
                </div>
            `;
        }
    }, 300);
}

let countingItemId = null;
async function startCountingItem(itemId, itemName, baseUnit) {
    try {
        // Try to lock the item
        const lockRequest = {
            session_id: currentSession.id,
            item_id: itemId
        };
        
        try {
            await API.stockTake.lockItem(lockRequest, currentUserId);
        } catch (error) {
            if (error.status === 409) {
                alert(error.message || 'Item is being counted by another user');
                await refreshLocks(); // Refresh locks to show who has it
                return;
            }
            throw error;
        }
        
        countingItemId = itemId;
        
        // Get system stock
        const stock = await API.inventory.getStock(itemId, CONFIG.BRANCH_ID);
        
        // Show counting interface
        document.getElementById('countingInterface').style.display = 'block';
        document.getElementById('countingItemName').textContent = itemName;
        document.getElementById('countingItemDetails').innerHTML = `
            <p><strong>Base Unit:</strong> ${baseUnit}</p>
            <p><strong>System Stock:</strong> ${stock || 0} ${baseUnit}</p>
        `;
        document.getElementById('countedQuantity').value = '';
        document.getElementById('shelfLocation').value = '';
        document.getElementById('countNotes').value = '';
        
        // Scroll to counting interface
        document.getElementById('countingInterface').scrollIntoView({ behavior: 'smooth' });
    } catch (error) {
        console.error('Error starting count:', error);
        alert('Error starting count: ' + error.message);
    }
}

async function saveCount() {
    if (!countingItemId || !currentSession) return;
    
    try {
        const countedQuantity = parseInt(document.getElementById('countedQuantity').value);
        if (isNaN(countedQuantity) || countedQuantity < 0) {
            alert('Please enter a valid quantity');
            return;
        }
        
        const countData = {
            session_id: currentSession.id,
            item_id: countingItemId,
            counted_quantity: countedQuantity,
            shelf_location: document.getElementById('shelfLocation').value.trim() || null,
            notes: document.getElementById('countNotes').value.trim() || null
        };
        
        await API.stockTake.createCount(countData, currentUserId);
        
        // Clear counting interface
        cancelCounting();
        
        // Reload my counts
        await loadMyCounts();
        
        // Clear search
        document.getElementById('itemSearchInput').value = '';
        document.getElementById('itemSearchResults').innerHTML = '';
        
        showNotification('Count saved successfully', 'success');
    } catch (error) {
        console.error('Error saving count:', error);
        alert('Error saving count: ' + error.message);
    }
}

function cancelCounting() {
    countingItemId = null;
    document.getElementById('countingInterface').style.display = 'none';
}

async function loadMyCounts() {
    try {
        const counts = await API.stockTake.listCounts(currentSession.id, currentUserId);
        
        const tableContainer = document.getElementById('myCountsTable');
        if (counts.length === 0) {
            tableContainer.innerHTML = '<p style="color: var(--text-secondary);">No counts yet. Start counting items above.</p>';
            return;
        }
        
        tableContainer.innerHTML = `
            <div class="table-container" style="max-height: 400px; overflow-y: auto;">
                <table style="width: 100%;">
                    <thead>
                        <tr>
                            <th>Item</th>
                            <th>Shelf</th>
                            <th>Counted</th>
                            <th>System</th>
                            <th>Variance</th>
                            <th>Time</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${counts.map(count => `
                            <tr>
                                <td>${escapeHtml(count.item_name || 'Unknown')}</td>
                                <td>${escapeHtml(count.shelf_location || '—')}</td>
                                <td><strong>${count.counted_quantity}</strong></td>
                                <td>${count.system_quantity}</td>
                                <td>
                                    <span style="color: ${count.variance === 0 ? 'green' : count.variance > 0 ? 'blue' : 'red'};">
                                        ${count.variance > 0 ? '+' : ''}${count.variance}
                                    </span>
                                </td>
                                <td>${formatDate(count.counted_at)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
        
        // Update progress display
        if (counts.length > 0) {
            document.getElementById('progressDisplay').textContent = `${counts.length} items counted`;
        }
    } catch (error) {
        console.error('Error loading my counts:', error);
    }
}

async function refreshLocks() {
    if (!currentSession) return;
    
    try {
        const locks = await API.stockTake.listLocks(currentSession.id);
        
        // Update itemLocks map
        itemLocks = {};
        locks.forEach(lock => {
            itemLocks[lock.item_id] = {
                counter_name: lock.counter_name,
                expires_at: lock.expires_at
            };
        });
        
        // Re-render search results if visible
        const searchTerm = document.getElementById('itemSearchInput')?.value;
        if (searchTerm && searchTerm.length >= 2) {
            await searchItemForCounting();
        }
    } catch (error) {
        console.error('Error refreshing locks:', error);
    }
}

function startProgressPolling() {
    stopProgressPolling();
    
    progressPollingInterval = setInterval(async () => {
        await refreshLocks();
    }, 5000); // Poll every 5 seconds
}

function stopProgressPolling() {
    if (progressPollingInterval) {
        clearInterval(progressPollingInterval);
        progressPollingInterval = null;
    }
}

async function getCurrentUserId() {
    try {
        if (window.authState && window.authState.user && window.authState.user.id) {
            return window.authState.user.id;
        }
        const userId = localStorage.getItem('userId') || CONFIG.USER_ID;
        return userId;
    } catch (error) {
        console.error('Error getting current user ID:', error);
        return null;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return '—';
    const date = new Date(dateString);
    return date.toLocaleString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert alert-${type}`;
    notification.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 10000; min-width: 300px;';
    notification.innerHTML = `<i class="fas fa-info-circle"></i> ${escapeHtml(message)}`;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Export to window
if (typeof window !== 'undefined') {
    window.loadStockTakeCounter = loadStockTakeCounter;
    window.renderStockTakeCounterPage = renderStockTakeCounterPage;
    window.joinSession = joinSession;
    window.searchItemForCounting = searchItemForCounting;
    window.startCountingItem = startCountingItem;
    window.saveCount = saveCount;
    window.cancelCounting = cancelCounting;
    window.checkActiveSession = checkActiveSession;
}
