// Settings Page - Multi-section Settings Management

console.log('[SETTINGS.JS] Script loading...');

let currentSettingsSubPage = 'general'; // 'general', 'company', 'branches', 'users', 'transaction'

// Initialize settings page
async function loadSettings(subPage = null) {
    console.log('loadSettings() called', subPage ? `with subPage: ${subPage}` : '');
    const page = document.getElementById('settings');
    if (!page) {
        console.error('Settings page element not found!');
        return;
    }
    
    // Show the page
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
    
    // Use provided subPage or current selection
    const targetSubPage = subPage || currentSettingsSubPage;
    console.log('Loading settings sub-page:', targetSubPage);
    // Load sub-page based on current selection or provided parameter
    await loadSettingsSubPage(targetSubPage);
}

// Load specific settings sub-page
async function loadSettingsSubPage(subPage) {
    console.log('[SETTINGS] loadSettingsSubPage() called with:', subPage);
    currentSettingsSubPage = subPage;
    const page = document.getElementById('settings');
    
    if (!page) {
        console.error('[SETTINGS] ERROR: Settings page element not found in loadSettingsSubPage!');
        return;
    }
    
    console.log('[SETTINGS] Page element found, switching...');
    
    // Ensure page is visible
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
    
    console.log('[SETTINGS] Entering switch for subPage:', subPage);
    switch(subPage) {
        case 'general':
            console.log('[SETTINGS] Case: general');
            await renderGeneralSettingsPage();
            break;
        case 'company':
            console.log('[SETTINGS] Case: company');
            await renderCompanyProfilePage();
            break;
        case 'branches':
            console.log('[SETTINGS] Case: branches');
            await renderBranchesPage();
            break;
        case 'users':
            console.log('[SETTINGS] Case: users - calling renderUsersPage()');
            await renderUsersPage();
            console.log('[SETTINGS] renderUsersPage() completed');
            break;
        case 'transaction':
            console.log('[SETTINGS] Case: transaction');
            await renderTransactionSettingsPage();
            break;
        default:
            console.log('[SETTINGS] Case: default (general)');
            await renderGeneralSettingsPage();
    }
    console.log('[SETTINGS] Switch completed for subPage:', subPage);
    
    // Update sub-nav active state
    updateSettingsSubNavActiveState();
}

// Update sub-nav active state
function updateSettingsSubNavActiveState() {
    const subNavItems = document.querySelectorAll('.sub-nav-item');
    subNavItems.forEach(item => {
        if (item.dataset.subPage === currentSettingsSubPage) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

// =====================================================
// GENERAL SETTINGS PAGE
// =====================================================

async function renderGeneralSettingsPage() {
    console.log('renderGeneralSettingsPage() called');
    const page = document.getElementById('settings');
    if (!page) return;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-cog"></i> General Settings</h3>
            </div>
            <div class="card-body">
                <form id="generalSettingsForm" onsubmit="saveGeneralSettings(event)">
                    <div class="form-group">
                        <label class="form-label">API Base URL</label>
                        <input type="text" class="form-input" name="api_base_url" 
                               value="${CONFIG.API_BASE_URL}" required>
                        <small style="color: var(--text-secondary);">
                            Backend API server URL
                        </small>
                    </div>
                    
                    <h4 style="margin-top: 2rem; margin-bottom: 1rem;">Configuration</h4>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Company ID</label>
                            <input type="text" class="form-input" name="company_id" 
                                   value="${CONFIG.COMPANY_ID || ''}" 
                                   placeholder="UUID">
                            <small style="color: var(--text-secondary);">
                                Your company UUID from database
                            </small>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Branch ID</label>
                            <input type="text" class="form-input" name="branch_id" 
                                   value="${CONFIG.BRANCH_ID || ''}" 
                                   placeholder="UUID">
                            <small style="color: var(--text-secondary);">
                                Your branch UUID from database
                            </small>
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">User ID</label>
                            <input type="text" class="form-input" name="user_id" 
                                   value="${CONFIG.USER_ID || ''}" 
                                   placeholder="UUID">
                            <small style="color: var(--text-secondary);">
                                Your user UUID (for audit trail)
                            </small>
                        </div>
                        <div class="form-group">
                            <label class="form-label">VAT Rate (%)</label>
                            <input type="number" class="form-input" name="vat_rate" 
                                   value="${CONFIG.VAT_RATE}" 
                                   step="0.01" min="0" max="100">
                        </div>
                    </div>
                    
                    <div style="margin-top: 2rem;">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Settings
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="resetGeneralSettings()">
                            <i class="fas fa-undo"></i> Reset to Defaults
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function saveGeneralSettings(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    CONFIG.API_BASE_URL = formData.get('api_base_url');
    CONFIG.COMPANY_ID = formData.get('company_id') || null;
    CONFIG.BRANCH_ID = formData.get('branch_id') || null;
    CONFIG.USER_ID = formData.get('user_id') || null;
    CONFIG.VAT_RATE = parseFloat(formData.get('vat_rate') || 16.00);
    
    // Update API client base URL
    api.baseURL = CONFIG.API_BASE_URL;
    
    saveConfig();
    
    // Refresh status bar if company/branch changed
    if (window.updateStatusBar) {
        Auth.getCurrentUser().then(user => {
            if (user) {
                window.updateStatusBar(user);
            }
        }).catch(err => console.warn('Could not refresh status bar:', err));
    }
    
    showToast('Settings saved successfully', 'success');
}

function resetGeneralSettings() {
    CONFIG.API_BASE_URL = 'http://localhost:8000';
    CONFIG.COMPANY_ID = null;
    CONFIG.BRANCH_ID = null;
    CONFIG.USER_ID = null;
    CONFIG.VAT_RATE = 16.00;
    
    saveConfig();
    renderGeneralSettingsPage();
    showToast('Settings reset to defaults', 'info');
}

// =====================================================
// COMPANY PROFILE PAGE
// =====================================================

async function renderCompanyProfilePage() {
    console.log('renderCompanyProfilePage() called');
    const page = document.getElementById('settings');
    if (!page) return;
    
    let companyData = null;
    if (CONFIG.COMPANY_ID) {
        try {
            companyData = await API.company.get(CONFIG.COMPANY_ID);
        } catch (error) {
            console.error('Error loading company:', error);
        }
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-building"></i> Company Profile</h3>
            </div>
            <div class="card-body">
                <form id="companyProfileForm" onsubmit="saveCompanyProfile(event)">
                    <div class="form-group">
                        <label class="form-label">Company Name *</label>
                        <input type="text" class="form-input" name="name" 
                               value="${companyData?.name || ''}" required
                               placeholder="Your Company Name">
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Email</label>
                            <input type="email" class="form-input" name="email" 
                                   value="${companyData?.email || ''}"
                                   placeholder="company@example.com">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Phone</label>
                            <input type="tel" class="form-input" name="phone" 
                                   value="${companyData?.phone || ''}"
                                   placeholder="+254 700 000 000">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-label">Address</label>
                        <textarea class="form-textarea" name="address" rows="3" 
                                  placeholder="Street address, City, Country">${companyData?.address || ''}</textarea>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">City</label>
                            <input type="text" class="form-input" name="city" 
                                   value="${companyData?.city || ''}"
                                   placeholder="City">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Country</label>
                            <input type="text" class="form-input" name="country" 
                                   value="${companyData?.country || 'Kenya'}"
                                   placeholder="Country">
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">PIN / Tax ID</label>
                            <input type="text" class="form-input" name="pin" 
                                   value="${companyData?.pin || ''}"
                                   placeholder="Tax identification number">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Logo URL</label>
                            <input type="url" class="form-input" name="logo_url" 
                                   value="${companyData?.logo_url || ''}"
                                   placeholder="https://example.com/logo.png">
                            <small style="color: var(--text-secondary);">
                                URL to your company logo (will appear on receipts/invoices)
                            </small>
                        </div>
                    </div>
                    
                    <div style="margin-top: 2rem;">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Company Profile
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

async function saveCompanyProfile(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const companyData = {
        name: formData.get('name'),
        email: formData.get('email') || null,
        phone: formData.get('phone') || null,
        address: formData.get('address') || null,
        city: formData.get('city') || null,
        country: formData.get('country') || null,
        pin: formData.get('pin') || null,
        logo_url: formData.get('logo_url') || null
    };
    
    try {
        if (CONFIG.COMPANY_ID) {
            // Update existing company
            await API.company.update(CONFIG.COMPANY_ID, companyData);
            showToast('Company profile updated successfully', 'success');
        } else {
            // Create new company
            const newCompany = await API.company.create(companyData);
            CONFIG.COMPANY_ID = newCompany.id;
            saveConfig();
            showToast('Company created successfully', 'success');
        }
        
        // Refresh status bar
        if (window.updateStatusBar) {
            Auth.getCurrentUser().then(user => {
                if (user) {
                    window.updateStatusBar(user);
                }
            }).catch(err => console.warn('Could not refresh status bar:', err));
        }
    } catch (error) {
        console.error('Error saving company profile:', error);
        showToast(error.message || 'Error saving company profile', 'error');
    }
}

// =====================================================
// BRANCHES PAGE
// =====================================================

async function renderBranchesPage() {
    console.log('renderBranchesPage() called');
    const page = document.getElementById('settings');
    if (!page) return;
    
    let branches = [];
    if (CONFIG.COMPANY_ID) {
        try {
            branches = await API.branch.list(CONFIG.COMPANY_ID);
        } catch (error) {
            console.error('Error loading branches:', error);
        }
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-code-branch"></i> Branches</h3>
                <button class="btn btn-primary" onclick="showCreateBranchModal()">
                    <i class="fas fa-plus"></i> New Branch
                </button>
            </div>
            <div class="card-body">
                ${branches.length === 0 ? `
                    <div style="text-align: center; padding: 3rem;">
                        <i class="fas fa-code-branch" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                        <p style="color: var(--text-secondary);">No branches found</p>
                        <button class="btn btn-primary" onclick="showCreateBranchModal()">
                            <i class="fas fa-plus"></i> Create Your First Branch
                        </button>
                    </div>
                ` : `
                    <div class="table-container">
                        <table style="width: 100%; border-collapse: collapse;">
                            <thead>
                                <tr>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Name</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Address</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Phone</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${branches.map(branch => `
                                    <tr>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <strong>${escapeHtml(branch.name)}</strong>
                                            ${branch.id === CONFIG.BRANCH_ID ? '<span class="badge badge-success" style="margin-left: 0.5rem;">Current</span>' : ''}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(branch.address || '—')}</td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${escapeHtml(branch.phone || '—')}</td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <button class="btn btn-outline" onclick="editBranch('${branch.id}')" title="Edit">
                                                <i class="fas fa-edit"></i>
                                            </button>
                                            ${branch.id !== CONFIG.BRANCH_ID ? `
                                                <button class="btn btn-outline" onclick="setCurrentBranch('${branch.id}')" title="Set as Current">
                                                    <i class="fas fa-check"></i>
                                                </button>
                                            ` : ''}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `}
            </div>
        </div>
    `;
}

function showCreateBranchModal() {
    const content = `
        <form id="createBranchForm" onsubmit="createBranch(event)">
            <div class="form-group">
                <label class="form-label">Branch Name *</label>
                <input type="text" class="form-input" name="name" required placeholder="Branch Name">
            </div>
            <div class="form-group">
                <label class="form-label">Address</label>
                <textarea class="form-textarea" name="address" rows="2" placeholder="Branch address"></textarea>
            </div>
            <div class="form-group">
                <label class="form-label">Phone</label>
                <input type="tel" class="form-input" name="phone" placeholder="Phone number">
            </div>
        </form>
    `;
    
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" type="submit" form="createBranchForm">
            <i class="fas fa-save"></i> Create Branch
        </button>
    `;
    
    showModal('Create New Branch', content, footer);
}

async function createBranch(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    if (!CONFIG.COMPANY_ID) {
        showToast('Please set Company ID in General Settings first', 'error');
        return;
    }
    
    const branchData = {
        company_id: CONFIG.COMPANY_ID,
        name: formData.get('name'),
        address: formData.get('address') || null,
        phone: formData.get('phone') || null
    };
    
    try {
        const branch = await API.branch.create(branchData);
        showToast('Branch created successfully!', 'success');
        closeModal();
        
        // If this is the first branch, set it as current
        if (!CONFIG.BRANCH_ID) {
            CONFIG.BRANCH_ID = branch.id;
            saveConfig();
        }
        
        // Refresh status bar
        if (window.updateStatusBar) {
            Auth.getCurrentUser().then(user => {
                if (user) {
                    window.updateStatusBar(user);
                }
            }).catch(err => console.warn('Could not refresh status bar:', err));
        }
        
        await renderBranchesPage();
    } catch (error) {
        console.error('Error creating branch:', error);
        showToast(error.message || 'Error creating branch', 'error');
    }
}

function editBranch(branchId) {
    showToast('Branch editing coming soon', 'info');
}

async function setCurrentBranch(branchId) {
    CONFIG.BRANCH_ID = branchId;
    saveConfig();
    showToast('Current branch updated', 'success');
    
    // Refresh status bar
    if (window.updateStatusBar) {
        Auth.getCurrentUser().then(user => {
            if (user) {
                window.updateStatusBar(user);
            }
        }).catch(err => console.warn('Could not refresh status bar:', err));
    }
    
    await renderBranchesPage();
}

// =====================================================
// USERS PAGE
// =====================================================

// State for inline forms
let usersPageState = {
    view: 'list', // 'list', 'createUser', 'createRole', 'editUser', 'editRole', 'rolesList'
    editingUserId: null,
    editingRoleId: null,
    showDeleted: false, // Whether to show deleted users
    invitationSent: new Set() // Track which users have had invitations sent
};

// Helper to get current user role (assumes role exists in memory or can be fetched)
async function getCurrentUserRole() {
    try {
        // Try to get from current user object if available
        if (window.currentUser && window.currentUser.role) {
            return window.currentUser.role;
        }
        // Try to get from Auth
        if (typeof Auth !== 'undefined' && Auth.getCurrentUser) {
            const user = await Auth.getCurrentUser();
            if (user && user.role) {
                return user.role;
            }
        }
        // Default: assume admin for now (backend will enforce permissions)
        return 'Admin';
    } catch (error) {
        console.warn('[USERS] Could not determine user role, defaulting to Admin:', error);
        return 'Admin';
    }
}

// Check if user is Super Admin
async function isSuperAdmin() {
    try {
        // Try to get from current user object if available
        if (window.currentUser && window.currentUser.branch_roles) {
            const roles = window.currentUser.branch_roles.map(br => br.role_name);
            return roles.includes('Super Admin');
        }
        // Try to get from API
        if (API && API.users) {
            const usersResponse = await API.users.list();
            const currentUserEmail = window.currentUser?.email || (await Auth.getCurrentUser())?.email;
            const currentUserData = usersResponse.users?.find(u => u.email === currentUserEmail);
            if (currentUserData && currentUserData.branch_roles) {
                return currentUserData.branch_roles.some(br => br.role_name === 'Super Admin');
            }
        }
        // Try legacy method
        const role = await getCurrentUserRole();
        return role === 'Super Admin' || role === 'admin' || role === 'Admin';
    } catch (error) {
        console.warn('[USERS] Could not determine if Super Admin, defaulting to false:', error);
        return false;
    }
}

// Check if user is Primary Admin (Super Admin or Admin)
async function isPrimaryAdmin() {
    const isSuper = await isSuperAdmin();
    if (isSuper) return true;
    const role = await getCurrentUserRole();
    return role === 'Admin' || role === 'Primary Admin' || role === 'admin';
}

// Check if user is Admin or Secondary Admin (includes Super Admin)
async function isAdmin() {
    const isSuper = await isSuperAdmin();
    if (isSuper) return true;
    const role = await getCurrentUserRole();
    return role === 'Admin' || role === 'Primary Admin' || role === 'Secondary Admin' || role === 'admin';
}

// Frontend validation functions
function validateEmail(email) {
    if (!email || email.trim() === '') {
        return { valid: false, message: 'Email is required' };
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        return { valid: false, message: 'Please enter a valid email address (e.g., name@domain.com)' };
    }
    return { valid: true, message: '' };
}

function validatePhone(phone) {
    if (!phone || phone.trim() === '') {
        return { valid: false, message: 'Phone number is required' };
    }
    // Allow leading +, then numeric only, minimum 10 digits
    const phoneRegex = /^\+?[0-9]{10,}$/;
    const digitsOnly = phone.replace(/[^0-9]/g, '');
    if (digitsOnly.length < 10) {
        return { valid: false, message: 'Phone number must be at least 10 digits' };
    }
    if (!phoneRegex.test(phone)) {
        return { valid: false, message: 'Phone number must be numeric (leading + allowed)' };
    }
    return { valid: true, message: '' };
}

// Update validation state and UI
function updateFormValidation(formId) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    const emailInput = form.querySelector('input[name="email"]');
    const phoneInput = form.querySelector('input[name="phone"]');
    const saveButton = form.querySelector('button[type="submit"]');
    
    if (!emailInput || !phoneInput || !saveButton) return;
    
    const emailValidation = validateEmail(emailInput.value);
    const phoneValidation = validatePhone(phoneInput.value);
    
    // Update email validation message
    let emailError = form.querySelector('.email-error');
    if (!emailError) {
        emailError = document.createElement('div');
        emailError.className = 'email-error';
        emailError.style.color = 'var(--danger-color)';
        emailError.style.fontSize = '0.875rem';
        emailError.style.marginTop = '0.25rem';
        emailInput.parentNode.appendChild(emailError);
    }
    emailError.textContent = emailValidation.message;
    emailInput.style.borderColor = emailValidation.valid ? '' : 'var(--danger-color)';
    
    // Update phone validation message
    let phoneError = form.querySelector('.phone-error');
    if (!phoneError) {
        phoneError = document.createElement('div');
        phoneError.className = 'phone-error';
        phoneError.style.color = 'var(--danger-color)';
        phoneError.style.fontSize = '0.875rem';
        phoneError.style.marginTop = '0.25rem';
        phoneInput.parentNode.appendChild(phoneError);
    }
    phoneError.textContent = phoneValidation.message;
    phoneInput.style.borderColor = phoneValidation.valid ? '' : 'var(--danger-color)';
    
    // Enable/disable save button
    const isValid = emailValidation.valid && phoneValidation.valid;
    saveButton.disabled = !isValid;
    saveButton.style.opacity = isValid ? '1' : '0.5';
    saveButton.style.cursor = isValid ? 'pointer' : 'not-allowed';
}

async function renderUsersPage() {
    console.log('[USERS] renderUsersPage() called - START');
    const page = document.getElementById('settings');
    if (!page) {
        console.error('[USERS] ERROR: Settings page element not found!');
        const fallbackPage = document.querySelector('.page.active') || document.body;
        fallbackPage.innerHTML = '<div class="card"><div class="card-body"><p style="color: red;">Error: Settings page element not found</p></div></div>';
        return;
    }
    
    // ALWAYS render something - show loading state first
    try {
        page.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="fas fa-users"></i> Users & Roles</h3>
                </div>
                <div class="card-body">
                    <div style="text-align: center; padding: 2rem;">
                        <p>Loading users...</p>
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('[USERS] Error setting loading state:', error);
    }
    
    // Load users, roles, branches, and current user role
    let users = [];
    let roles = [];
    let branches = [];
    let errorMessage = null;
    let userRole = 'Admin';
    let canCreateRole = false;
    
    // Check if we should show deleted users (stored in state)
    const showDeleted = usersPageState.showDeleted || false;
    
    try {
        userRole = await getCurrentUserRole();
        canCreateRole = await isPrimaryAdmin();
        
        if (API && API.users) {
            // Always fetch with include_deleted=true, we'll filter in the UI
            const usersResponse = await API.users.list(true);
            users = usersResponse.users || [];
            
            roles = await API.users.listRoles();
            
            if (CONFIG.COMPANY_ID) {
                branches = await API.branch.list(CONFIG.COMPANY_ID);
            }
        } else {
            errorMessage = 'API not initialized. Please check your configuration.';
            console.error('API.users is not defined');
        }
    } catch (error) {
        console.error('Error loading users:', error);
        errorMessage = error.message || 'Error loading users. Please check the console for details.';
        showToast('Error loading users. Please try again.', 'error');
    }
    
    // Determine what to show based on state
    const view = usersPageState.view;
    const isAdminUser = await isAdmin();
    const isPrimaryAdminUser = await isPrimaryAdmin();
    
    // Render the page content - NEVER render blank
    try {
        if (view === 'createUser') {
            await renderCreateUserForm(page, roles, branches, isAdminUser);
        } else if (view === 'createRole' && canCreateRole) {
            await renderCreateRoleForm(page, roles);
        } else if (view === 'editUser' && usersPageState.editingUserId) {
            await renderEditUserForm(page, usersPageState.editingUserId, roles, branches, isAdminUser);
        } else if (view === 'editRole' && usersPageState.editingRoleId && canCreateRole) {
            await renderEditRoleForm(page, usersPageState.editingRoleId, roles);
        } else if (view === 'rolesList') {
            renderRolesList(page, roles, canCreateRole);
        } else {
            // Default: show users list
            renderUsersList(page, users, roles, branches, errorMessage, isAdminUser, canCreateRole, isPrimaryAdminUser);
        }
        console.log('[USERS] Page rendered successfully!');
    } catch (error) {
        console.error('Error rendering users page:', error);
        page.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i class="fas fa-users"></i> Users & Roles</h3>
                </div>
                <div class="card-body">
                    <div style="text-align: center; padding: 3rem; color: var(--danger-color);">
                        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; margin-bottom: 1rem;"></i>
                        <p><strong>Error rendering page</strong></p>
                        <p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">${escapeHtml(error.message || 'Unknown error')}</p>
                        <button class="btn btn-primary" onclick="window.renderUsersPage()" style="margin-top: 1rem;">
                            <i class="fas fa-refresh"></i> Retry
                        </button>
                    </div>
                </div>
            </div>
        `;
    }
}

function renderUsersList(page, users, roles, branches, errorMessage, isAdminUser, canCreateRole, isPrimaryAdminUser) {
    // Separate active and deleted users
    const activeUsers = users.filter(u => !u.deleted_at);
    const deletedUsers = users.filter(u => u.deleted_at);
    const showDeleted = usersPageState.showDeleted || false;
    const usersToDisplay = showDeleted ? users : activeUsers;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-users"></i> Users & Roles</h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-primary" onclick="showCreateUserForm()" title="Create a new user">
                        <i class="fas fa-plus"></i> Create User
                    </button>
                    <button class="btn btn-secondary" onclick="showCreateRoleForm()" title="Create a new role">
                        <i class="fas fa-user-tag"></i> Create Role
                    </button>
                    <button class="btn btn-outline" onclick="showRolesList()" title="View all roles">
                        <i class="fas fa-list"></i> Manage Roles
                    </button>
                </div>
            </div>
            <div class="card-body">
                <!-- Inline Action Bar -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 2px solid var(--border-color);">
                    <div style="display: flex; gap: 1rem; align-items: center;">
                        <div style="color: var(--text-secondary); font-size: 0.875rem;">
                            ${activeUsers.length} active user${activeUsers.length !== 1 ? 's' : ''}${deletedUsers.length > 0 ? ` • ${deletedUsers.length} deleted` : ''} • ${roles.length} role${roles.length !== 1 ? 's' : ''}
                        </div>
                        ${deletedUsers.length > 0 ? `
                            <label style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer; font-size: 0.875rem;">
                                <input type="checkbox" ${showDeleted ? 'checked' : ''} onchange="toggleShowDeleted()" style="cursor: pointer;">
                                Show deleted users
                            </label>
                        ` : ''}
                    </div>
                </div>
                ${errorMessage ? `
                    <div style="text-align: center; padding: 3rem; color: var(--danger-color);">
                        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; margin-bottom: 1rem;"></i>
                        <p><strong>Error loading users</strong></p>
                        <p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">${escapeHtml(errorMessage)}</p>
                        <button class="btn btn-primary" onclick="window.renderUsersPage()" style="margin-top: 1rem;">
                            <i class="fas fa-refresh"></i> Retry
                        </button>
                    </div>
                ` : usersToDisplay.length === 0 ? `
                    <div style="text-align: center; padding: 3rem;">
                        <i class="fas fa-users" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                        <p style="color: var(--text-secondary); margin-bottom: 1rem;">${showDeleted ? 'No users found' : 'No active users found'}</p>
                        <button class="btn btn-primary" onclick="showCreateUserForm()">
                            <i class="fas fa-plus"></i> Create Your First User
                        </button>
                    </div>
                ` : `
                    <div class="table-container" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <thead>
                                <tr>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Email</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Name</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Phone</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Role(s)</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Status</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${usersToDisplay.map(user => {
                                    const isDeleted = user.deleted_at !== null && user.deleted_at !== undefined;
                                    return `
                                    <tr ${isDeleted ? 'style="opacity: 0.6; background-color: var(--bg-secondary);"' : ''}>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${escapeHtml(user.email)}
                                            ${user.is_pending ? '<span class="badge badge-warning" style="margin-left: 0.5rem;">Pending</span>' : ''}
                                            ${isDeleted ? '<span class="badge badge-danger" style="margin-left: 0.5rem;">Deleted</span>' : ''}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${escapeHtml(user.full_name || '—')}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${escapeHtml(user.phone || '—')}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${user.branch_roles && user.branch_roles.length > 0 
                                                ? user.branch_roles.map(ubr => 
                                                    `<span class="badge" style="margin-right: 0.25rem;">${escapeHtml(ubr.role_name || 'N/A')}</span>`
                                                ).join('')
                                                : '<span class="badge badge-secondary">No role</span>'
                                            }
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${user.is_active 
                                                ? '<span class="badge badge-success">Active</span>' 
                                                : '<span class="badge badge-danger">Inactive</span>'
                                            }
                                            ${user.is_pending 
                                                ? (usersPageState.invitationSent.has(user.id) 
                                                    ? '<span class="badge badge-info" style="margin-left: 0.25rem;">Invitation Sent</span>'
                                                    : '<span class="badge badge-warning" style="margin-left: 0.25rem;">Pending</span>')
                                                : ''
                                            }
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                                ${isDeleted ? `
                                                    <button class="btn btn-success btn-sm" onclick="restoreUser('${user.id}', '${escapeHtml(user.email)}')" title="Restore User">
                                                        <i class="fas fa-undo"></i> Restore
                                                    </button>
                                                ` : `
                                                    ${user.is_pending && !isDeleted && isPrimaryAdminUser
                                                        ? `<button class="btn btn-primary btn-sm" onclick="sendInvitationEmail('${user.id}', '${escapeHtml(user.email)}')" id="send-invite-btn-${user.id}" title="Send Invitation Email">
                                                            <i class="fas fa-paper-plane"></i> Send Invitation
                                                        </button>`
                                                        : ''
                                                    }
                                                    ${user.is_pending && user.invitation_code 
                                                        ? `<button class="btn btn-outline btn-sm" onclick="copyInvitationCode('${escapeHtml(user.invitation_code)}', '${escapeHtml(user.email)}')" title="Copy Invitation Code">
                                                            <i class="fas fa-copy"></i>
                                                        </button>`
                                                        : ''
                                                    }
                                                    <button class="btn btn-outline btn-sm" onclick="showEditUserForm('${user.id}')" title="Edit User">
                                                        <i class="fas fa-edit"></i> Edit
                                                    </button>
                                                    ${user.is_active 
                                                        ? `<button class="btn btn-outline btn-sm" onclick="toggleUserActive('${user.id}', false)" title="Deactivate User">
                                                            <i class="fas fa-ban"></i> Deactivate
                                                        </button>`
                                                        : `<button class="btn btn-outline btn-sm" onclick="toggleUserActive('${user.id}', true)" title="Activate User">
                                                            <i class="fas fa-check"></i> Activate
                                                        </button>`
                                                    }
                                                    <button class="btn btn-outline btn-sm btn-danger" onclick="deleteUser('${user.id}', '${escapeHtml(user.email)}')" title="Delete User">
                                                        <i class="fas fa-trash"></i> Delete
                                                    </button>
                                                `}
                                            </div>
                                        </td>
                                    </tr>
                                `;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>
                `}
            </div>
        </div>
    `;
}

async function renderCreateUserForm(page, roles, branches, isAdminUser) {
    if (!isAdminUser) {
        usersPageState.view = 'list';
        await renderUsersPage();
        showToast('You do not have permission to create users', 'error');
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-user-plus"></i> Create New User</h3>
                <button class="btn btn-secondary" onclick="cancelCreateUser()">
                    <i class="fas fa-times"></i> Cancel
                </button>
            </div>
            <div class="card-body">
                <form id="createUserForm" onsubmit="handleCreateUser(event)">
                    <div class="form-group">
                        <label class="form-label">Full Name *</label>
                        <input type="text" class="form-input" name="full_name" required 
                               placeholder="John Doe">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Email *</label>
                        <input type="email" class="form-input" name="email" required 
                               placeholder="user@example.com" oninput="updateFormValidation('createUserForm')">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Phone Number *</label>
                        <input type="tel" class="form-input" name="phone" required 
                               placeholder="+254700000000" oninput="updateFormValidation('createUserForm')">
                        <small style="color: var(--text-secondary); display: block; margin-top: 0.25rem;">
                            Used for password reset flows. Must be at least 10 digits.
                        </small>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Role *</label>
                        <select class="form-input" name="role_name" required>
                            <option value="">Select a role</option>
                            ${roles.map(role => 
                                `<option value="${escapeHtml(role.role_name)}">${escapeHtml(role.role_name)}${role.description ? ' - ' + escapeHtml(role.description) : ''}</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Branch (Optional)</label>
                        <select class="form-input" name="branch_id">
                            <option value="">None (assign later)</option>
                            ${branches.map(branch => 
                                `<option value="${branch.id}">${escapeHtml(branch.name)}</option>`
                            ).join('')}
                        </select>
                        <small style="color: var(--text-secondary); display: block; margin-top: 0.25rem;">
                            Assign user to a specific branch, or leave empty to assign later
                        </small>
                    </div>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="is_active" checked>
                            <span>Active (user can login immediately after password setup)</span>
                        </label>
                    </div>
                    <div style="margin-top: 2rem; display: flex; gap: 1rem;">
                        <button type="submit" class="btn btn-primary" disabled>
                            <i class="fas fa-save"></i> Create User
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="cancelCreateUser()">
                            <i class="fas fa-times"></i> Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize validation
    setTimeout(() => updateFormValidation('createUserForm'), 100);
}

async function renderCreateRoleForm(page, roles) {
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-user-tag"></i> Create New Role</h3>
                <button class="btn btn-secondary" onclick="cancelCreateRole()">
                    <i class="fas fa-times"></i> Cancel
                </button>
            </div>
            <div class="card-body">
                <form id="createRoleForm" onsubmit="handleCreateRole(event)">
                    <div class="form-group">
                        <label class="form-label">Role Name *</label>
                        <input type="text" class="form-input" name="role_name" required 
                               placeholder="e.g., Pharmacist, Cashier">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Description</label>
                        <textarea class="form-textarea" name="description" rows="3" 
                                  placeholder="Describe the role's responsibilities"></textarea>
                    </div>
                    <h4 style="margin-top: 1.5rem; margin-bottom: 1rem;">Permissions</h4>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="permission_read">
                            <span>Read</span>
                        </label>
                    </div>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="permission_write">
                            <span>Write</span>
                        </label>
                    </div>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="permission_admin">
                            <span>Admin</span>
                        </label>
                    </div>
                    <div style="margin-top: 2rem; display: flex; gap: 1rem;">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Create Role
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="cancelCreateRole()">
                            <i class="fas fa-times"></i> Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function renderRolesList(page, roles, canCreateRole) {
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-user-tag"></i> Roles</h3>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-primary" onclick="showCreateRoleForm()" title="Create a new role">
                        <i class="fas fa-plus"></i> Create Role
                    </button>
                    <button class="btn btn-secondary" onclick="cancelRolesList()">
                        <i class="fas fa-arrow-left"></i> Back to Users
                    </button>
                </div>
            </div>
            <div class="card-body">
                <!-- Inline Action Bar -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 2px solid var(--border-color);">
                    <div style="color: var(--text-secondary); font-size: 0.875rem;">
                        ${roles.length} role${roles.length !== 1 ? 's' : ''}
                    </div>
                </div>
                ${roles.length === 0 ? `
                    <div style="text-align: center; padding: 3rem;">
                        <i class="fas fa-user-tag" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                        <p style="color: var(--text-secondary); margin-bottom: 1rem;">No roles found</p>
                        <button class="btn btn-primary" onclick="showCreateRoleForm()">
                            <i class="fas fa-plus"></i> Create Your First Role
                        </button>
                    </div>
                ` : `
                    <div class="table-container" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <thead>
                                <tr>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Role Name</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Description</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Permissions</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${roles.map(role => `
                                    <tr>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <strong>${escapeHtml(role.role_name)}</strong>
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${escapeHtml(role.description || '—')}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                                ${role.permissions ? `
                                                    ${role.permissions.read ? '<span class="badge badge-info">Read</span>' : ''}
                                                    ${role.permissions.write ? '<span class="badge badge-info">Write</span>' : ''}
                                                    ${role.permissions.admin ? '<span class="badge badge-warning">Admin</span>' : ''}
                                                ` : '<span class="badge badge-secondary">No permissions set</span>'}
                                            </div>
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <button class="btn btn-outline btn-sm" onclick="showEditRoleForm('${role.id}')" title="Edit Role">
                                                <i class="fas fa-edit"></i> Edit
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `}
            </div>
        </div>
    `;
}

async function renderEditRoleForm(page, roleId, roles) {
    let role = null;
    try {
        // Try to find role in the list, or fetch from API if needed
        role = roles.find(r => r.id === roleId);
        if (!role && API && API.users && API.users.getRole) {
            role = await API.users.getRole(roleId);
        } else if (!role) {
            // Fallback: create a basic role object
            role = { id: roleId, role_name: 'Unknown', description: '', permissions: {} };
        }
    } catch (error) {
        console.error('Error loading role:', error);
        showToast('Error loading role details', 'error');
        usersPageState.view = 'list';
        usersPageState.editingRoleId = null;
        await renderUsersPage();
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-user-tag"></i> Edit Role: ${escapeHtml(role.role_name)}</h3>
                <button class="btn btn-secondary" onclick="cancelEditRole()">
                    <i class="fas fa-times"></i> Cancel
                </button>
            </div>
            <div class="card-body">
                <form id="editRoleForm" onsubmit="handleEditRole(event, '${role.id}')">
                    <div class="form-group">
                        <label class="form-label">Role Name *</label>
                        <input type="text" class="form-input" name="role_name" required 
                               value="${escapeHtml(role.role_name)}" placeholder="e.g., Pharmacist, Cashier">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Description</label>
                        <textarea class="form-textarea" name="description" rows="3" 
                                  placeholder="Describe the role's responsibilities">${escapeHtml(role.description || '')}</textarea>
                    </div>
                    <h4 style="margin-top: 1.5rem; margin-bottom: 1rem;">Permissions</h4>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="permission_read" ${role.permissions && role.permissions.read ? 'checked' : ''}>
                            <span>Read</span>
                        </label>
                    </div>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="permission_write" ${role.permissions && role.permissions.write ? 'checked' : ''}>
                            <span>Write</span>
                        </label>
                    </div>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="permission_admin" ${role.permissions && role.permissions.admin ? 'checked' : ''}>
                            <span>Admin</span>
                        </label>
                    </div>
                    <div style="margin-top: 2rem; display: flex; gap: 1rem;">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Update Role
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="cancelEditRole()">
                            <i class="fas fa-times"></i> Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function cancelRolesList() {
    usersPageState.view = 'list';
    renderUsersPage();
}

async function renderEditUserForm(page, userId, roles, branches, isAdminUser) {
    if (!isAdminUser) {
        usersPageState.view = 'list';
        usersPageState.editingUserId = null;
        await renderUsersPage();
        showToast('You do not have permission to edit users', 'error');
        return;
    }
    
    let user = null;
    try {
        user = await API.users.get(userId);
    } catch (error) {
        console.error('Error loading user:', error);
        showToast('Error loading user details', 'error');
        usersPageState.view = 'list';
        usersPageState.editingUserId = null;
        await renderUsersPage();
        return;
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-user-edit"></i> Edit User: ${escapeHtml(user.email)}</h3>
                <button class="btn btn-secondary" onclick="cancelEditUser()">
                    <i class="fas fa-times"></i> Cancel
                </button>
            </div>
            <div class="card-body">
                <form id="editUserForm" onsubmit="handleEditUser(event, '${user.id}')">
                    <div class="form-group">
                        <label class="form-label">Full Name *</label>
                        <input type="text" class="form-input" name="full_name" required 
                               value="${escapeHtml(user.full_name || '')}" placeholder="John Doe">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Email *</label>
                        <input type="email" class="form-input" name="email" required 
                               value="${escapeHtml(user.email)}" placeholder="user@example.com" oninput="updateFormValidation('editUserForm')">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Phone Number *</label>
                        <input type="tel" class="form-input" name="phone" required 
                               value="${escapeHtml(user.phone || '')}" placeholder="+254700000000" oninput="updateFormValidation('editUserForm')">
                        <small style="color: var(--text-secondary); display: block; margin-top: 0.25rem;">
                            Used for password reset flows. Must be at least 10 digits.
                        </small>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Role *</label>
                        <select class="form-input" name="role_name" required>
                            <option value="">Select a role</option>
                            ${roles.map(role => {
                                const isSelected = user.branch_roles && user.branch_roles.some(ubr => ubr.role_name === role.role_name);
                                return `<option value="${escapeHtml(role.role_name)}" ${isSelected ? 'selected' : ''}>${escapeHtml(role.role_name)}${role.description ? ' - ' + escapeHtml(role.description) : ''}</option>`;
                            }).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Branch (Optional)</label>
                        <select class="form-input" name="branch_id">
                            <option value="">None (assign later)</option>
                            ${branches.map(branch => {
                                const isSelected = user.branch_roles && user.branch_roles.some(ubr => ubr.branch_id === branch.id);
                                return `<option value="${branch.id}" ${isSelected ? 'selected' : ''}>${escapeHtml(branch.name)}</option>`;
                            }).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="is_active" ${user.is_active ? 'checked' : ''}>
                            <span>Active</span>
                        </label>
                    </div>
                    <div style="margin-top: 2rem; display: flex; gap: 1rem;">
                        <button type="submit" class="btn btn-primary" disabled>
                            <i class="fas fa-save"></i> Update User
                        </button>
                        <button type="button" class="btn btn-secondary" onclick="cancelEditUser()">
                            <i class="fas fa-times"></i> Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    // Initialize validation
    setTimeout(() => updateFormValidation('editUserForm'), 100);
}

// Inline form handlers
function showCreateUserForm() {
    usersPageState.view = 'createUser';
    renderUsersPage();
}

function cancelCreateUser() {
    usersPageState.view = 'list';
    renderUsersPage();
}

function showCreateRoleForm() {
    usersPageState.view = 'createRole';
    renderUsersPage();
}

function cancelCreateRole() {
    usersPageState.view = 'list';
    renderUsersPage();
}

function showEditUserForm(userId) {
    usersPageState.view = 'editUser';
    usersPageState.editingUserId = userId;
    renderUsersPage();
}

function cancelEditUser() {
    usersPageState.view = 'list';
    usersPageState.editingUserId = null;
    renderUsersPage();
}

function showRolesList() {
    usersPageState.view = 'rolesList';
    renderUsersPage();
}

function showEditRoleForm(roleId) {
    usersPageState.view = 'editRole';
    usersPageState.editingRoleId = roleId;
    renderUsersPage();
}

function cancelEditRole() {
    usersPageState.view = 'list';
    usersPageState.editingRoleId = null;
    renderUsersPage();
}

async function handleCreateUser(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    // Frontend validation
    const emailValidation = validateEmail(formData.get('email'));
    const phoneValidation = validatePhone(formData.get('phone'));
    
    if (!emailValidation.valid || !phoneValidation.valid) {
        showToast('Please fix validation errors before submitting', 'error');
        return;
    }
    
    const userData = {
        email: formData.get('email'),
        full_name: formData.get('full_name') || null,
        phone: formData.get('phone'),
        role_name: formData.get('role_name'),
        branch_id: formData.get('branch_id') || null,
        is_active: formData.get('is_active') === 'on'
    };
    
    try {
        const result = await API.users.create(userData);
        showToast(result.message || 'User created successfully!', 'success');
        
        // Show invitation code inline
        if (result.invitation_code) {
            const inviteDiv = document.createElement('div');
            inviteDiv.style.cssText = 'margin-top: 1rem; padding: 1rem; background: var(--bg-secondary); border-radius: 0.5rem;';
            inviteDiv.innerHTML = `
                <p style="margin-bottom: 0.5rem;"><strong>Invitation Code:</strong></p>
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <code style="flex: 1; padding: 0.5rem; background: white; border: 1px solid var(--border-color); border-radius: 0.25rem; font-size: 1.25rem; font-weight: bold;">${escapeHtml(result.invitation_code)}</code>
                    <button class="btn btn-outline" onclick="copyInvitationCode('${escapeHtml(result.invitation_code)}', '${escapeHtml(userData.email)}')">
                        <i class="fas fa-copy"></i> Copy
                    </button>
                </div>
                <p style="margin-top: 0.5rem; font-size: 0.875rem; color: var(--text-secondary);">
                    Share this code with the user for first-time login.
                </p>
            `;
            form.parentNode.insertBefore(inviteDiv, form);
        }
        
        // Reset form and return to list after 2 seconds
        setTimeout(async () => {
            usersPageState.view = 'list';
            await renderUsersPage();
        }, 2000);
    } catch (error) {
        console.error('Error creating user:', error);
        showToast(error.message || 'Error creating user', 'error');
    }
}

async function handleCreateRole(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const roleData = {
        role_name: formData.get('role_name'),
        description: formData.get('description') || null,
        permissions: {
            read: formData.get('permission_read') === 'on',
            write: formData.get('permission_write') === 'on',
            admin: formData.get('permission_admin') === 'on'
        }
    };
    
    try {
        // Note: This endpoint may need to be created in the backend
        if (API && API.users && API.users.createRole) {
            await API.users.createRole(roleData);
            showToast('Role created successfully!', 'success');
            usersPageState.view = 'list';
            await renderUsersPage();
        } else {
            showToast('Role creation feature coming soon. Backend endpoint needed.', 'info');
        }
    } catch (error) {
        console.error('Error creating role:', error);
        showToast(error.message || 'Error creating role', 'error');
    }
}

async function handleEditRole(event, roleId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const roleData = {
        role_name: formData.get('role_name'),
        description: formData.get('description') || null,
        permissions: {
            read: formData.get('permission_read') === 'on',
            write: formData.get('permission_write') === 'on',
            admin: formData.get('permission_admin') === 'on'
        }
    };
    
    try {
        if (API && API.users && API.users.updateRole) {
            await API.users.updateRole(roleId, roleData);
            showToast('Role updated successfully!', 'success');
            usersPageState.view = 'list';
            usersPageState.editingRoleId = null;
            await renderUsersPage();
        } else {
            showToast('Role editing feature coming soon. Backend endpoint needed.', 'info');
        }
    } catch (error) {
        console.error('Error updating role:', error);
        showToast(error.message || 'Error updating role', 'error');
    }
}

async function handleEditUser(event, userId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    // Frontend validation
    const emailValidation = validateEmail(formData.get('email'));
    const phoneValidation = validatePhone(formData.get('phone'));
    
    if (!emailValidation.valid || !phoneValidation.valid) {
        showToast('Please fix validation errors before submitting', 'error');
        return;
    }
    
    const userData = {
        email: formData.get('email'),
        full_name: formData.get('full_name') || null,
        phone: formData.get('phone'),
        role_name: formData.get('role_name'),
        branch_id: formData.get('branch_id') || null,
        is_active: formData.get('is_active') === 'on'
    };
    
    try {
        await API.users.update(userId, userData);
        showToast('User updated successfully!', 'success');
        usersPageState.view = 'list';
        usersPageState.editingUserId = null;
        await renderUsersPage();
    } catch (error) {
        console.error('Error updating user:', error);
        showToast(error.message || 'Error updating user', 'error');
    }
}

function copyInvitationCode(code, email) {
    navigator.clipboard.writeText(code).then(() => {
        showToast(`Invitation code for ${email} copied to clipboard: ${code}`, 'success');
    }).catch(() => {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = code;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showToast(`Invitation code: ${code}`, 'info');
    });
}

async function toggleUserActive(userId, isActive) {
    try {
        await API.users.activate(userId, isActive);
        showToast(`User ${isActive ? 'activated' : 'deactivated'} successfully`, 'success');
        await renderUsersPage();
    } catch (error) {
        console.error('Error toggling user status:', error);
        showToast(error.message || 'Error updating user status', 'error');
    }
}

async function deleteUser(userId, email) {
    // Inline confirmation - replace table with confirmation message
    const page = document.getElementById('settings');
    if (!page) {
        console.error('[USERS] Cannot delete: settings page not found');
        return;
    }
    
    // Store original content
    const cardBody = page.querySelector('.card-body');
    if (!cardBody) {
        console.error('[USERS] Cannot delete: card-body not found');
        return;
    }
    
    const originalContent = cardBody.innerHTML;
    
    // Show inline confirmation
    cardBody.innerHTML = `
        <div style="padding: 2rem; text-align: center; background: var(--bg-secondary); border-radius: 0.5rem;">
            <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--danger-color); margin-bottom: 1rem;"></i>
            <h4 style="margin-bottom: 1rem;">Confirm Delete User</h4>
            <p style="margin-bottom: 0.5rem; font-size: 1.1rem;"><strong>${escapeHtml(email)}</strong></p>
            <p style="margin-bottom: 1.5rem; color: var(--text-secondary);">Are you sure you want to delete this user?</p>
            <p style="margin-bottom: 2rem; color: var(--danger-color); font-size: 0.875rem;">⚠️ This action cannot be undone.</p>
            <div style="display: flex; gap: 1rem; justify-content: center;">
                <button class="btn btn-secondary" onclick="cancelDeleteUser()">
                    <i class="fas fa-times"></i> Cancel
                </button>
                <button class="btn btn-danger" onclick="confirmDeleteUser('${userId}', '${escapeHtml(email)}')">
                    <i class="fas fa-trash"></i> Delete User
                </button>
            </div>
        </div>
    `;
    
    // Store original content for restore
    window._deleteUserOriginalContent = originalContent;
}

function cancelDeleteUser() {
    const page = document.getElementById('settings');
    if (!page) return;
    
    const cardBody = page.querySelector('.card-body');
    if (cardBody && window._deleteUserOriginalContent) {
        cardBody.innerHTML = window._deleteUserOriginalContent;
        window._deleteUserOriginalContent = null;
    } else {
        // Fallback: reload page
        renderUsersPage();
    }
}

function toggleShowDeleted() {
    usersPageState.showDeleted = !usersPageState.showDeleted;
    renderUsersPage();
}

async function restoreUser(userId, email) {
    if (!confirm(`Are you sure you want to restore user "${email}"?`)) {
        return;
    }
    
    try {
        await API.users.restore(userId);
        showToast(`User "${email}" restored successfully`, 'success');
        await renderUsersPage();
    } catch (error) {
        console.error('Error restoring user:', error);
        showToast(error.message || 'Error restoring user', 'error');
    }
}

async function sendInvitationEmail(userId, email) {
    const button = document.getElementById(`send-invite-btn-${userId}`);
    if (!button) return;
    
    // Disable button while sending
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
    
    try {
        // Use shared Supabase client
        const supabaseClient = window.initSupabaseClient ? window.initSupabaseClient() : null;
        if (!supabaseClient) {
            throw new Error('Supabase client not available. Please check configuration.');
        }
        
        // Send invitation email via Supabase Auth password reset
        // This works for both first-time setup and password reset
        const { error } = await supabaseClient.auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/invite`
        });
        
        if (error) {
            throw error;
        }
        
        // Mark as sent in state
        usersPageState.invitationSent.add(userId);
        
        // Update badge from "Pending" to "Invitation Sent" without reloading
        const row = button.closest('tr');
        if (row) {
            const statusCell = row.querySelector('td:nth-child(5)'); // Status column
            if (statusCell) {
                const pendingBadge = statusCell.querySelector('.badge-warning');
                if (pendingBadge) {
                    pendingBadge.className = 'badge badge-info';
                    pendingBadge.textContent = 'Invitation Sent';
                }
            }
        }
        
        // Re-enable button but change text
        button.innerHTML = '<i class="fas fa-check"></i> Sent';
        button.classList.remove('btn-primary');
        button.classList.add('btn-success');
        button.disabled = true;
        
        showToast(`Invitation email sent to ${email}`, 'success');
    } catch (error) {
        console.error('Error sending invitation email:', error);
        showToast(error.message || 'Error sending invitation email', 'error');
        
        // Re-enable button on error
        button.disabled = false;
        button.innerHTML = '<i class="fas fa-paper-plane"></i> Send Invitation';
    }
}

async function confirmDeleteUser(userId, email) {
    const page = document.getElementById('settings');
    if (!page) return;
    
    // Show loading state
    const cardBody = page.querySelector('.card-body');
    if (cardBody) {
        cardBody.innerHTML = '<div style="text-align: center; padding: 2rem;"><p>Deleting user...</p></div>';
    }
    
    try {
        await API.users.delete(userId);
        showToast('User deleted successfully', 'success');
        // Clear stored content
        window._deleteUserOriginalContent = null;
        // Reload users list
        await renderUsersPage();
    } catch (error) {
        console.error('Error deleting user:', error);
        showToast(error.message || 'Error deleting user', 'error');
        // Restore original content on error
        if (cardBody && window._deleteUserOriginalContent) {
            cardBody.innerHTML = window._deleteUserOriginalContent;
            window._deleteUserOriginalContent = null;
        } else {
            await renderUsersPage();
        }
    }
}

// =====================================================
// TRANSACTION SETTINGS PAGE
// =====================================================

async function renderTransactionSettingsPage() {
    console.log('renderTransactionSettingsPage() called');
    const page = document.getElementById('settings');
    if (!page) return;
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-receipt"></i> Transaction Settings</h3>
            </div>
            <div class="card-body">
                <form id="transactionSettingsForm" onsubmit="saveTransactionSettings(event)">
                    <h4 style="margin-bottom: 1rem;">Transaction Options</h4>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="invoice_bill_no" checked>
                            <span>Invoice/Bill No.</span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="add_time_on_transactions">
                            <span>Add Time on Transactions</span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="cash_sale_by_default">
                            <span>Cash Sale by default</span>
                        </label>
                    </div>
                    
                    <h4 style="margin-top: 2rem; margin-bottom: 1rem;">Items</h4>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="inclusive_tax" checked>
                            <span>Inclusive/Exclusive Tax on Rate (Price/Unit)</span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="display_purchase_price" checked>
                            <span>Display Purchase Price of Items</span>
                        </label>
                    </div>
                    
                    <h4 style="margin-top: 2rem; margin-bottom: 1rem;">Taxes, Discount & Totals</h4>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="transaction_wise_tax" checked>
                            <span>Transaction wise Tax</span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="transaction_wise_discount" checked>
                            <span>Transaction wise Discount</span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-checkbox">
                            <input type="checkbox" name="round_off_total" checked>
                            <span>Round Off Total</span>
                        </label>
                    </div>
                    
                    <div style="margin-top: 2rem;">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Transaction Settings
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;
}

function saveTransactionSettings(event) {
    event.preventDefault();
    // TODO: Save transaction settings to backend/localStorage
    showToast('Transaction settings saved', 'success');
}

// Helper function
function escapeHtml(text) {
    if (!text) return '—';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Switch settings sub-page
function switchSettingsSubPage(subPage) {
    loadSettingsSubPage(subPage);
}

// Export functions - CRITICAL: Must run immediately
(function() {
    'use strict';
    try {
        console.log('[SETTINGS.JS] Exporting functions to window...');
        
        if (typeof window === 'undefined') {
            console.error('[SETTINGS.JS] ❌ window is undefined!');
            return;
        }
        
        // Core settings functions - EXPORT IMMEDIATELY
        window.loadSettings = loadSettings;
        window.loadSettingsSubPage = loadSettingsSubPage;
        window.switchSettingsSubPage = switchSettingsSubPage;
        window.updateSettingsSubNavActiveState = updateSettingsSubNavActiveState;
        
        // General settings
        window.saveGeneralSettings = saveGeneralSettings;
        window.resetGeneralSettings = resetGeneralSettings;
        
        // Company profile
        window.saveCompanyProfile = saveCompanyProfile;
        
        // Branches
        window.showCreateBranchModal = showCreateBranchModal;
        window.createBranch = createBranch;
        window.editBranch = editBranch;
        window.setCurrentBranch = setCurrentBranch;
        
        // Transaction settings
        window.saveTransactionSettings = saveTransactionSettings;
        
    // User management functions
    window.renderUsersPage = renderUsersPage;
    window.showCreateUserForm = showCreateUserForm;
    window.cancelCreateUser = cancelCreateUser;
    window.showCreateRoleForm = showCreateRoleForm;
    window.cancelCreateRole = cancelCreateRole;
    window.showEditUserForm = showEditUserForm;
    window.cancelEditUser = cancelEditUser;
    window.showRolesList = showRolesList;
    window.cancelRolesList = cancelRolesList;
    window.showEditRoleForm = showEditRoleForm;
    window.cancelEditRole = cancelEditRole;
    window.handleCreateUser = handleCreateUser;
    window.handleCreateRole = handleCreateRole;
    window.handleEditUser = handleEditUser;
    window.handleEditRole = handleEditRole;
    window.updateFormValidation = updateFormValidation;
    window.copyInvitationCode = copyInvitationCode;
    window.toggleUserActive = toggleUserActive;
    window.deleteUser = deleteUser;
    window.confirmDeleteUser = confirmDeleteUser;
    window.cancelDeleteUser = cancelDeleteUser;
    window.restoreUser = restoreUser;
    window.toggleShowDeleted = toggleShowDeleted;
    window.sendInvitationEmail = sendInvitationEmail;
        
        // Verify exports
        const exports = {
            loadSettings: typeof window.loadSettings,
            loadSettingsSubPage: typeof window.loadSettingsSubPage,
            renderUsersPage: typeof window.renderUsersPage
        };
        
        console.log('[SETTINGS.JS] ✅ Functions exported:', exports);
        
        // Double-check critical function
        if (typeof window.loadSettings !== 'function') {
            console.error('[SETTINGS.JS] ❌ CRITICAL: window.loadSettings is not a function!', typeof window.loadSettings);
        } else {
            console.log('[SETTINGS.JS] ✅ window.loadSettings is ready:', window.loadSettings);
        }
    } catch (error) {
        console.error('[SETTINGS.JS] ❌ ERROR during export:', error);
        console.error('[SETTINGS.JS] Error stack:', error.stack);
    }
})();
