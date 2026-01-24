// Unified Stock Take Page
// Automatically shows admin or counter interface based on user role

// IMMEDIATE TEST - This should appear in console if script loads
console.log('[STOCK TAKE] ===== SCRIPT FILE LOADED =====');
if (typeof window !== 'undefined') {
    console.log('[STOCK TAKE] window object is available');
} else {
    console.error('[STOCK TAKE] window object is NOT available!');
}

let currentSession = null;
let currentUserId = null;
let userRole = null;
let progressPollingInterval = null;

// Define function first
async function loadStockTake() {
    console.log('[STOCK TAKE] loadStockTake called');
    const page = document.getElementById('stock-take');
    if (!page) {
        console.error('[STOCK TAKE] Page element not found');
        return;
    }
    
    try {
        // Check if CONFIG and API are available
        if (typeof CONFIG === 'undefined') {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>Configuration not loaded. Please refresh the page.</p>
                    </div>
                </div>
            `;
            return;
        }
        
        if (typeof API === 'undefined' || !API.stockTake) {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>API not loaded. Please refresh the page.</p>
                    </div>
                </div>
            `;
            return;
        }
        
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
        
        // Determine user role
        userRole = await getUserRole();
        console.log('[STOCK TAKE] User role determined:', userRole);
        
        // Render appropriate interface
        if (userRole === 'admin' || userRole === 'auditor' || userRole === 'Super Admin' || userRole === 'super admin') {
            console.log('[STOCK TAKE] Loading admin interface');
            await loadAdminInterface();
        } else {
            console.log('[STOCK TAKE] Loading counter interface');
            await loadCounterInterface();
        }
    } catch (error) {
        console.error('[STOCK TAKE] Error loading stock take:', error);
        console.error('[STOCK TAKE] Error stack:', error.stack);
        const page = document.getElementById('stock-take');
        if (page) {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle"></i>
                        <h3>Error Loading Stock Take</h3>
                        <p>${error.message || 'Unknown error occurred'}</p>
                        <pre style="font-size: 0.75rem; margin-top: 1rem; overflow: auto;">${error.stack || ''}</pre>
                    </div>
                </div>
            `;
        }
    }
}

async function getUserRole() {
    try {
        // Get user's role for current branch
        const usersResponse = await API.users.list();
        const currentUser = usersResponse.users.find(u => u.id === currentUserId);
        
        if (currentUser && currentUser.branch_roles) {
            const branchRole = currentUser.branch_roles.find(br => br.branch_id === CONFIG.BRANCH_ID);
            if (branchRole) {
                return branchRole.role_name.toLowerCase();
            }
        }
        
        // Fallback: check if user is admin (common case)
        return 'counter'; // Default to counter if can't determine
    } catch (error) {
        console.error('Error getting user role:', error);
        return 'counter';
    }
}

async function loadAdminInterface() {
    // Use admin page function directly - it now supports stock-take page ID
    if (typeof window.renderStockTakeAdminPage === 'function') {
        window.renderStockTakeAdminPage();
        if (typeof window.loadSessions === 'function') {
            await window.loadSessions();
        }
    } else {
        renderAdminInterface();
        await loadSessions();
    }
}

async function loadCounterInterface() {
    // Use counter page function directly - it now supports stock-take page ID
    if (typeof window.renderStockTakeCounterPage === 'function') {
        window.renderStockTakeCounterPage();
        if (typeof window.checkActiveSession === 'function') {
            await window.checkActiveSession();
        }
    } else {
        renderCounterInterface();
        await checkActiveSession();
    }
}

// Admin Interface Functions (from stock_take_admin.js)
function renderAdminInterface() {
    const page = document.getElementById('stock-take');
    if (!page) return;
    
    page.innerHTML = `
        <div style="background: white; border-radius: 8px; padding: 1.5rem; box-shadow: var(--shadow);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <h2 style="margin: 0;"><i class="fas fa-clipboard-list"></i> Stock Take Management</h2>
                <button class="btn btn-primary" onclick="showCreateSessionModal()">
                    <i class="fas fa-plus"></i> New Session
                </button>
            </div>
            
            <div id="sessionsList" style="margin-bottom: 2rem;">
                <div class="spinner"></div>
            </div>
            
            <div id="sessionDetails" style="display: none;">
                <div class="card" style="margin-top: 2rem;">
                    <h3 id="sessionDetailsTitle"></h3>
                    <div id="sessionDetailsContent"></div>
                </div>
            </div>
        </div>
    `;
}

async function loadSessions() {
    const container = document.getElementById('sessionsList');
    if (!container) return;
    
    try {
        const sessions = await API.stockTake.listSessions(CONFIG.BRANCH_ID);
        
        if (sessions.length === 0) {
            container.innerHTML = `
                <div style="padding: 3rem; text-align: center; color: var(--text-secondary);">
                    <i class="fas fa-clipboard-list" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                    <p style="font-size: 1.1rem;">No stock take sessions found</p>
                    <p style="font-size: 0.875rem;">Create a new session to get started</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = `
            <div class="table-container">
                <table style="width: 100%;">
                    <thead>
                        <tr>
                            <th>Session Code</th>
                            <th>Status</th>
                            <th>Created By</th>
                            <th>Counters</th>
                            <th>Items Counted</th>
                            <th>Created At</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${sessions.map(session => `
                            <tr>
                                <td><strong>${escapeHtml(session.session_code)}</strong></td>
                                <td>
                                    <span class="badge ${getStatusBadgeClass(session.status)}">
                                        ${escapeHtml(session.status)}
                                    </span>
                                </td>
                                <td>${escapeHtml(session.creator_name || 'Unknown')}</td>
                                <td>${session.counter_count}</td>
                                <td>${session.total_items_counted}</td>
                                <td>${formatDate(session.created_at)}</td>
                                <td>
                                    <button class="btn btn-outline" onclick="viewSessionDetails('${session.id}')" title="View Details">
                                        <i class="fas fa-eye"></i>
                                    </button>
                                    ${session.status === 'DRAFT' ? `
                                        <button class="btn btn-success" onclick="startSession('${session.id}')" title="Start Session">
                                            <i class="fas fa-play"></i>
                                        </button>
                                    ` : ''}
                                    ${session.status === 'ACTIVE' ? `
                                        <button class="btn btn-warning" onclick="pauseSession('${session.id}')" title="Pause Session">
                                            <i class="fas fa-pause"></i>
                                        </button>
                                    ` : ''}
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    } catch (error) {
        console.error('Error loading sessions:', error);
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle"></i>
                <p>Error loading sessions: ${error.message}</p>
            </div>
        `;
    }
}

// Counter Interface Functions (from stock_take_counter.js)
function renderCounterInterface() {
    const page = document.getElementById('stock-take');
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
            await loadCounterInterfaceContent();
        } else {
            showJoinSessionInterface();
        }
    } catch (error) {
        console.error('Error checking active session:', error);
        showJoinSessionInterface();
    }
}

async function loadCounterInterfaceContent() {
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

// Helper functions
function getStatusBadgeClass(status) {
    const classes = {
        'DRAFT': 'badge-secondary',
        'ACTIVE': 'badge-success',
        'PAUSED': 'badge-warning',
        'COMPLETED': 'badge-info',
        'CANCELLED': 'badge-danger'
    };
    return classes[status] || 'badge-secondary';
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
        year: 'numeric', 
        month: 'short', 
        day: 'numeric', 
        hour: '2-digit', 
        minute: '2-digit' 
    });
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

// Missing counter functions - implement them here
let countingItemId = null;
let itemLocks = {};
let searchTimeout = null;

async function loadMyCounts() {
    if (!currentSession || !currentUserId) return;
    
    try {
        const counts = await API.stockTake.listCounts(currentSession.id, currentUserId);
        
        const tableContainer = document.getElementById('myCountsTable');
        if (!tableContainer) return;
        
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
            const progressDisplay = document.getElementById('progressDisplay');
            if (progressDisplay) {
                progressDisplay.textContent = `${counts.length} items counted`;
            }
        }
    } catch (error) {
        console.error('Error loading my counts:', error);
    }
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
            await loadCounterInterfaceContent();
            showNotification('Successfully joined session', 'success');
        } else {
            alert(result.message || 'Failed to join session');
        }
    } catch (error) {
        console.error('Error joining session:', error);
        alert('Error joining session: ' + error.message);
    }
}

async function searchItemForCounting() {
    const input = document.getElementById('itemSearchInput');
    if (!input) return;
    
    const searchTerm = input.value.trim();
    const resultsContainer = document.getElementById('itemSearchResults');
    
    if (searchTerm.length < 2) {
        if (resultsContainer) resultsContainer.innerHTML = '';
        return;
    }
    
    // Debounce search
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            if (resultsContainer) resultsContainer.innerHTML = '<div class="spinner"></div>';
            
            const items = await API.items.search(searchTerm, CONFIG.COMPANY_ID, 10, CONFIG.BRANCH_ID, false);
            
            if (!resultsContainer) return;
            
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
            if (resultsContainer) {
                resultsContainer.innerHTML = `
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle"></i>
                        Error searching items: ${error.message}
                    </div>
                `;
            }
        }
    }, 300);
}

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
                await refreshLocks();
                return;
            }
            throw error;
        }
        
        countingItemId = itemId;
        
        // Get system stock
        const stock = await API.inventory.getStock(itemId, CONFIG.BRANCH_ID);
        
        // Show counting interface
        const countingInterface = document.getElementById('countingInterface');
        if (countingInterface) {
            countingInterface.style.display = 'block';
            document.getElementById('countingItemName').textContent = itemName;
            document.getElementById('countingItemDetails').innerHTML = `
                <p><strong>Base Unit:</strong> ${baseUnit}</p>
                <p><strong>System Stock:</strong> ${stock || 0} ${baseUnit}</p>
            `;
            document.getElementById('countedQuantity').value = '';
            document.getElementById('shelfLocation').value = '';
            document.getElementById('countNotes').value = '';
            
            // Scroll to counting interface
            countingInterface.scrollIntoView({ behavior: 'smooth' });
        }
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
        const searchInput = document.getElementById('itemSearchInput');
        if (searchInput) searchInput.value = '';
        const searchResults = document.getElementById('itemSearchResults');
        if (searchResults) searchResults.innerHTML = '';
        
        showNotification('Count saved successfully', 'success');
    } catch (error) {
        console.error('Error saving count:', error);
        alert('Error saving count: ' + error.message);
    }
}

function cancelCounting() {
    countingItemId = null;
    const countingInterface = document.getElementById('countingInterface');
    if (countingInterface) {
        countingInterface.style.display = 'none';
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

// Export functions to window object IMMEDIATELY
// Using IIFE to ensure export happens as soon as script loads
console.log('[STOCK TAKE] Setting up exports...');
(function() {
    'use strict';
    function exportFunctions() {
        try {
            if (typeof window !== 'undefined') {
                console.log('[STOCK TAKE] Exporting functions, checking availability...');
                console.log('[STOCK TAKE] loadStockTake type:', typeof loadStockTake);
                
                if (typeof loadStockTake === 'function') {
                    window.loadStockTake = loadStockTake;
                    console.log('[STOCK TAKE] ✓ loadStockTake exported');
                } else {
                    console.error('[STOCK TAKE] ✗ loadStockTake is not a function! Type:', typeof loadStockTake);
                }
                
                if (typeof joinSession === 'function') {
                    window.joinSession = joinSession;
                }
                if (typeof searchItemForCounting === 'function') {
                    window.searchItemForCounting = searchItemForCounting;
                }
                if (typeof startCountingItem === 'function') {
                    window.startCountingItem = startCountingItem;
                }
                if (typeof saveCount === 'function') {
                    window.saveCount = saveCount;
                }
                if (typeof cancelCounting === 'function') {
                    window.cancelCounting = cancelCounting;
                }
                
                console.log('✓ Stock Take functions exported to window:', {
                    loadStockTake: typeof window.loadStockTake,
                    joinSession: typeof window.joinSession,
                    searchItemForCounting: typeof window.searchItemForCounting,
                    startCountingItem: typeof window.startCountingItem,
                    saveCount: typeof window.saveCount,
                    cancelCounting: typeof window.cancelCounting
                });
            } else {
                console.error('[STOCK TAKE] window is undefined!');
            }
        } catch (error) {
            console.error('✗ Error exporting stock take functions:', error);
            console.error('✗ Error stack:', error.stack);
        }
    }
    
    // Export immediately
    console.log('[STOCK TAKE] Calling exportFunctions() immediately...');
    exportFunctions();
    
    // Also export on DOM ready (in case functions aren't hoisted yet)
    if (document.readyState === 'loading') {
        console.log('[STOCK TAKE] DOM still loading, will export on DOMContentLoaded');
        document.addEventListener('DOMContentLoaded', function() {
            console.log('[STOCK TAKE] DOMContentLoaded fired, exporting again...');
            exportFunctions();
        });
    } else {
        // DOM already loaded, export now
        console.log('[STOCK TAKE] DOM already loaded, exporting with setTimeout...');
        setTimeout(function() {
            console.log('[STOCK TAKE] setTimeout fired, exporting again...');
            exportFunctions();
        }, 0);
    }
})();

console.log('[STOCK TAKE] Script loaded, exports complete');

// SIMPLE EXPORT - Like dashboard.js pattern
// This is the simplest possible export that should always work
try {
    console.log('[STOCK TAKE] Attempting simple export...');
    console.log('[STOCK TAKE] loadStockTake function exists?', typeof loadStockTake);
    
    if (typeof window !== 'undefined' && typeof loadStockTake === 'function') {
        window.loadStockTake = loadStockTake;
        window.joinSession = joinSession;
        window.searchItemForCounting = searchItemForCounting;
        window.startCountingItem = startCountingItem;
        window.saveCount = saveCount;
        window.cancelCounting = cancelCounting;
        
        console.log('[STOCK TAKE] ✓✓✓ SIMPLE EXPORT SUCCESSFUL ✓✓✓');
        console.log('[STOCK TAKE] window.loadStockTake type:', typeof window.loadStockTake);
    } else {
        console.error('[STOCK TAKE] ✗✗✗ SIMPLE EXPORT FAILED ✗✗✗');
        console.error('[STOCK TAKE] window exists?', typeof window !== 'undefined');
        console.error('[STOCK TAKE] loadStockTake is function?', typeof loadStockTake === 'function');
    }
} catch (e) {
    console.error('[STOCK TAKE] ✗✗✗ EXCEPTION IN SIMPLE EXPORT ✗✗✗', e);
    console.error('[STOCK TAKE] Exception stack:', e.stack);
}
