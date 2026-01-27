// Unified Stock Take System - Branch-Based with Automatic Participation
// 
// IMPORTANT: NO session codes for users, NO manual joins
// - Users are automatically redirected when they select a branch in stock take mode
// - Session codes exist internally (database requirement) but are NEVER shown to users
// - All users in the branch automatically participate

console.log('[STOCK TAKE] Loading unified module');

// Safe State Management
if (typeof window.stockTake === 'undefined') {
    window.stockTake = {
        currentSession: null,
        userCounts: [],
        itemLocks: {},
        searchTimeout: null,
        currentShelf: null,  // Current shelf being counted
        shelfCounts: [],  // Items counted for current shelf
        countViewMode: 'list'  // 'list' or 'shelf'
    };
}

// Main Load Function
async function loadStockTake() {
    console.log('[STOCK TAKE] loadStockTake called');
    
    const page = document.getElementById('stock-take');
    if (!page) {
        console.error('[STOCK TAKE] Page not found');
        return;
    }
    
    try {
        // Validate dependencies
        if (typeof CONFIG === 'undefined' || !CONFIG.BRANCH_ID) {
            page.innerHTML = `
                <div class="card">
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>Please select a branch first.</p>
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
        
        // Close any open draft modal when loading
        closeDraftModal();
        
        // Check if branch is in stock take mode (with cache busting)
        let branchStatus;
        try {
            branchStatus = await API.stockTake.getBranchStatus(CONFIG.BRANCH_ID);
        } catch (error) {
            console.error('[STOCK TAKE] Error getting branch status:', error);
            // If it's a network error, show helpful message
            if (error.message && (error.message.includes('Failed to fetch') || error.message.includes('Network error'))) {
                throw new Error('Unable to connect to server. Please check if the backend is running on ' + (CONFIG.API_BASE_URL || 'http://localhost:8000'));
            }
            throw error;
        }
        
        if (branchStatus && branchStatus.inStockTake) {
            // Branch is in stock take - check user role
            const role = await getUserRole();
            const isVerifier = role && (role.toLowerCase().includes('verifier') || role.toLowerCase().includes('auditor'));
            
            if (isVerifier) {
                // Verifier sees verification interface
                await renderVerificationInterface();
            } else {
                // Counter sees counting interface
                await renderCountingInterface();
            }
        } else {
            // Branch is normal - show admin interface or message
            await renderBranchNormalInterface();
        }
    } catch (error) {
        console.error('[STOCK TAKE] Error:', error);
        const page = document.getElementById('stock-take');
        if (page) {
            let errorMessage = error.message || 'Unknown error';
            let errorDetail = '';
            
            if (errorMessage.includes('Failed to fetch') || errorMessage.includes('Network error')) {
                errorDetail = '<p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">Please check if the backend server is running on ' + (CONFIG.API_BASE_URL || 'http://localhost:8000') + '</p>';
            } else if (errorMessage.includes('500')) {
                errorDetail = '<p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">Server error. Please check the database migration has been run.</p>';
            }
            
            page.innerHTML = `
                <div class="card">
                    <div style="padding: 2rem; text-align: center;">
                        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
                        <h4>Error Loading Stock Take</h4>
                        <p style="color: var(--text-secondary);">${escapeHtml(errorMessage)}</p>
                        ${errorDetail}
                        <button class="btn btn-primary" onclick="loadStockTake();" style="margin-top: 1rem;">
                            <i class="fas fa-redo"></i> Retry
                        </button>
                    </div>
                </div>
            `;
        }
    }
}

// Branch Normal Interface (When NO stock take active)
async function renderBranchNormalInterface() {
    const page = document.getElementById('stock-take');
    const role = await getUserRole();
    const isVerifier = role && (role.toLowerCase().includes('verifier') || role.toLowerCase().includes('auditor'));
    
    if (isAdminRole(role)) {
        // Admin sees "Start Stock Take" button
        page.innerHTML = `
            <div class="card">
                <div style="padding: 1.5rem; text-align: center;">
                    <i class="fas fa-warehouse" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <h3><i class="fas fa-clipboard-list"></i> Stock Take Management</h3>
                    <h4>Start Stock Take for ${CONFIG.BRANCH_NAME || 'this branch'}</h4>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        Start a stock take session for this branch. All users in this branch will automatically participate.
                    </p>
                    
                    <button class="btn btn-primary btn-lg" onclick="startBranchStockTake()">
                        <i class="fas fa-play-circle"></i> Start Stock Take
                    </button>
                    
                    <div style="margin-top: 2rem;">
                        <small style="color: var(--text-secondary);">
                            <i class="fas fa-info-circle"></i>
                            System will check for pending draft documents before starting.
                        </small>
                        <div style="margin-top: 0.5rem;">
                            <button class="btn btn-link btn-sm" onclick="refreshDraftCheck();" style="padding: 0; color: var(--primary-color);">
                                <i class="fas fa-sync"></i> Refresh Draft Check
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    } else if (isVerifier) {
        // Verifier sees message that no stock take is active
        page.innerHTML = `
            <div class="card">
                <div style="padding: 3rem; text-align: center;">
                    <i class="fas fa-check-circle" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <h4>No Active Stock Take</h4>
                    <p style="color: var(--text-secondary);">
                        There is no active stock take in ${CONFIG.BRANCH_NAME || 'this branch'}.<br>
                        When a stock take is active, you'll be able to verify counted shelves here.
                    </p>
                </div>
            </div>
        `;
    } else {
        // Counter sees "No stock take active" message
        page.innerHTML = `
            <div class="card">
                <div style="padding: 3rem; text-align: center;">
                    <i class="fas fa-clipboard-check" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                    <h4>No Active Stock Take</h4>
                    <p style="color: var(--text-secondary);">
                        There is no active stock take in ${CONFIG.BRANCH_NAME || 'this branch'}.<br>
                        Only administrators can start a stock take session.
                    </p>
                </div>
            </div>
        `;
    }
}

// Admin: Start Stock Take
async function startBranchStockTake() {
    try {
        // Show loading state
        const startBtn = document.querySelector('button[onclick="startBranchStockTake()"]');
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';
        }
        
        // Check for draft documents (with cache busting)
        let hasDrafts;
        try {
            hasDrafts = await API.stockTake.hasDraftDocuments(CONFIG.BRANCH_ID);
        } catch (error) {
            console.error('[STOCK TAKE] Error checking drafts:', error);
            // Continue anyway - backend will handle validation
            hasDrafts = { hasDrafts: false };
        }
        
        if (hasDrafts && hasDrafts.hasDrafts) {
            // Show modal with links to draft documents
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-play-circle"></i> Start Stock Take';
            }
            showDraftDocumentsModal(hasDrafts);
            return;
        }
        
        // Get current user ID
        const userId = await getCurrentUserId();
        if (!userId) {
            throw new Error('Unable to identify current user. Please refresh and try again.');
        }
        
        // Start stock take for branch
        const result = await API.stockTake.startForBranch(CONFIG.BRANCH_ID, userId);
        
        if (result && result.success !== false) {
            showNotification('Stock take started successfully!', 'success');
            // Redirect to stock take page
            window.location.hash = '#stock-take';
            // Reload to refresh interface
            setTimeout(() => {
                loadStockTake();
            }, 500);
        } else {
            throw new Error(result?.message || result?.detail || 'Unknown error occurred');
        }
    } catch (error) {
        console.error('[STOCK TAKE] Start error:', error);
        
        // Restore button state
        const startBtn = document.querySelector('button[onclick="startBranchStockTake()"]');
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fas fa-play-circle"></i> Start Stock Take';
        }
        
        // Show user-friendly error message
        let errorMessage = 'Error starting stock take. ';
        if (error.message) {
            if (error.message.includes('Failed to fetch') || error.message.includes('Network error')) {
                errorMessage += 'Unable to connect to server. Please check if the backend is running.';
            } else if (error.message.includes('500')) {
                errorMessage += 'Server error occurred. Please check the database migration has been run.';
            } else {
                errorMessage += error.message;
            }
        } else {
            errorMessage += 'Please try again or contact support.';
        }
        
        alert(errorMessage);
    }
}

// Show modal with draft documents and links
function showDraftDocumentsModal(draftInfo) {
    const details = draftInfo.details || {};
    const reasons = draftInfo.reasons || [];
    
    // Build links HTML
    let linksHtml = '<div style="margin-top: 1rem;">';
    
    if (details.sales > 0) {
        linksHtml += `
            <a href="#sales" onclick="closeDraftModal(); if(window.loadPage) window.loadPage('sales'); if(window.loadSalesSubPage) setTimeout(() => window.loadSalesSubPage('invoices'), 200);" 
               class="btn btn-outline" style="margin-right: 0.5rem; margin-bottom: 0.5rem;">
                <i class="fas fa-file-invoice"></i> View ${details.sales} Sales Invoice(s)
            </a>
        `;
    }
    
    if (details.purchases > 0) {
        linksHtml += `
            <a href="#purchases" onclick="closeDraftModal(); if(window.loadPage) window.loadPage('purchases'); if(window.loadPurchaseSubPage) setTimeout(() => { window.loadPurchaseSubPage('invoices'); clearPurchaseDateFilters(); }, 200);" 
               class="btn btn-outline" style="margin-right: 0.5rem; margin-bottom: 0.5rem;">
                <i class="fas fa-shopping-bag"></i> View ${details.purchases} Purchase Invoice(s)
            </a>
        `;
    }
    
    if (details.credit_notes > 0) {
        linksHtml += `
            <a href="#sales" onclick="if(window.loadPage) window.loadPage('sales'); closeDraftModal();" 
               class="btn btn-outline" style="margin-right: 0.5rem; margin-bottom: 0.5rem;">
                <i class="fas fa-file-invoice-dollar"></i> View ${details.credit_notes} Credit Note(s)
            </a>
        `;
    }
    
    linksHtml += '</div>';
    
    // Create modal HTML
    const modalHtml = `
        <div id="draftDocumentsModal" class="modal-overlay" style="display: flex; z-index: 10000;">
            <div class="modal" style="max-width: 600px; width: 90%;">
                <div style="padding: 2rem;">
                    <div style="display: flex; align-items: center; margin-bottom: 1.5rem;">
                        <i class="fas fa-exclamation-triangle" style="font-size: 2rem; color: var(--warning-color); margin-right: 1rem;"></i>
                        <h3 style="margin: 0;">Cannot Start Stock Take</h3>
                    </div>
                    
                    <div style="margin-bottom: 1.5rem;">
                        <p style="color: var(--text-primary); margin-bottom: 1rem;">
                            The following draft documents must be finalized or deleted before starting a stock take:
                        </p>
                        <ul style="margin-left: 1.5rem; color: var(--text-secondary);">
                            ${reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
                        </ul>
                    </div>
                    
                    ${linksHtml}
                    
                    <div style="display: flex; gap: 0.5rem; margin-top: 1.5rem; justify-content: flex-end;">
                        <button class="btn btn-secondary" onclick="closeDraftModal(); refreshDraftCheck();">
                            <i class="fas fa-sync"></i> Refresh Check
                        </button>
                        <button class="btn btn-primary" onclick="closeDraftModal();">
                            OK
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    const existing = document.getElementById('draftDocumentsModal');
    if (existing) {
        existing.remove();
    }
    
    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

// Close draft modal
function closeDraftModal() {
    const modal = document.getElementById('draftDocumentsModal');
    if (modal) {
        modal.remove();
    }
}

// Refresh draft check and update UI
async function refreshDraftCheck() {
    try {
        // Force fresh check (no cache)
        const hasDrafts = await API.stockTake.hasDraftDocuments(CONFIG.BRANCH_ID);
        
        console.log('[STOCK TAKE] Draft check result:', hasDrafts);
        
        if (!hasDrafts || !hasDrafts.hasDrafts) {
            // No drafts, show success and allow retry
            showNotification('All draft documents resolved! You can now start stock take.', 'success');
            
            // Refresh the stock take page to update the UI
            setTimeout(() => {
                loadStockTake();
            }, 500);
        } else {
            // Still has drafts, show updated info
            console.log('[STOCK TAKE] Still has drafts:', hasDrafts.details);
            if (hasDrafts.purchase_invoice_ids) {
                console.log('[STOCK TAKE] Draft invoice IDs:', hasDrafts.purchase_invoice_ids);
            }
            showDraftDocumentsModal(hasDrafts);
        }
    } catch (error) {
        console.error('[STOCK TAKE] Refresh draft check error:', error);
        showNotification('Error checking draft documents: ' + error.message, 'error');
    }
}

// Counting Interface (For counters when branch in stock take)
async function renderCountingInterface() {
    const page = document.getElementById('stock-take');
    
    // Check if user has an active shelf
    const currentShelf = window.stockTake.currentShelf;
    
    page.innerHTML = `
        <div style="background: white; border-radius: 8px; padding: 1.5rem; box-shadow: var(--shadow);">
            <!-- Header -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <div>
                    <h2 style="margin: 0;"><i class="fas fa-clipboard-check"></i> Stock Take - ${CONFIG.BRANCH_NAME || 'Active'}</h2>
                    <p style="color: var(--text-secondary); margin: 0;">Counting in progress</p>
                </div>
                <div>
                    <span id="progressBadge" class="badge badge-info" style="font-size: 1rem; padding: 0.5rem 1rem;">Loading...</span>
                </div>
            </div>
            
            ${!currentShelf ? `
            <!-- Shelf Selection (if no active shelf) -->
            <div class="card" style="margin-bottom: 1.5rem; border: 2px solid var(--primary-color);">
                <div style="padding: 1.5rem; text-align: center;">
                    <i class="fas fa-warehouse" style="font-size: 3rem; color: var(--primary-color); margin-bottom: 1rem;"></i>
                    <h3 style="margin: 0 0 1rem 0;">Start Counting a Shelf</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">
                        Enter the shelf name/location you want to count. You'll count all items for this shelf, then submit the shelf count.
                    </p>
                    <div style="max-width: 400px; margin: 0 auto;">
                        <label style="display: block; text-align: left; margin-bottom: 0.5rem; font-weight: 500;">
                            Shelf Name/Location <span style="color: var(--danger-color);">*</span>
                        </label>
                        <input type="text" 
                               id="shelfNameInput" 
                               class="form-input" 
                               placeholder="e.g., A1, Shelf 3, Front Counter"
                               style="width: 100%; margin-bottom: 1rem;"
                               onkeypress="if(event.key === 'Enter') startShelfCounting()"
                               oninput="loadShelfNameSuggestions()">
                        <div id="shelfNameSuggestions" style="margin-top: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);"></div>
                        <button class="btn btn-primary btn-lg" onclick="startShelfCounting()" style="width: 100%;">
                            <i class="fas fa-play"></i> Start Counting This Shelf
                        </button>
                    </div>
                </div>
            </div>
            ` : `
            <!-- Active Shelf Header -->
            <div class="card" style="margin-bottom: 1.5rem; border: 2px solid var(--success-color); background: var(--bg-secondary);">
                <div style="padding: 1rem; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h4 style="margin: 0;">
                            <i class="fas fa-warehouse"></i> Counting Shelf: <strong>${escapeHtml(currentShelf)}</strong>
                        </h4>
                        <p style="margin: 0.5rem 0 0 0; color: var(--text-secondary);">
                            <span id="shelfItemCount">0</span> item(s) counted for this shelf
                        </p>
                    </div>
                    <div>
                        <button class="btn btn-success" onclick="submitShelfCount()" id="submitShelfBtn">
                            <i class="fas fa-check-circle"></i> Submit Shelf Count
                        </button>
                        <button class="btn btn-outline" onclick="cancelShelfCounting()" style="margin-left: 0.5rem;">
                            <i class="fas fa-times"></i> Cancel
                        </button>
                    </div>
                </div>
            </div>
            
            <!-- Search Section -->
            <div class="card" style="margin-bottom: 1.5rem;">
                <div style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                    <h4 style="margin: 0;"><i class="fas fa-search"></i> Search Item to Count</h4>
                </div>
                <div style="padding: 1rem;">
                    <input type="text" 
                           id="stockTakeSearch" 
                           class="form-input" 
                           placeholder="Search by item name, SKU, or barcode..."
                           style="width: 100%; max-width: 500px;"
                           oninput="searchStockTakeItems()">
                    <div id="searchResults" style="margin-top: 1rem;"></div>
                </div>
            </div>
            
            <!-- Counting Form (hidden initially) -->
            <div id="countingFormContainer" style="display: none; margin-bottom: 2rem;">
                <!-- Dynamic content -->
            </div>
            
            <!-- Current Shelf Items -->
            <div class="card" style="margin-bottom: 2rem;">
                <div style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                    <h4 style="margin: 0;"><i class="fas fa-list"></i> Items Counted for ${escapeHtml(currentShelf)}</h4>
                </div>
                <div style="padding: 1rem;">
                    <div id="currentShelfItems">
                        <p style="color: var(--text-secondary); text-align: center;">No items counted yet for this shelf.</p>
                    </div>
                </div>
            </div>
            `}
            
            <!-- My Counts - Tabs for Shelf View and List View -->
            <div class="card" style="margin-bottom: 2rem;">
                <div style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h4 style="margin: 0;"><i class="fas fa-list-check"></i> My Counted Items</h4>
                        <div style="display: flex; gap: 0.5rem;">
                            <button id="viewShelfBtn" class="btn btn-sm btn-outline" onclick="switchCountView('shelf')" style="font-size: 0.875rem;">
                                <i class="fas fa-th-large"></i> By Shelf
                            </button>
                            <button id="viewListBtn" class="btn btn-sm btn-outline active" onclick="switchCountView('list')" style="font-size: 0.875rem;">
                                <i class="fas fa-list"></i> List
                            </button>
                        </div>
                    </div>
                </div>
                <div style="padding: 1rem;">
                    <div id="myCountsList">
                        <div style="text-align: center; padding: 2rem;">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary); margin-top: 1rem;">Loading your counts...</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Admin Controls (only visible to admin) -->
            <div id="adminControls" style="display: none;">
                <div class="card" style="border: 2px solid var(--warning-color);">
                    <div style="padding: 1rem; background: var(--warning-color); color: white;">
                        <h4 style="margin: 0;"><i class="fas fa-user-shield"></i> Administration</h4>
                    </div>
                    <div style="padding: 1.5rem;">
                        <div id="overallProgress" style="margin-bottom: 1rem;"></div>
                        <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                            <button class="btn btn-danger btn-lg" onclick="completeStockTake()">
                                <i class="fas fa-flag-checkered"></i> Complete Stock Take
                            </button>
                            <button class="btn btn-outline-danger btn-lg" onclick="cancelStockTake()">
                                <i class="fas fa-times-circle"></i> Cancel Stock Take
                            </button>
                        </div>
                        <p style="color: var(--text-secondary); margin-top: 1rem; font-size: 0.875rem;">
                            <strong>Complete:</strong> Updates inventory and ends session.<br>
                            <strong>Cancel:</strong> Discards all counts and returns branch to normal.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Load initial data
    if (window.stockTake.currentShelf) {
        await updateShelfItemCount();
    } else {
        await loadMyCounts();
    }
    await updateProgress();
    
    // Show admin controls if user is admin
    const role = await getUserRole();
    if (isAdminRole(role)) {
        const adminControls = document.getElementById('adminControls');
        if (adminControls) {
            adminControls.style.display = 'block';
        }
    }
}

// Verification Interface (For verifiers)
async function renderVerificationInterface() {
    const page = document.getElementById('stock-take');
    
    page.innerHTML = `
        <div style="background: white; border-radius: 8px; padding: 1.5rem; box-shadow: var(--shadow);">
            <!-- Header -->
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <div>
                    <h2 style="margin: 0;"><i class="fas fa-check-circle"></i> Verify Stock Take Counts</h2>
                    <p style="color: var(--text-secondary); margin: 0;">Review and verify counted shelves</p>
                </div>
            </div>
            
            <!-- Shelves List -->
            <div class="card">
                <div style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                    <h4 style="margin: 0;"><i class="fas fa-list"></i> Counted Shelves</h4>
                </div>
                <div style="padding: 1rem;">
                    <div id="shelvesList">
                        <div style="text-align: center; padding: 2rem;">
                            <div class="spinner"></div>
                            <p style="color: var(--text-secondary); margin-top: 1rem;">Loading shelves...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    await loadShelvesForVerification();
}

// Load shelves for verification
async function loadShelvesForVerification() {
    try {
        const shelves = await API.stockTake.getShelves(CONFIG.BRANCH_ID);
        const container = document.getElementById('shelvesList');
        
        if (!container) return;
        
        if (!shelves || shelves.length === 0) {
            container.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 2rem;">No shelves counted yet.</p>';
            return;
        }
        
        // Group by verification status
        const pending = shelves.filter(s => s.verification_status === 'PENDING');
        const approved = shelves.filter(s => s.verification_status === 'APPROVED');
        const rejected = shelves.filter(s => s.verification_status === 'REJECTED');
        
        container.innerHTML = `
            ${pending.length > 0 ? `
            <div style="margin-bottom: 2rem;">
                <h5 style="margin-bottom: 1rem; color: var(--warning-color);">
                    <i class="fas fa-clock"></i> Pending Verification (${pending.length})
                </h5>
                <div style="display: grid; gap: 1rem;">
                    ${pending.map(shelf => `
                        <div class="card" style="border-left: 4px solid var(--warning-color);">
                            <div style="padding: 1rem; display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <h5 style="margin: 0;">
                                        <i class="fas fa-warehouse"></i> ${escapeHtml(shelf.name)}
                                    </h5>
                                    <p style="margin: 0.5rem 0 0 0; color: var(--text-secondary); font-size: 0.875rem;">
                                        ${shelf.item_count || 0} item(s) • Counted by: ${escapeHtml(shelf.counter_name || 'Unknown')}
                                    </p>
                                </div>
                                <div>
                                    <button class="btn btn-primary" onclick="viewShelfForVerification('${escapeHtml(shelf.name)}')">
                                        <i class="fas fa-eye"></i> Review
                                    </button>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}
            
            ${approved.length > 0 ? `
            <div style="margin-bottom: 2rem;">
                <h5 style="margin-bottom: 1rem; color: var(--success-color);">
                    <i class="fas fa-check-circle"></i> Approved (${approved.length})
                </h5>
                <div style="display: grid; gap: 1rem;">
                    ${approved.map(shelf => `
                        <div class="card" style="border-left: 4px solid var(--success-color); opacity: 0.7;">
                            <div style="padding: 1rem; display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <h5 style="margin: 0;">
                                        <i class="fas fa-warehouse"></i> ${escapeHtml(shelf.name)}
                                    </h5>
                                    <p style="margin: 0.5rem 0 0 0; color: var(--text-secondary); font-size: 0.875rem;">
                                        Verified by: ${escapeHtml(shelf.verified_by_name || 'Unknown')} • ${shelf.verified_at ? formatDate(shelf.verified_at) : ''}
                                    </p>
                                </div>
                                <div>
                                    <span class="badge badge-success">Approved</span>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}
            
            ${rejected.length > 0 ? `
            <div style="margin-bottom: 2rem;">
                <h5 style="margin-bottom: 1rem; color: var(--danger-color);">
                    <i class="fas fa-times-circle"></i> Rejected (${rejected.length})
                </h5>
                <div style="display: grid; gap: 1rem;">
                    ${rejected.map(shelf => `
                        <div class="card" style="border-left: 4px solid var(--danger-color);">
                            <div style="padding: 1rem; display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <h5 style="margin: 0;">
                                        <i class="fas fa-warehouse"></i> ${escapeHtml(shelf.name)}
                                    </h5>
                                    <p style="margin: 0.5rem 0 0 0; color: var(--text-secondary); font-size: 0.875rem;">
                                        Rejected by: ${escapeHtml(shelf.verified_by_name || 'Unknown')} • ${shelf.rejection_reason ? escapeHtml(shelf.rejection_reason) : 'No reason provided'}
                                    </p>
                                </div>
                                <div>
                                    <span class="badge badge-danger">Rejected</span>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        `;
        
    } catch (error) {
        console.error('[STOCK TAKE] Load shelves error:', error);
        const container = document.getElementById('shelvesList');
        if (container) {
            container.innerHTML = '<p style="color: var(--text-secondary);">Error loading shelves</p>';
        }
    }
}

// View shelf for verification
async function viewShelfForVerification(shelfName) {
    try {
        const counts = await API.stockTake.getShelfCounts(CONFIG.BRANCH_ID, shelfName);
        
        if (!counts || counts.length === 0) {
            alert('No counts found for this shelf.');
            return;
        }
        
        // Show verification modal
        const modalHtml = `
            <div id="verificationModal" class="modal-overlay" style="display: flex; z-index: 10000;">
                <div class="modal" style="max-width: 800px; width: 90%; max-height: 90vh; overflow-y: auto;">
                    <div style="padding: 2rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                            <h3 style="margin: 0;">
                                <i class="fas fa-warehouse"></i> Verify Shelf: ${escapeHtml(shelfName)}
                            </h3>
                            <button class="btn btn-link" onclick="closeVerificationModal()" style="font-size: 1.5rem; padding: 0;">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                        
                        <div class="table-container" style="max-height: 400px; overflow-y: auto; margin-bottom: 1.5rem;">
                            <table style="width: 100%;">
                                <thead>
                                    <tr>
                                        <th>Item</th>
                                        <th>Batch</th>
                                        <th>Expiry</th>
                                        <th>Unit</th>
                                        <th>Counted</th>
                                        <th>System</th>
                                        <th>Difference</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${counts.map(count => {
                                        const difference = (count.counted_quantity || 0) - (count.system_quantity || 0);
                                        return `
                                            <tr>
                                                <td>${escapeHtml(count.item_name || 'Unknown')}</td>
                                                <td><small>${escapeHtml(count.batch_number || '-')}</small></td>
                                                <td><small>${count.expiry_date ? formatDate(count.expiry_date) : '-'}</small></td>
                                                <td><small>${escapeHtml(count.unit_name || '-')}</small></td>
                                                <td><strong>${count.counted_quantity || 0}</strong></td>
                                                <td>${count.system_quantity || 0}</td>
                                                <td style="color: ${difference === 0 ? 'green' : difference > 0 ? 'blue' : 'red'};">
                                                    ${difference > 0 ? '+' : ''}${difference}
                                                </td>
                                            </tr>
                                        `;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                        
                        <div style="margin-bottom: 1rem;">
                            <label>Rejection Reason (if rejecting):</label>
                            <textarea id="rejectionReason" class="form-input" rows="2" placeholder="Enter reason for rejection..."></textarea>
                        </div>
                        
                        <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                            <button class="btn btn-danger" onclick="rejectShelf('${escapeHtml(shelfName)}')">
                                <i class="fas fa-times-circle"></i> Reject
                            </button>
                            <button class="btn btn-success" onclick="approveShelf('${escapeHtml(shelfName)}')">
                                <i class="fas fa-check-circle"></i> Approve
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Remove existing modal
        const existing = document.getElementById('verificationModal');
        if (existing) existing.remove();
        
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
    } catch (error) {
        console.error('[STOCK TAKE] View shelf error:', error);
        alert('Error loading shelf details: ' + error.message);
    }
}

// Approve shelf
async function approveShelf(shelfName) {
    try {
        const userId = await getCurrentUserId();
        if (!userId) {
            alert('Unable to identify current user.');
            return;
        }
        
        const result = await API.stockTake.approveShelf(CONFIG.BRANCH_ID, shelfName, userId);
        
        if (result && result.success !== false) {
            closeVerificationModal();
            showNotification(`Shelf "${shelfName}" approved successfully!`, 'success');
            await loadShelvesForVerification();
        } else {
            throw new Error(result?.message || result?.detail || 'Failed to approve shelf');
        }
        
    } catch (error) {
        console.error('[STOCK TAKE] Approve shelf error:', error);
        alert('Error approving shelf: ' + (error.message || 'Please try again.'));
    }
}

// Reject shelf
async function rejectShelf(shelfName) {
    try {
        const reason = document.getElementById('rejectionReason')?.value.trim() || '';
        
        if (!confirm(`Reject shelf "${shelfName}"? This will return it to the counter for correction.`)) {
            return;
        }
        
        const userId = await getCurrentUserId();
        if (!userId) {
            alert('Unable to identify current user.');
            return;
        }
        
        const result = await API.stockTake.rejectShelf(CONFIG.BRANCH_ID, shelfName, userId, reason);
        
        if (result && result.success !== false) {
            closeVerificationModal();
            showNotification(`Shelf "${shelfName}" rejected and returned to counter.`, 'warning');
            await loadShelvesForVerification();
        } else {
            throw new Error(result?.message || result?.detail || 'Failed to reject shelf');
        }
        
    } catch (error) {
        console.error('[STOCK TAKE] Reject shelf error:', error);
        alert('Error rejecting shelf: ' + (error.message || 'Please try again.'));
    }
}

// Close verification modal
function closeVerificationModal() {
    const modal = document.getElementById('verificationModal');
    if (modal) {
        modal.remove();
    }
}

// Item Search for Counting
async function searchStockTakeItems() {
    const searchTerm = document.getElementById('stockTakeSearch').value.trim();
    const resultsDiv = document.getElementById('searchResults');
    
    if (!searchTerm || searchTerm.length < 2) {
        resultsDiv.innerHTML = '<p style="color: var(--text-secondary);">Type at least 2 characters to search</p>';
        return;
    }
    
    // Debounce
    clearTimeout(window.stockTake.searchTimeout);
    window.stockTake.searchTimeout = setTimeout(async () => {
        try {
            resultsDiv.innerHTML = '<div style="text-align: center;"><div class="spinner"></div></div>';
            
            const items = await API.items.search(searchTerm, CONFIG.COMPANY_ID, 10, CONFIG.BRANCH_ID, false);
            
            if (!items || items.length === 0) {
                resultsDiv.innerHTML = `<p style="color: var(--text-secondary);">No items found for "${escapeHtml(searchTerm)}"</p>`;
                return;
            }
            
            resultsDiv.innerHTML = `
                <div class="table-container" style="max-height: 400px; overflow-y: auto;">
                    <table style="width: 100%;">
                        <thead>
                            <tr>
                                <th>Item Name</th>
                                <th>SKU</th>
                                <th>Base Unit</th>
                                <th>System Stock</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${items.map(item => `
                                <tr>
                                    <td>${escapeHtml(item.name)}</td>
                                    <td><code>${escapeHtml(item.sku || 'N/A')}</code></td>
                                    <td>${escapeHtml(item.base_unit)}</td>
                                    <td>${item.current_stock || 0}</td>
                                    <td>
                                        <button class="btn btn-primary btn-sm" onclick="selectItemForCounting('${item.id}')">
                                            <i class="fas fa-edit"></i> Count
                                        </button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (error) {
            console.error('[STOCK TAKE] Search error:', error);
            resultsDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
        }
    }, 300);
}

// Select Item for Counting (with transaction check)
async function selectItemForCounting(itemId) {
    try {
        const item = await API.items.get(itemId);
        if (!item) {
            alert('Item not found');
            return;
        }
        
        // Check if item has transactions
        const transactionCheck = await API.items.hasTransactions(itemId, CONFIG.BRANCH_ID);
        const hasTransactions = transactionCheck && transactionCheck.hasTransactions;
        
        // Get current stock
        let currentStock = 0;
        let currentStockDisplay = '0';
        try {
            const stockData = await API.inventory.getStock(itemId, CONFIG.BRANCH_ID);
            // API returns {stock: number, item_id, branch_id, unit: "base_units"}
            if (typeof stockData === 'object' && stockData !== null) {
                currentStock = stockData.stock || stockData.total_quantity || stockData.quantity || 0;
                currentStockDisplay = currentStock.toString();
            } else {
                currentStock = stockData || 0;
                currentStockDisplay = currentStock.toString();
            }
        } catch (e) {
            console.warn('[STOCK TAKE] Could not get stock:', e);
            currentStockDisplay = 'N/A';
        }
        
        // Get item units for unit selection
        const itemUnits = item.units || [];
        const baseUnit = item.base_unit || 'UNIT';
        
        // Show counting form
        const formContainer = document.getElementById('countingFormContainer');
        formContainer.style.display = 'block';
        
        // Build unit options
        const unitOptions = itemUnits.map(unit => 
            `<option value="${escapeHtml(unit.unit_name)}" data-multiplier="${unit.multiplier_to_base || 1}">${escapeHtml(unit.unit_name)}</option>`
        ).join('');
        
        // Add base unit if not in units list
        const hasBaseUnit = itemUnits.some(u => u.unit_name === baseUnit);
        const baseUnitOption = !hasBaseUnit ? `<option value="${escapeHtml(baseUnit)}" data-multiplier="1" selected>${escapeHtml(baseUnit)}</option>` : '';
        
        formContainer.innerHTML = `
            <div class="card">
                <div style="padding: 1rem; border-bottom: 1px solid var(--border-color);">
                    <h4 style="margin: 0;">Count Item: ${escapeHtml(item.name)}</h4>
                </div>
                <div style="padding: 1.5rem;">
                    <!-- System Stock Info -->
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                        <div>
                            <label>Current System Stock</label>
                            <input type="text" class="form-input" value="${currentStockDisplay} ${escapeHtml(baseUnit)}" readonly>
                        </div>
                        <div>
                            <label>Base Unit</label>
                            <input type="text" class="form-input" value="${escapeHtml(baseUnit)}" readonly>
                        </div>
                    </div>
                    
                    <!-- Batch and Expiry (if required) -->
                    ${item.requires_batch_tracking || item.requires_expiry_tracking ? `
                    <div style="display: grid; grid-template-columns: ${item.requires_batch_tracking && item.requires_expiry_tracking ? '1fr 1fr' : '1fr'}; gap: 1rem; margin-bottom: 1rem;">
                        ${item.requires_batch_tracking ? `
                        <div>
                            <label>Batch Number ${item.requires_batch_tracking ? '<span style="color: var(--danger-color);">*</span>' : ''}</label>
                            <input type="text" id="batchNumber" class="form-input" placeholder="Enter batch number" ${item.requires_batch_tracking ? 'required' : ''}>
                        </div>
                        ` : ''}
                        ${item.requires_expiry_tracking ? `
                        <div>
                            <label>Expiry Date ${item.requires_expiry_tracking ? '<span style="color: var(--danger-color);">*</span>' : ''}</label>
                            <input type="date" id="expiryDate" class="form-input" ${item.requires_expiry_tracking ? 'required' : ''}>
                        </div>
                        ` : ''}
                    </div>
                    ` : ''}
                    
                    ${hasTransactions ? 
                        // Item HAS transactions - read only details, but can still select unit
                        `<div class="alert alert-info">
                            <i class="fas fa-info-circle"></i>
                            This item has sales/purchase transactions. Only quantity can be counted (pack size cannot be edited).
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 1rem; margin-top: 1rem;">
                            <div>
                                <label>Count In Unit</label>
                                <select id="countUnit" class="form-input">
                                    ${baseUnitOption}${unitOptions}
                                </select>
                            </div>
                            <div>
                                <label>Counted Quantity</label>
                                <input type="number" id="countedQty" class="form-input" min="0" step="0.01" placeholder="Enter counted quantity">
                            </div>
                        </div>`
                        :
                        // Item NO transactions - editable pack size + unit selection
                        `<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                            <div>
                                <label>Pack Size</label>
                                <input type="text" id="editPackSize" class="form-input" value="${escapeHtml(item.pack_size || '')}" placeholder="e.g., 10 tablets">
                            </div>
                            <div>
                                <label>Breaking Bulk Unit</label>
                                <input type="text" id="editBulkUnit" class="form-input" value="${escapeHtml(item.breaking_bulk_unit || '')}" placeholder="e.g., tablet">
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 1rem; margin-bottom: 1rem;">
                            <div>
                                <label>Count In Unit</label>
                                <select id="countUnit" class="form-input">
                                    ${baseUnitOption}${unitOptions}
                                </select>
                            </div>
                            <div>
                                <label>Counted Quantity</label>
                                <input type="number" id="countedQty" class="form-input" min="0" step="0.01" placeholder="Enter counted quantity">
                            </div>
                        </div>
                        <div class="alert alert-info" style="margin-bottom: 1rem;">
                            <i class="fas fa-info-circle"></i>
                            <strong>Mixed Unit Counting:</strong> You can count in different units. For example, if you have 3 packets and 25 tablets, 
                            enter "3" in packets unit, save, then enter "25" in tablets unit for the same shelf.
                        </div>`
                    }
                    
                    <div style="margin-top: 1rem;">
                        <label>Notes (Optional)</label>
                        <textarea id="countNotes" class="form-input" rows="2" placeholder="Any observations..."></textarea>
                    </div>
                    
                    <div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
                        <button class="btn btn-primary" onclick="saveCount('${itemId}')">
                            <i class="fas fa-plus"></i> Add to Shelf Count
                        </button>
                        <button class="btn btn-secondary" onclick="clearCountingForm()">
                            Cancel
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // Scroll to form
        formContainer.scrollIntoView({ behavior: 'smooth' });
        
    } catch (error) {
        console.error('[STOCK TAKE] Select item error:', error);
        alert('Error: ' + error.message);
    }
}

// Start Shelf Counting
async function startShelfCounting() {
    try {
        const shelfNameInput = document.getElementById('shelfNameInput');
        const shelfName = shelfNameInput?.value.trim();
        
        if (!shelfName) {
            alert('Please enter a shelf name/location.');
            shelfNameInput?.focus();
            return;
        }
        
        // Check if shelf name already exists (unique constraint - no two shelves can have same name)
        try {
            const existingShelves = await API.stockTake.getShelves(CONFIG.BRANCH_ID);
            
            if (existingShelves && existingShelves.some(s => s.name.toLowerCase() === shelfName.toLowerCase())) {
                alert(`Shelf "${shelfName}" already exists. Please use a different name.`);
                shelfNameInput?.focus();
                return;
            }
        } catch (error) {
            console.warn('[STOCK TAKE] Could not check existing shelves:', error);
            // Continue anyway - backend will validate
        }
        
        // Set current shelf
        window.stockTake.currentShelf = shelfName;
        window.stockTake.shelfCounts = [];
        
        // Reload interface to show counting form
        await renderCountingInterface();
        await updateShelfItemCount();
        
        showNotification(`Started counting shelf: ${shelfName}`, 'success');
        
    } catch (error) {
        console.error('[STOCK TAKE] Start shelf counting error:', error);
        alert('Error starting shelf counting: ' + (error.message || 'Please try again.'));
    }
}

// Load shelf name suggestions (optional assisted naming)
async function loadShelfNameSuggestions() {
    try {
        const existingShelves = await API.stockTake.getShelves(CONFIG.BRANCH_ID);
        const suggestionsContainer = document.getElementById('shelfNameSuggestions');
        
        if (!suggestionsContainer) return;
        
        if (existingShelves && existingShelves.length > 0) {
            const uniqueNames = [...new Set(existingShelves.map(s => s.name))].slice(0, 5);
            suggestionsContainer.innerHTML = `
                <small style="color: var(--text-secondary);">
                    <strong>Suggestions:</strong> ${uniqueNames.map(name => 
                        `<a href="#" onclick="document.getElementById('shelfNameInput').value='${escapeHtml(name)}'; return false;" style="margin-right: 0.5rem; color: var(--primary-color);">${escapeHtml(name)}</a>`
                    ).join('')}
                </small>
            `;
        } else {
            suggestionsContainer.innerHTML = '';
        }
    } catch (error) {
        console.warn('[STOCK TAKE] Could not load shelf suggestions:', error);
    }
}

// Cancel Shelf Counting
function cancelShelfCounting() {
    if (confirm('Cancel counting this shelf? All unsaved counts for this shelf will be lost.')) {
        window.stockTake.currentShelf = null;
        window.stockTake.shelfCounts = [];
        renderCountingInterface();
    }
}

// Submit Shelf Count (marks shelf as ready for verification)
async function submitShelfCount() {
    try {
        if (!window.stockTake.currentShelf) {
            alert('No active shelf to submit.');
            return;
        }
        
        // Get counts for this shelf from server
        const userId = await getCurrentUserId();
        const myCounts = await API.stockTake.getMyCounts(CONFIG.BRANCH_ID, userId);
        const shelfCounts = myCounts.filter(c => c.shelf_location === window.stockTake.currentShelf);
        
        if (shelfCounts.length === 0) {
            alert('No items counted for this shelf. Please count at least one item before submitting.');
            return;
        }
        
        if (!confirm(`Submit shelf count for "${window.stockTake.currentShelf}"? This will mark ${shelfCounts.length} item(s) as ready for verification.`)) {
            return;
        }
        
        const submitBtn = document.getElementById('submitShelfBtn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Submitting...';
        }
        
        // All counts are already saved (saved immediately when added)
        // Just mark shelf as submitted/ready for verification
        showNotification(`Shelf "${window.stockTake.currentShelf}" submitted successfully! ${shelfCounts.length} item(s) ready for verification.`, 'success');
        
        // Clear current shelf and reload
        window.stockTake.currentShelf = null;
        window.stockTake.shelfCounts = [];
        await renderCountingInterface();
        await loadMyCounts();
        await updateProgress();
        
    } catch (error) {
        console.error('[STOCK TAKE] Submit shelf count error:', error);
        
        const submitBtn = document.getElementById('submitShelfBtn');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-check-circle"></i> Submit Shelf Count';
        }
        
        alert('Error submitting shelf count: ' + (error.message || 'Please try again.'));
    }
}

// Update shelf item count display
async function updateShelfItemCount() {
    if (!window.stockTake.currentShelf) return;
    
    try {
        const userId = await getCurrentUserId();
        const myCounts = await API.stockTake.getMyCounts(CONFIG.BRANCH_ID, userId);
        const shelfCounts = myCounts.filter(c => c.shelf_location === window.stockTake.currentShelf);
        
        const countElement = document.getElementById('shelfItemCount');
        if (countElement) {
            countElement.textContent = shelfCounts.length;
        }
        
        // Update current shelf items list
        const container = document.getElementById('currentShelfItems');
        if (container && window.stockTake.currentShelf) {
            if (shelfCounts.length === 0) {
                container.innerHTML = '<p style="color: var(--text-secondary); text-align: center;">No items counted yet for this shelf.</p>';
            } else {
                container.innerHTML = `
                    <div class="table-container" style="max-height: 300px; overflow-y: auto;">
                        <table style="width: 100%; font-size: 0.875rem;">
                            <thead>
                                <tr>
                                    <th>Item</th>
                                    <th>Batch</th>
                                    <th>Unit</th>
                                    <th>Quantity</th>
                                    <th>Status</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${shelfCounts.map(count => {
                                    const status = count.verification_status || 'PENDING';
                                    const statusColor = status === 'APPROVED' ? 'var(--success-color)' : status === 'REJECTED' ? 'var(--danger-color)' : 'var(--warning-color)';
                                    return `
                                        <tr>
                                            <td>${escapeHtml(count.item_name || 'Unknown')}</td>
                                            <td><small>${escapeHtml(count.batch_number || '-')}</small></td>
                                            <td><small>${escapeHtml(count.unit_name || '-')}</small></td>
                                            <td><strong>${count.quantity_in_unit || count.counted_quantity || 0}</strong></td>
                                            <td>
                                                <span class="badge" style="background: ${statusColor}; color: white; font-size: 0.75rem;">
                                                    ${status}
                                                </span>
                                            </td>
                                            <td>
                                                ${status === 'PENDING' || status === 'REJECTED' ? `
                                                    <button class="btn btn-sm btn-outline" onclick="editCount('${count.id}')" title="Edit">
                                                        <i class="fas fa-edit"></i>
                                                    </button>
                                                    <button class="btn btn-sm btn-outline-danger" onclick="deleteCount('${count.id}')" title="Delete">
                                                        <i class="fas fa-trash"></i>
                                                    </button>
                                                ` : '<small style="color: var(--text-secondary);">Locked</small>'}
                                            </td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            }
        }
    } catch (error) {
        console.error('[STOCK TAKE] Update shelf item count error:', error);
    }
}

// Save Count (modified for shelf-based workflow)
async function saveCount(itemId) {
    try {
        // Use current shelf instead of input field
        const shelfLocation = window.stockTake.currentShelf;
        if (!shelfLocation) {
            alert('Please start counting a shelf first.');
            return;
        }
        
        const countedQtyInput = document.getElementById('countedQty');
        if (!countedQtyInput) {
            alert('Counting form not found. Please select an item first.');
            return;
        }
        
        const countedQty = parseFloat(countedQtyInput.value);
        if (isNaN(countedQty) || countedQty < 0) {
            alert('Please enter a valid quantity (0 or greater)');
            return;
        }
        
        // Get unit selection
        const unitSelect = document.getElementById('countUnit');
        const selectedUnit = unitSelect ? unitSelect.value : null;
        const unitOption = unitSelect ? unitSelect.options[unitSelect.selectedIndex] : null;
        const unitMultiplier = unitOption ? parseFloat(unitOption.getAttribute('data-multiplier') || '1') : 1;
        
        // Get item to check batch/expiry requirements
        const item = await API.items.get(itemId);
        if (!item) {
            alert('Item not found');
            return;
        }
        
        // Validate batch/expiry if required
        const batchNumber = document.getElementById('batchNumber')?.value.trim() || null;
        const expiryDate = document.getElementById('expiryDate')?.value || null;
        
        if (item.requires_batch_tracking && !batchNumber) {
            alert('Batch number is required for this item. Please enter a batch number.');
            document.getElementById('batchNumber')?.focus();
            return;
        }
        
        if (item.requires_expiry_tracking && !expiryDate) {
            alert('Expiry date is required for this item. Please select an expiry date.');
            document.getElementById('expiryDate')?.focus();
            return;
        }
        
        const notes = document.getElementById('countNotes')?.value.trim() || '';
        
        // Check if item has transactions
        let hasTransactions = false;
        try {
            const transactionCheck = await API.items.hasTransactions(itemId, CONFIG.BRANCH_ID);
            hasTransactions = transactionCheck && transactionCheck.hasTransactions;
        } catch (error) {
            console.warn('[STOCK TAKE] Could not check transactions, assuming item has transactions:', error);
            hasTransactions = true; // Safe default - don't allow edits if check fails
        }
        
        let itemUpdates = null;
        if (!hasTransactions) {
            // Only update if no transactions
            const packSize = document.getElementById('editPackSize')?.value.trim();
            const bulkUnit = document.getElementById('editBulkUnit')?.value.trim();
            
            if (packSize || bulkUnit) {
                itemUpdates = {};
                if (packSize) itemUpdates.pack_size = packSize;
                if (bulkUnit) itemUpdates.breaking_bulk_unit = bulkUnit;
            }
        }
        
        // Get current user ID
        const userId = await getCurrentUserId();
        if (!userId) {
            alert('Unable to identify current user. Please refresh and try again.');
            return;
        }
        
        // Show saving state
        const saveBtn = document.querySelector(`button[onclick="saveCount('${itemId}')"]`);
        const originalBtnText = saveBtn ? saveBtn.innerHTML : '';
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        }
        
        // Save count immediately to server (shelf-based workflow)
        const result = await API.stockTake.saveCount({
            item_id: itemId,
            branch_id: CONFIG.BRANCH_ID,
            shelf_location: shelfLocation,
            batch_number: batchNumber,
            expiry_date: expiryDate,
            unit_name: selectedUnit,
            quantity_in_unit: countedQty,
            counted_quantity: countedQty * unitMultiplier,
            notes: notes || null,
            item_updates: itemUpdates
        }, userId);
        
        if (result && result.success !== false) {
            clearCountingForm();
            await updateShelfItemCount();
            await loadMyCounts();
            await updateProgress();
            
            // Clear search
            const searchInput = document.getElementById('stockTakeSearch');
            const searchResults = document.getElementById('searchResults');
            if (searchInput) searchInput.value = '';
            if (searchResults) searchResults.innerHTML = '';
            
            showNotification('Item added to shelf count! Continue counting or click "Submit Shelf Count" when done.', 'success');
        } else {
            throw new Error(result?.message || result?.detail || 'Failed to save count');
        }
        
    } catch (error) {
        console.error('[STOCK TAKE] Save count error:', error);
        
        // Restore button state
        const saveBtn = document.querySelector(`button[onclick="saveCount('${itemId}')"]`);
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fas fa-save"></i> Save Count';
        }
        
        // Show user-friendly error
        let errorMessage = 'Error saving count. ';
        if (error.message) {
            if (error.message.includes('Failed to fetch') || error.message.includes('Network error')) {
                errorMessage += 'Unable to connect to server. Please check your connection.';
            } else {
                errorMessage += error.message;
            }
        } else {
            errorMessage += 'Please try again.';
        }
        
        alert(errorMessage);
    }
}

// Cancel Stock Take (Admin only)
async function cancelStockTake() {
    if (!confirm('Cancel stock take? This will DISCARD ALL COUNTS and return the branch to normal mode. This action cannot be undone.')) {
        return;
    }
    
    try {
        // Show loading state
        const cancelBtn = document.querySelector('button[onclick="cancelStockTake()"]');
        if (cancelBtn) {
            cancelBtn.disabled = true;
            cancelBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Cancelling...';
        }
        
        const userId = await getCurrentUserId();
        if (!userId) {
            throw new Error('Unable to identify current user. Please refresh and try again.');
        }
        
        const result = await API.stockTake.cancelForBranch(CONFIG.BRANCH_ID, userId);
        
        if (result && result.success !== false) {
            const countsDeleted = result.counts_deleted || 0;
            showNotification(`Stock take cancelled! ${countsDeleted} count(s) discarded.`, 'success');
            
            // Reload page to show normal interface
            setTimeout(() => {
                loadStockTake();
            }, 1500);
        } else {
            throw new Error(result?.message || result?.detail || 'Failed to cancel stock take');
        }
        
    } catch (error) {
        console.error('[STOCK TAKE] Cancel error:', error);
        
        // Restore button state
        const cancelBtn = document.querySelector('button[onclick="cancelStockTake()"]');
        if (cancelBtn) {
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = '<i class="fas fa-times-circle"></i> Cancel Stock Take';
        }
        
        let errorMessage = 'Error cancelling stock take. ';
        if (error.message) {
            if (error.message.includes('Failed to fetch') || error.message.includes('Network error')) {
                errorMessage += 'Unable to connect to server. Please check your connection.';
            } else {
                errorMessage += error.message;
            }
        } else {
            errorMessage += 'Please try again.';
        }
        
        alert(errorMessage);
    }
}

// Complete Stock Take (Admin only)
async function completeStockTake() {
    if (!confirm('Complete stock take? This will update inventory with counted quantities and end the session.')) {
        return;
    }
    
    try {
        // Show loading state
        const completeBtn = document.querySelector('button[onclick="completeStockTake()"]');
        if (completeBtn) {
            completeBtn.disabled = true;
            completeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Completing...';
        }
        
        const userId = await getCurrentUserId();
        if (!userId) {
            throw new Error('Unable to identify current user. Please refresh and try again.');
        }
        
        const result = await API.stockTake.completeForBranch(CONFIG.BRANCH_ID, userId);
        
        if (result && result.success !== false) {
            const itemsUpdated = result.items_updated || 0;
            const totalCounts = result.total_counts || 0;
            showNotification(`Stock take completed! ${itemsUpdated} item(s) updated in inventory.`, 'success');
            
            if (result.warnings && result.warnings.length > 0) {
                console.warn('[STOCK TAKE] Completion warnings:', result.warnings);
            }
            
            // Redirect to inventory after delay
            setTimeout(() => {
                window.location.hash = '#inventory';
            }, 2000);
        } else {
            throw new Error(result?.message || result?.detail || 'Failed to complete stock take');
        }
    } catch (error) {
        console.error('[STOCK TAKE] Complete error:', error);
        
        // Restore button state
        const completeBtn = document.querySelector('button[onclick="completeStockTake()"]');
        if (completeBtn) {
            completeBtn.disabled = false;
            completeBtn.innerHTML = '<i class="fas fa-check-circle"></i> Complete Stock Take';
        }
        
        // Show user-friendly error
        let errorMessage = 'Error completing stock take. ';
        if (error.message) {
            if (error.message.includes('Failed to fetch') || error.message.includes('Network error')) {
                errorMessage += 'Unable to connect to server. Please check your connection.';
            } else {
                errorMessage += error.message;
            }
        } else {
            errorMessage += 'Please try again.';
        }
        
        alert(errorMessage);
    }
}

// Helper Functions
async function getUserRole() {
    try {
        const userId = await getCurrentUserId();
        const usersResponse = await API.users.list();
        const users = usersResponse.users || usersResponse || [];
        const user = users.find(u => u.id === userId);
        
        if (user && user.branch_roles) {
            const branchRole = user.branch_roles.find(br => br.branch_id === CONFIG.BRANCH_ID);
            return branchRole ? branchRole.role_name.toLowerCase() : 'counter';
        }
        return 'counter';
    } catch (error) {
        console.error('[STOCK TAKE] Get role error:', error);
        return 'counter';
    }
}

function isAdminRole(role) {
    return ['admin', 'super admin', 'super_admin', 'auditor'].includes(role?.toLowerCase());
}

async function getCurrentUserId() {
    return window.authState?.user?.id || localStorage.getItem('userId') || CONFIG.USER_ID;
}

// Store current view mode
window.stockTake.countViewMode = window.stockTake.countViewMode || 'list';

// Switch between shelf view and list view
async function switchCountView(mode) {
    window.stockTake.countViewMode = mode;
    
    // Update button states
    const shelfBtn = document.getElementById('viewShelfBtn');
    const listBtn = document.getElementById('viewListBtn');
    if (shelfBtn) shelfBtn.classList.toggle('active', mode === 'shelf');
    if (listBtn) listBtn.classList.toggle('active', mode === 'list');
    
    // Reload counts with new view
    await loadMyCounts();
}

async function loadMyCounts() {
    try {
        const userId = await getCurrentUserId();
        const counts = await API.stockTake.getMyCounts(CONFIG.BRANCH_ID, userId);
        const container = document.getElementById('myCountsList');
        
        if (!container) return;
        
        if (!counts || counts.length === 0) {
            container.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 2rem;">No counts yet. Start counting items!</p>';
            return;
        }
        
        const viewMode = window.stockTake.countViewMode || 'list';
        
        if (viewMode === 'shelf') {
            // Group by shelf
            const byShelf = {};
            counts.forEach(count => {
                const shelf = count.shelf_location || 'UNKNOWN';
                if (!byShelf[shelf]) {
                    byShelf[shelf] = [];
                }
                byShelf[shelf].push(count);
            });
            
            const shelves = Object.keys(byShelf).sort();
            
            container.innerHTML = `
                <div style="display: grid; gap: 1rem;">
                    ${shelves.map(shelf => {
                        const shelfCounts = byShelf[shelf];
                        return `
                            <div class="card" style="border-left: 4px solid var(--primary-color);">
                                <div style="padding: 1rem; border-bottom: 1px solid var(--border-color); background: var(--bg-secondary);">
                                    <h5 style="margin: 0;">
                                        <i class="fas fa-warehouse"></i> ${escapeHtml(shelf)}
                                        <span class="badge" style="margin-left: 0.5rem;">${shelfCounts.length} item(s)</span>
                                    </h5>
                                </div>
                                <div style="padding: 1rem;">
                                    <div class="table-container" style="max-height: 300px; overflow-y: auto;">
                                        <table style="width: 100%; font-size: 0.875rem;">
                                            <thead>
                                                <tr>
                                                    <th>Item</th>
                                                    <th>Batch</th>
                                                    <th>Expiry</th>
                                                    <th>Unit</th>
                                                    <th>Counted</th>
                                                    <th>System</th>
                                                    <th>Diff</th>
                                                    <th>Actions</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                ${shelfCounts.map(count => {
                                                    const difference = (count.counted_quantity || 0) - (count.system_quantity || 0);
                                                    const canEdit = !count.is_completed;
                                                    return `
                                                        <tr>
                                                            <td>${escapeHtml(count.item_name || 'Unknown')}</td>
                                                            <td><small>${escapeHtml(count.batch_number || '-')}</small></td>
                                                            <td><small>${count.expiry_date ? formatDate(count.expiry_date) : '-'}</small></td>
                                                            <td><small>${escapeHtml(count.unit_name || '-')}</small></td>
                                                            <td><strong>${count.counted_quantity || 0}</strong></td>
                                                            <td>${count.system_quantity || 0}</td>
                                                            <td style="color: ${difference === 0 ? 'green' : difference > 0 ? 'blue' : 'red'};">
                                                                ${difference > 0 ? '+' : ''}${difference}
                                                            </td>
                                                            <td>
                                                                ${canEdit ? `
                                                                    <button class="btn btn-sm btn-outline" onclick="editCount('${count.id}')" title="Edit">
                                                                        <i class="fas fa-edit"></i>
                                                                    </button>
                                                                    <button class="btn btn-sm btn-outline-danger" onclick="deleteCount('${count.id}')" title="Delete">
                                                                        <i class="fas fa-trash"></i>
                                                                    </button>
                                                                ` : '<small style="color: var(--text-secondary);">Locked</small>'}
                                                            </td>
                                                        </tr>
                                                    `;
                                                }).join('')}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        } else {
            // List view
            container.innerHTML = `
                <div class="table-container" style="max-height: 400px; overflow-y: auto;">
                    <table style="width: 100%;">
                        <thead>
                            <tr>
                                <th>Shelf</th>
                                <th>Item</th>
                                <th>Batch</th>
                                <th>Unit</th>
                                <th>Counted</th>
                                <th>System</th>
                                <th>Difference</th>
                                <th>Time</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${counts.map(count => {
                                const difference = (count.counted_quantity || 0) - (count.system_quantity || 0);
                                const canEdit = !count.is_completed;
                                return `
                                    <tr>
                                        <td><strong>${escapeHtml(count.shelf_location || 'UNKNOWN')}</strong></td>
                                        <td>${escapeHtml(count.item_name || 'Unknown')}</td>
                                        <td><small>${escapeHtml(count.batch_number || '-')}</small></td>
                                        <td><small>${escapeHtml(count.unit_name || '-')}</small></td>
                                        <td><strong>${count.counted_quantity || 0}</strong></td>
                                        <td>${count.system_quantity || 0}</td>
                                        <td style="color: ${difference === 0 ? 'green' : difference > 0 ? 'blue' : 'red'};">
                                            ${difference > 0 ? '+' : ''}${difference}
                                        </td>
                                        <td><small>${formatDate(count.counted_at)}</small></td>
                                        <td>
                                            ${canEdit ? `
                                                <button class="btn btn-sm btn-outline" onclick="editCount('${count.id}')" title="Edit">
                                                    <i class="fas fa-edit"></i>
                                                </button>
                                                <button class="btn btn-sm btn-outline-danger" onclick="deleteCount('${count.id}')" title="Delete">
                                                    <i class="fas fa-trash"></i>
                                                </button>
                                            ` : '<small style="color: var(--text-secondary);">Locked</small>'}
                                        </td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }
    } catch (error) {
        console.error('[STOCK TAKE] Load counts error:', error);
        const container = document.getElementById('myCountsList');
        if (container) {
            container.innerHTML = '<p style="color: var(--text-secondary);">Error loading counts</p>';
        }
    }
}

async function updateProgress() {
    try {
        const progress = await API.stockTake.getProgress(CONFIG.BRANCH_ID);
        const badge = document.getElementById('progressBadge');
        
        if (badge && progress) {
            const counted = progress.counted_items || progress.total_counted || 0;
            const total = progress.total_items || 0;
            const percentage = total > 0 ? (counted / total) * 100 : 0;
            
            badge.textContent = `${counted} / ${total} items`;
            badge.className = `badge ${percentage >= 80 ? 'badge-success' : percentage >= 50 ? 'badge-warning' : 'badge-info'}`;
            badge.style.fontSize = '1rem';
            badge.style.padding = '0.5rem 1rem';
        }
    } catch (error) {
        console.error('[STOCK TAKE] Progress error:', error);
    }
}

function clearCountingForm() {
    const formContainer = document.getElementById('countingFormContainer');
    if (formContainer) {
        formContainer.style.display = 'none';
        formContainer.innerHTML = '';
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
        year: 'numeric', 
        month: 'short', 
        day: 'numeric', 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

function showNotification(message, type = 'info') {
    if (window.showToast) {
        window.showToast(message, type);
        return;
    }
    if (window.showNotification && window.showNotification !== showNotification) {
        window.showNotification(message, type);
        return;
    }
    // Fallback
    alert(message);
}

// Export to Window
if (typeof window !== 'undefined') {
    window.loadStockTake = loadStockTake;
    window.startBranchStockTake = startBranchStockTake;
    window.searchStockTakeItems = searchStockTakeItems;
    window.selectItemForCounting = selectItemForCounting;
    window.saveCount = saveCount;
    window.completeStockTake = completeStockTake;
    window.cancelStockTake = cancelStockTake;
    window.clearCountingForm = clearCountingForm;
    window.closeDraftModal = closeDraftModal;
    window.refreshDraftCheck = refreshDraftCheck;
    window.editCount = editCount;
    window.saveEditedCount = saveEditedCount;
    window.deleteCount = deleteCount;
    window.switchCountView = switchCountView;
    window.startShelfCounting = startShelfCounting;
    window.cancelShelfCounting = cancelShelfCounting;
    window.submitShelfCount = submitShelfCount;
    window.editShelfItem = editShelfItem;
    window.removeShelfItem = removeShelfItem;
    window.viewShelfForVerification = viewShelfForVerification;
    window.approveShelf = approveShelf;
    window.rejectShelf = rejectShelf;
    window.closeVerificationModal = closeVerificationModal;
    window.loadShelfNameSuggestions = loadShelfNameSuggestions;
}

// Edit shelf item (from current shelf items list) - now uses editCount
// Remove shelf item - now uses deleteCount
// These functions are kept for backward compatibility but redirect to editCount/deleteCount

console.log('[STOCK TAKE] Module loaded and exported');
