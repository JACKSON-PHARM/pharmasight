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
        
        // Get user's company
        let companyId = CONFIG.COMPANY_ID;
        
        if (!companyId) {
            // Try to get from startup status
            try {
                const status = await API.startup.status();
                if (status.initialized && status.company_id) {
                    companyId = status.company_id;
                    CONFIG.COMPANY_ID = companyId;
                    saveConfig();
                }
            } catch (error) {
                console.warn('Could not get company from startup status:', error);
            }
        }
        
        if (!companyId) {
            // Try to list companies (user might belong to one)
            try {
                const companies = await API.company.list();
                if (companies && companies.length > 0) {
                    companyId = companies[0].id;
                    CONFIG.COMPANY_ID = companyId;
                    saveConfig();
                }
            } catch (error) {
                console.error('Error loading companies:', error);
            }
        }
        
        if (!companyId) {
            throw new Error('No company found. Please contact your administrator.');
        }
        
        // Load branches for company
        const branches = await API.branch.list(companyId);
        availableBranches = branches || [];
        
        // Render branch selection UI
        renderBranchSelection();
        
    } catch (error) {
        console.error('Error loading branches:', error);
        page.innerHTML = `
            <div class="login-container">
                <div class="login-card">
                    <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                    <h2>Select Branch</h2>
                    <div class="error-message" style="display: block; margin: 1rem 0;">
                        <i class="fas fa-exclamation-triangle"></i> 
                        ${escapeHtml(error.message || 'Failed to load branches. Please refresh the page.')}
                    </div>
                    <button class="btn btn-primary btn-block" onclick="window.location.reload()">
                        <i class="fas fa-sync-alt"></i> Retry
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
        page.innerHTML = `
            <div class="login-container">
                <div class="login-card">
                    <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                    <h2>Select Branch</h2>
                    <div class="error-message" style="display: block; margin: 1rem 0;">
                        <i class="fas fa-info-circle"></i> 
                        No branches available. Please contact your administrator to create a branch.
                    </div>
                    <button class="btn btn-secondary btn-block" onclick="window.AuthBootstrap.signOut().then(() => window.location.reload())">
                        <i class="fas fa-sign-out-alt"></i> Sign Out
                    </button>
                </div>
            </div>
        `;
        return;
    }
    
    // If only one branch, auto-select it
    // GUARD: do NOT auto-select when user is explicitly on #branch-select route.
    // Branch selection must be user-invoked on this route.
    const currentHash = window.location.hash || '';
    const isOnBranchSelectRoute = currentHash.replace('#', '').split('?')[0] === 'branch-select';
    if (availableBranches.length === 1 && !isOnBranchSelectRoute) {
        selectBranch(availableBranches[0]);
        return;
    }
    
    // Show branch selection list
    const branchList = availableBranches.map(branch => `
        <button class="branch-card" onclick="selectBranchById('${branch.id}')">
            <div class="branch-card-header">
                <i class="fas fa-code-branch"></i>
                <h3>${escapeHtml(branch.name)}</h3>
            </div>
            ${branch.code ? `<div class="branch-card-code">Code: ${escapeHtml(branch.code)}</div>` : ''}
            ${branch.address ? `<div class="branch-card-address">${escapeHtml(branch.address)}</div>` : ''}
        </button>
    `).join('');
    
    console.log('[BRANCH SELECT] Rendering branch list with', availableBranches.length, 'branch(es)');
    const branchSelectionHTML = `
        <div class="login-container">
            <div class="login-card" style="max-width: 600px;">
                <h1><i class="fas fa-pills"></i> PharmaSight</h1>
                <h2>Select Branch</h2>
                <p style="margin-bottom: 1.5rem; color: var(--text-secondary);">
                    Please select a branch to continue.
                </p>
                <div class="branch-list">
                    ${branchList}
                </div>
            </div>
        </div>
        <style>
            .branch-list {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                margin-top: 1.5rem;
            }
            .branch-card {
                background: var(--bg-secondary, #f8f9fa);
                border: 2px solid var(--border-color, #dee2e6);
                border-radius: 0.5rem;
                padding: 1.5rem;
                text-align: left;
                cursor: pointer;
                transition: all 0.2s;
                width: 100%;
            }
            .branch-card:hover {
                border-color: var(--primary-color, #3498db);
                background: var(--bg-hover, #e9ecef);
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            .branch-card-header {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-bottom: 0.5rem;
            }
            .branch-card-header i {
                font-size: 1.5rem;
                color: var(--primary-color, #3498db);
            }
            .branch-card-header h3 {
                margin: 0;
                font-size: 1.25rem;
                color: var(--text-primary, #212529);
            }
            .branch-card-code {
                color: var(--text-secondary, #6c757d);
                font-size: 0.875rem;
                margin-top: 0.5rem;
            }
            .branch-card-address {
                color: var(--text-secondary, #6c757d);
                font-size: 0.875rem;
                margin-top: 0.25rem;
            }
        </style>
    `;
    
    page.innerHTML = branchSelectionHTML;
    console.log('[BRANCH SELECT] Branch selection UI rendered, page.innerHTML length:', page.innerHTML.length);
    console.log('[BRANCH SELECT] Page element display:', window.getComputedStyle(page).display);
    console.log('[BRANCH SELECT] Page element visibility:', window.getComputedStyle(page).visibility);
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
