/**
 * Branch Selection Page
 * 
 * Shows branch selection screen before dashboard loads.
 * User must select a branch to continue.
 */

let availableBranches = [];
let isLoadingBranches = false;

async function loadBranchSelect() {
    console.log('[BRANCH SELECT] loadBranchSelect() called');
    // Branch select is part of app flow but shown before full app shell
    // It should use app layout but without showing sidebar/topbar initially
    // For now, we'll show it in app layout with sidebar hidden
    const authenticated = isAuthenticated();
    if (!authenticated) {
        console.warn('[BRANCH SELECT] User not authenticated, redirecting to login');
        // Not authenticated, redirect to login
        renderAuthLayout();
        loadPage('login');
        return;
    }
    
    console.log('[BRANCH SELECT] User authenticated, rendering app layout');
    // Ensure app layout is rendered (branch selection happens after auth)
    renderAppLayout();
    
    // Hide sidebar and top bar for branch selection (clean UI)
    const sidebar = document.getElementById('sidebar');
    const topBar = document.querySelector('.top-bar');
    if (sidebar) sidebar.style.display = 'none';
    if (topBar) topBar.style.display = 'none';
    
    const page = document.getElementById('branch-select');
    if (!page) {
        console.error('Branch select page not found');
        return;
    }
    
    // Show page
    const appLayout = document.getElementById('appLayout');
    if (appLayout) {
        appLayout.querySelectorAll('.page').forEach(p => {
            if (p.id !== 'branch-select') {
                p.classList.remove('active');
                p.style.display = 'none';
                p.style.visibility = 'hidden';
            }
        });
    }
    
    page.classList.add('active');
    page.style.display = 'block';
    page.style.visibility = 'visible';
    
    console.log('[BRANCH SELECT] Page element found, setting loading state');
    // Show loading state
    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Select Branch</h2>
                <div style="text-align: center; padding: 2rem;">
                    <div class="spinner"></div>
                    <p style="margin-top: 1rem; color: var(--text-secondary);">Loading branches...</p>
                </div>
            </div>
        </div>
        <style>
            .spinner {
                border: 4px solid #f3f3f3;
                border-top: 4px solid var(--primary-color, #3498db);
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1s linear infinite;
                margin: 0 auto;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        </style>
    `;
    
    console.log('[BRANCH SELECT] Loading state set, calling loadBranches()');
    // Load branches
    await loadBranches();
    console.log('[BRANCH SELECT] loadBranches() completed');
}

async function loadBranches() {
    const page = document.getElementById('branch-select');
    if (!page || isLoadingBranches) return;
    
    isLoadingBranches = true;
    
    try {
        const user = AuthBootstrap.getCurrentUser();
        if (!user) {
            throw new Error('User not authenticated');
        }
        
        // Get user's company (must exist in this tenant). Prefer list() so we only use companies that exist.
        let companyId = null;
        try {
            const companies = await API.company.list();
            if (companies && companies.length > 0) {
                companyId = companies[0].id;
                CONFIG.COMPANY_ID = companyId;
                saveConfig();
            }
        } catch (error) {
            console.warn('Could not list companies:', error);
        }
        
        if (!companyId) {
            // Try startup status (may return stale id from another tenant - we'll validate)
            try {
                const status = await API.startup.status();
                if (status.initialized && status.company_id) {
                    try {
                        await API.company.get(status.company_id);
                        companyId = status.company_id;
                        CONFIG.COMPANY_ID = companyId;
                        saveConfig();
                    } catch (e) {
                        if (e.status === 404 || (e.data && e.data.detail === 'Company not found')) {
                            console.log('[BRANCH SELECT] Stale company_id from status, clearing');
                        }
                    }
                }
            } catch (error) {
                console.warn('Could not get company from startup status:', error);
            }
        }
        
        if (!companyId && CONFIG.COMPANY_ID) {
            // Validate persisted CONFIG company (may be from different tenant)
            try {
                await API.company.get(CONFIG.COMPANY_ID);
                companyId = CONFIG.COMPANY_ID;
            } catch (e) {
                if (e.status === 404 || (e.data && e.data.detail === 'Company not found')) {
                    console.log('[BRANCH SELECT] CONFIG company not found in this tenant, clearing');
                    CONFIG.COMPANY_ID = null;
                    saveConfig();
                }
            }
        }
        
        // No company yet: first user must complete company + first branch via setup wizard (company first!)
        if (!companyId) {
            console.log('[BRANCH SELECT] No company found, redirecting to setup wizard (company then branch)');
            window.location.hash = '#setup';
            if (window.loadPage) window.loadPage('setup');
            return;
        }
        
        // Load branches for company
        const branches = await API.branch.list(companyId);
        availableBranches = branches || [];
        
        // Render branch selection UI (or "create first branch" if none)
        renderBranchSelection();
        
    } catch (error) {
        console.error('Error loading branches:', error);
        const isNetwork = /fetch|network|cors|failed/i.test(String(error.message || ''));
        const msg = error.message || 'Failed to load branches.';
        page.innerHTML = `
            <div class="login-container">
                <div class="login-card">
                    <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                    <h2>Select Branch</h2>
                    <div class="error-message" style="display: block; margin: 1rem 0;">
                        <i class="fas fa-exclamation-triangle"></i> 
                        ${escapeHtml(msg)}
                    </div>
                    ${isNetwork ? '<p style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 1rem;">Make sure the backend server is running (e.g. <code>http://localhost:8000</code>). Then retry or go to setup to complete your company profile.</p>' : ''}
                    <button class="btn btn-primary btn-block" onclick="window.location.reload()">
                        <i class="fas fa-sync-alt"></i> Retry
                    </button>
                    <a href="#setup" class="btn btn-secondary btn-block" style="margin-top: 0.5rem; display: inline-block; text-align: center;">
                        <i class="fas fa-cog"></i> Go to setup (company &amp; first branch)
                    </a>
                    <button class="btn btn-secondary btn-block" style="margin-top: 0.5rem;" onclick="window.AuthBootstrap.signOut().then(() => window.location.reload())">
                        <i class="fas fa-sign-out-alt"></i> Sign Out
                    </button>
                </div>
            </div>
        `;
    } finally {
        isLoadingBranches = false;
    }
}

function renderBranchSelection() {
    console.log('[BRANCH SELECT] renderBranchSelection() called, availableBranches:', availableBranches.length);
    const page = document.getElementById('branch-select');
    if (!page) {
        console.error('[BRANCH SELECT] Page element not found in renderBranchSelection');
        return;
    }
    
    if (availableBranches.length === 0) {
        // Company exists but no branches: first user creates first branch here
        renderCreateFirstBranch();
        return;
    }
    
    // If only one branch, auto-select it (unless user is explicitly on branch-select route)
    // GUARD: do NOT auto-select when user is explicitly on #branch-select route.
    // Branch selection must be user-invoked on this route.
    const currentHash = window.location.hash || '';
    const isOnBranchSelectRoute = currentHash.replace('#', '').split('?')[0] === 'branch-select';
    if (availableBranches.length === 1 && !isOnBranchSelectRoute) {
        selectBranch(availableBranches[0]);
        return;
    }
    
    // Build options for select dropdown
    const branchOptions = availableBranches.map(branch => `
        <option value="${branch.id}">
            ${escapeHtml(branch.name)}${branch.code ? ' - ' + escapeHtml(branch.code) : ''}
        </option>
    `).join('');
    
    console.log('[BRANCH SELECT] Rendering branch dropdown with', availableBranches.length, 'branch(es)');
    const branchSelectionHTML = `
        <div class="branch-select-fullscreen">
            <div class="branch-select-card">
                <div class="branch-select-logo">
                    <i class="fas fa-pills"></i>
                </div>
                <h2 class="branch-select-title">Select transacting branch to proceed!</h2>
                
                <div class="branch-select-form-group">
                    <label for="branchSelectDropdown" class="branch-select-label">Assigned Branches</label>
                    <select id="branchSelectDropdown" class="branch-select-dropdown">
                        <option value="">Select Branch</option>
                        ${branchOptions}
                    </select>
                </div>
                
                <div class="branch-select-actions">
                    <button class="btn btn-primary branch-select-proceed" id="branchSelectProceedBtn">
                        Proceed
                    </button>
                    <button class="btn btn-secondary branch-select-logout" id="branchSelectLogoutBtn">
                        Logout
                    </button>
                </div>
            </div>
        </div>
        <style>
            .branch-select-fullscreen {
                width: 100%;
                height: 100vh;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: var(--bg-color);
            }
            .branch-select-card {
                background: var(--card-bg);
                border-radius: 0.75rem;
                padding: 2.5rem 3rem;
                box-shadow: var(--shadow-lg);
                border: 1px solid var(--border-color);
                max-width: 480px;
                width: 100%;
                text-align: center;
            }
            .branch-select-logo {
                width: 56px;
                height: 56px;
                border-radius: 999px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 1rem auto;
                background: rgba(37, 99, 235, 0.1);
                color: var(--primary-color);
                font-size: 1.75rem;
            }
            .branch-select-title {
                font-size: 1.4rem;
                margin-bottom: 1.5rem;
                color: var(--text-primary);
            }
            .branch-select-form-group {
                text-align: left;
                margin-bottom: 2rem;
            }
            .branch-select-label {
                display: block;
                margin-bottom: 0.5rem;
                font-weight: 500;
                color: var(--text-secondary);
            }
            .branch-select-dropdown {
                width: 100%;
                padding: 0.75rem 0.9rem;
                border-radius: 0.5rem;
                border: 1px solid var(--border-color);
                font-size: 1rem;
                outline: none;
            }
            .branch-select-dropdown:focus {
                border-color: var(--primary-color);
                box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.3);
            }
            .branch-select-actions {
                display: flex;
                gap: 1rem;
                justify-content: center;
            }
            .branch-select-proceed {
                min-width: 140px;
            }
            .branch-select-logout {
                min-width: 140px;
            }
        </style>
    `;
    
    page.innerHTML = branchSelectionHTML;
    console.log('[BRANCH SELECT] Branch selection UI rendered, page.innerHTML length:', page.innerHTML.length);
    console.log('[BRANCH SELECT] Page element display:', window.getComputedStyle(page).display);
    console.log('[BRANCH SELECT] Page element visibility:', window.getComputedStyle(page).visibility);
    
    // Wire up Proceed and Logout buttons
    const dropdown = document.getElementById('branchSelectDropdown');
    const proceedBtn = document.getElementById('branchSelectProceedBtn');
    const logoutBtn = document.getElementById('branchSelectLogoutBtn');
    
    if (proceedBtn && dropdown) {
        proceedBtn.onclick = () => {
            const selectedId = dropdown.value;
            if (!selectedId) {
                showToast('Please select a branch to continue', 'warning');
                return;
            }
            selectBranchById(selectedId);
        };
    }
    
    if (logoutBtn) {
        logoutBtn.onclick = async () => {
            try {
                if (window.AuthBootstrap && typeof window.AuthBootstrap.signOut === 'function') {
                    await window.AuthBootstrap.signOut();
                }
            } finally {
                window.location.hash = '#login';
                window.location.reload();
            }
        };
    }
}

function renderCreateFirstBranch() {
    const page = document.getElementById('branch-select');
    if (!page) return;
    const companyId = CONFIG.COMPANY_ID;
    if (!companyId) return;
    page.innerHTML = `
        <div class="login-container">
            <div class="login-card">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Complete your setup</h2>
                <p style="color: var(--text-secondary); margin-bottom: 1rem;">
                    Create your first branch to start using the app. You can add more branches later in Settings.
                </p>
                <form id="createFirstBranchForm">
                    <div class="form-group">
                        <label for="branchName">Branch name *</label>
                        <input type="text" id="branchName" required placeholder="e.g. Main Branch">
                    </div>
                    <div class="form-group">
                        <label for="branchCode">Branch code</label>
                        <input type="text" id="branchCode" placeholder="BR001 (optional, default BR001)">
                    </div>
                    <div class="form-group">
                        <label for="branchAddress">Address</label>
                        <input type="text" id="branchAddress" placeholder="Branch address">
                    </div>
                    <div class="form-group">
                        <label for="branchPhone">Phone</label>
                        <input type="tel" id="branchPhone" placeholder="Branch phone">
                    </div>
                    <div id="createBranchError" class="error-message" style="display: none; margin-bottom: 1rem;"></div>
                    <button type="submit" class="btn btn-primary btn-block" id="createBranchBtn">
                        <i class="fas fa-plus"></i> Create branch & continue
                    </button>
                </form>
                <button class="btn btn-secondary btn-block" style="margin-top: 0.75rem;" onclick="window.AuthBootstrap.signOut().then(() => window.location.reload())">
                    <i class="fas fa-sign-out-alt"></i> Sign Out
                </button>
            </div>
        </div>
    `;
    const form = document.getElementById('createFirstBranchForm');
    const errEl = document.getElementById('createBranchError');
    if (form) {
        form.onsubmit = async function (e) {
            e.preventDefault();
            const name = (document.getElementById('branchName') && document.getElementById('branchName').value || '').trim();
            const codeRaw = (document.getElementById('branchCode') && document.getElementById('branchCode').value || '').trim();
            const code = codeRaw || 'BR001';
            const address = (document.getElementById('branchAddress') && document.getElementById('branchAddress').value || '').trim() || null;
            const phone = (document.getElementById('branchPhone') && document.getElementById('branchPhone').value || '').trim() || null;
            if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
            if (!name) {
                if (errEl) { errEl.textContent = 'Branch name is required'; errEl.style.display = 'block'; }
                return;
            }
            const btn = document.getElementById('createBranchBtn');
            if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...'; }
            try {
                const result = await API.branch.create({
                    company_id: companyId,
                    name: name,
                    code: code.toUpperCase(),
                    address: address,
                    phone: phone,
                    is_active: true
                });
                const user = AuthBootstrap.getCurrentUser();
                if (user && user.id && API.users && typeof API.users.assignRole === 'function') {
                    await API.users.assignRole(user.id, { role_name: 'admin', branch_id: result.id });
                }
                CONFIG.BRANCH_ID = result.id;
                if (typeof saveConfig === 'function') saveConfig();
                showToast('Branch created. Proceeding...', 'success');
                if (window.BranchContext && typeof BranchContext.setBranch === 'function') {
                    BranchContext.setBranch(result);
                }
                if (window.handleBranchSelected) {
                    window.handleBranchSelected();
                } else {
                    loadPage('dashboard');
                }
            } catch (err) {
                const msg = (err && err.message) || (err.data && (err.data.detail || err.data.message)) || 'Failed to create branch';
                if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Create branch & continue'; }
            }
        };
    }
}

async function selectBranch(branch) {
    try {
        // Set branch in context
        BranchContext.setBranch(branch);
        
        showToast(`Selected branch: ${branch.name}`, 'success');
        
        // Wait a moment for state to update
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Trigger app flow to continue
        if (window.handleBranchSelected) {
            window.handleBranchSelected();
        } else {
            // Fallback: navigate to dashboard
            loadPage('dashboard');
        }
    } catch (error) {
        console.error('Error selecting branch:', error);
        showToast('Failed to select branch', 'error');
    }
}

function selectBranchById(branchId) {
    const branch = availableBranches.find(b => b.id === branchId);
    if (branch) {
        selectBranch(branch);
    }
}

// Helper function for escaping HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Export for app.js
window.loadBranchSelect = loadBranchSelect;
window.selectBranchById = selectBranchById;
