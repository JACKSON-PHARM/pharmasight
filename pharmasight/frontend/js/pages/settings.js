// Settings Page - Multi-section Settings Management

let currentSettingsSubPage = 'general'; // 'general', 'company', 'branches', 'users', 'transaction'

// Initialize settings page
async function loadSettings() {
    console.log('loadSettings() called');
    const page = document.getElementById('settings');
    if (!page) {
        console.error('Settings page element not found!');
        return;
    }
    
    // Show the page
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
    
    console.log('Loading settings sub-page:', currentSettingsSubPage);
    // Load sub-page based on current selection
    await loadSettingsSubPage(currentSettingsSubPage);
}

// Load specific settings sub-page
async function loadSettingsSubPage(subPage) {
    console.log('loadSettingsSubPage() called with:', subPage);
    currentSettingsSubPage = subPage;
    const page = document.getElementById('settings');
    
    if (!page) {
        console.error('Settings page element not found in loadSettingsSubPage!');
        return;
    }
    
    // Ensure page is visible
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    page.classList.add('active');
    
    switch(subPage) {
        case 'general':
            await renderGeneralSettingsPage();
            break;
        case 'company':
            await renderCompanyProfilePage();
            break;
        case 'branches':
            await renderBranchesPage();
            break;
        case 'users':
            await renderUsersPage();
            break;
        case 'transaction':
            await renderTransactionSettingsPage();
            break;
        default:
            await renderGeneralSettingsPage();
    }
    
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
    
    try {
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

async function renderUsersPage() {
    console.log('renderUsersPage() called');
    const page = document.getElementById('settings');
    if (!page) return;
    
    // Load users and roles
    let users = [];
    let roles = [];
    let branches = [];
    
    try {
        const usersResponse = await API.users.list();
        users = usersResponse.users || [];
        
        roles = await API.users.listRoles();
        
        if (CONFIG.COMPANY_ID) {
            branches = await API.branch.list(CONFIG.COMPANY_ID);
        }
    } catch (error) {
        console.error('Error loading users:', error);
        showToast('Error loading users. Please try again.', 'error');
    }
    
    page.innerHTML = `
        <div class="card">
            <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <h3 class="card-title"><i class="fas fa-users"></i> Users & Roles</h3>
                <button class="btn btn-primary" onclick="showCreateUserModal()">
                    <i class="fas fa-plus"></i> New User
                </button>
            </div>
            <div class="card-body">
                ${users.length === 0 ? `
                    <div style="text-align: center; padding: 3rem;">
                        <i class="fas fa-users" style="font-size: 3rem; color: var(--text-secondary); margin-bottom: 1rem;"></i>
                        <p style="color: var(--text-secondary);">No users found</p>
                        <button class="btn btn-primary" onclick="showCreateUserModal()">
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
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Role(s)</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Status</th>
                                    <th style="padding: 0.75rem; border-bottom: 2px solid var(--border-color); text-align: left;">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${users.map(user => `
                                    <tr>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${escapeHtml(user.email)}
                                            ${user.is_pending ? '<span class="badge badge-warning" style="margin-left: 0.5rem;">Pending</span>' : ''}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${escapeHtml(user.full_name || '—')}
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            ${user.branch_roles.length > 0 
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
                                                ? '<span class="badge badge-warning" style="margin-left: 0.25rem;">Password Pending</span>' 
                                                : ''
                                            }
                                        </td>
                                        <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                                            <div style="display: flex; gap: 0.5rem;">
                                                ${user.is_pending && user.invitation_code 
                                                    ? `<button class="btn btn-outline btn-sm" onclick="copyInvitationCode('${user.invitation_code}', '${user.email}')" title="Copy Invitation Code">
                                                        <i class="fas fa-copy"></i>
                                                    </button>`
                                                    : ''
                                                }
                                                <button class="btn btn-outline btn-sm" onclick="editUser('${user.id}')" title="Edit">
                                                    <i class="fas fa-edit"></i>
                                                </button>
                                                ${user.is_active 
                                                    ? `<button class="btn btn-outline btn-sm" onclick="toggleUserActive('${user.id}', false)" title="Deactivate">
                                                        <i class="fas fa-ban"></i>
                                                    </button>`
                                                    : `<button class="btn btn-outline btn-sm" onclick="toggleUserActive('${user.id}', true)" title="Activate">
                                                        <i class="fas fa-check"></i>
                                                    </button>`
                                                }
                                                <button class="btn btn-outline btn-sm btn-danger" onclick="deleteUser('${user.id}', '${user.email}')" title="Delete">
                                                    <i class="fas fa-trash"></i>
                                                </button>
                                            </div>
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

function showCreateUserModal() {
    // Load branches and roles for the form
    Promise.all([
        CONFIG.COMPANY_ID ? API.branch.list(CONFIG.COMPANY_ID) : Promise.resolve([]),
        API.users.listRoles()
    ]).then(([branches, roles]) => {
        const content = `
            <form id="createUserForm" onsubmit="createUser(event)">
                <div class="form-group">
                    <label class="form-label">Email *</label>
                    <input type="email" class="form-input" name="email" required 
                           placeholder="user@example.com">
                </div>
                <div class="form-group">
                    <label class="form-label">Full Name</label>
                    <input type="text" class="form-input" name="full_name" 
                           placeholder="John Doe">
                </div>
                <div class="form-group">
                    <label class="form-label">Phone</label>
                    <input type="tel" class="form-input" name="phone" 
                           placeholder="+254700000000">
                </div>
                <div class="form-group">
                    <label class="form-label">Role *</label>
                    <select class="form-input" name="role_name" required>
                        <option value="">Select a role</option>
                        ${roles.map(role => 
                            `<option value="${escapeHtml(role.role_name)}">${escapeHtml(role.role_name)} - ${escapeHtml(role.description || '')}</option>`
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
                    <small style="color: var(--text-secondary);">
                        Assign user to a specific branch, or leave empty to assign later
                    </small>
                </div>
            </form>
        `;
        
        const footer = `
            <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button class="btn btn-primary" type="submit" form="createUserForm">
                <i class="fas fa-save"></i> Create User
            </button>
        `;
        
        showModal('Create New User', content, footer);
    }).catch(error => {
        console.error('Error loading form data:', error);
        showToast('Error loading form data. Please try again.', 'error');
    });
}

async function createUser(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const userData = {
        email: formData.get('email'),
        full_name: formData.get('full_name') || null,
        phone: formData.get('phone') || null,
        role_name: formData.get('role_name'),
        branch_id: formData.get('branch_id') || null
    };
    
    try {
        const result = await API.users.create(userData);
        showToast(result.message || 'User created successfully!', 'success');
        
        // Show invitation code
        if (result.invitation_code) {
            const inviteMessage = `Invitation Code: ${result.invitation_code}\n\nShare this code with the user for first-time login.`;
            setTimeout(() => {
                if (confirm(inviteMessage + '\n\nClick OK to copy the code to clipboard.')) {
                    navigator.clipboard.writeText(result.invitation_code);
                    showToast('Invitation code copied to clipboard!', 'success');
                }
            }, 500);
        }
        
        closeModal();
        await renderUsersPage();
    } catch (error) {
        console.error('Error creating user:', error);
        showToast(error.message || 'Error creating user', 'error');
    }
}

function copyInvitationCode(code, email) {
    navigator.clipboard.writeText(code).then(() => {
        showToast(`Invitation code for ${email} copied to clipboard: ${code}`, 'success');
    }).catch(() => {
        prompt(`Invitation code for ${email}:`, code);
    });
}

async function editUser(userId) {
    try {
        const user = await API.users.get(userId);
        showToast('User editing coming soon. Use activate/deactivate for now.', 'info');
        // TODO: Implement edit user modal
    } catch (error) {
        console.error('Error loading user:', error);
        showToast('Error loading user details', 'error');
    }
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
    if (!confirm(`Are you sure you want to delete user "${email}"?\n\nThis action cannot be undone.`)) {
        return;
    }
    
    try {
        await API.users.delete(userId);
        showToast('User deleted successfully', 'success');
        await renderUsersPage();
    } catch (error) {
        console.error('Error deleting user:', error);
        showToast(error.message || 'Error deleting user', 'error');
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

// Export functions
if (typeof window !== 'undefined') {
    window.loadSettings = loadSettings;
    window.loadSettingsSubPage = loadSettingsSubPage;
    window.switchSettingsSubPage = switchSettingsSubPage;
    window.updateSettingsSubNavActiveState = updateSettingsSubNavActiveState;
    window.saveGeneralSettings = saveGeneralSettings;
    window.resetGeneralSettings = resetGeneralSettings;
    window.saveCompanyProfile = saveCompanyProfile;
    window.showCreateBranchModal = showCreateBranchModal;
    window.createBranch = createBranch;
    window.editBranch = editBranch;
    window.setCurrentBranch = setCurrentBranch;
    window.saveTransactionSettings = saveTransactionSettings;
    // User management functions
    window.showCreateUserModal = showCreateUserModal;
    window.createUser = createUser;
    window.copyInvitationCode = copyInvitationCode;
    window.editUser = editUser;
    window.toggleUserActive = toggleUserActive;
    window.deleteUser = deleteUser;
}
