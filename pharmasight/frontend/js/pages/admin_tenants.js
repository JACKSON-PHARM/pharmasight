/**
 * Admin Tenant Management Page
 * Manage all clients/tenants
 */
// API is available globally via window.API
// showNotification is available globally from utils.js (loaded as script)

let tenants = [];
let currentPage = 1;
let totalPages = 1;
const pageSize = 20;

// Initialize page
export async function init() {
    console.log('Admin Tenants page initialized');
    
    // Check admin authentication
    const adminToken = localStorage.getItem('admin_token');
    const isAdmin = localStorage.getItem('is_admin');
    
    if (!adminToken || isAdmin !== 'true') {
        // Check if user is logged in via Supabase (for tenant admins)
        if (window.AuthBootstrap) {
            const user = window.AuthBootstrap.getCurrentUser();
            const userEmail = user?.email?.toLowerCase();
            const adminEmails = ['pharmasightsolutions@gmail.com', 'admin@pharmasight.com'];
            
            if (user && adminEmails.includes(userEmail)) {
                // Tenant admin accessing admin panel - allow
                localStorage.setItem('is_admin', 'true');
            } else {
                // Not authenticated - redirect to login
                window.location.href = '/#login';
                return;
            }
        } else {
            // Not authenticated - redirect to login
            window.location.href = '/#login';
            return;
        }
    }
    
    setupEventListeners();
    await loadTenants();
}

function setupEventListeners() {
    // Search
    const searchInput = document.getElementById('tenant-search');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(handleSearch, 500));
    }
    
    // Status filter
    const statusFilter = document.getElementById('status-filter');
    if (statusFilter) {
        statusFilter.addEventListener('change', handleStatusFilter);
    }
    
    // Create tenant button
    const createBtn = document.getElementById('create-tenant-btn');
    if (createBtn) {
        createBtn.addEventListener('click', showCreateTenantModal);
    }
    
    // Pagination
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    if (prevBtn) prevBtn.addEventListener('click', () => changePage(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => changePage(1));
}

async function loadTenants(page = 1, search = '', status = '') {
    const tbody = document.getElementById('tenants-table-body');
    
    try {
        // Show loading state
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center">Loading tenants...</td>
                </tr>
            `;
        }
        
        const params = {
            skip: (page - 1) * pageSize,
            limit: pageSize
        };
        
        if (search) params.search = search;
        if (status) params.status = status;
        
        console.log('Loading tenants with params:', params);
        console.log('API available:', !!window.API);
        console.log('API.admin available:', !!window.API?.admin);
        console.log('API.admin.tenants available:', !!window.API?.admin?.tenants);
        
        if (!window.API || !window.API.admin || !window.API.admin.tenants) {
            throw new Error('API client not properly initialized. Please refresh the page.');
        }
        
        console.log('Calling API endpoint: /api/admin/tenants with params:', params);
        const response = await window.API.admin.tenants.list(params);
        
        console.log('Tenants response:', response);
        console.log('Response type:', typeof response);
        console.log('Response keys:', response ? Object.keys(response) : 'null');
        
        // Handle different response formats
        let tenantsList = null;
        let totalCount = 0;
        
        if (response) {
            // Check if response has tenants array directly
            if (Array.isArray(response)) {
                tenantsList = response;
                totalCount = response.length;
            }
            // Check if response has tenants property
            else if (response.tenants) {
                tenantsList = response.tenants;
                totalCount = response.total || response.tenants.length;
            }
            // Check if response is the data itself
            else if (response.data && response.data.tenants) {
                tenantsList = response.data.tenants;
                totalCount = response.data.total || response.data.tenants.length;
            }
        }
        
        if (tenantsList) {
            tenants = tenantsList;
            totalPages = Math.ceil(totalCount / pageSize);
            currentPage = page;
            
            console.log(`Loaded ${tenants.length} tenants, total: ${totalCount}`);
            renderTenants();
            updatePagination();
        } else {
            const errorMsg = 'Failed to load tenants: Invalid response format';
            console.error(errorMsg, response);
            if (tbody) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center" style="color: red;">
                            ${errorMsg}<br>
                            <small>Response: ${JSON.stringify(response)}</small>
                        </td>
                    </tr>
                `;
            }
            showNotification('Failed to load tenants', 'error');
        }
    } catch (error) {
        console.error('Error loading tenants:', error);
        const errorMsg = `Error loading tenants: ${error.message || 'Unknown error'}`;
        
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center" style="color: red; padding: 20px;">
                        <strong>${errorMsg}</strong><br>
                        <small>Check browser console (F12) for details</small>
                    </td>
                </tr>
            `;
        }
        showNotification(errorMsg, 'error');
    }
}

function renderTenants() {
    const tbody = document.getElementById('tenants-table-body');
    if (!tbody) return;
    
    if (tenants.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center" style="padding: 40px 20px;">
                    <p style="font-size: 1.1rem; color: #666; margin-bottom: 8px;">No organizations yet.</p>
                    <p style="font-size: 0.9rem; color: #999;">Create your first organization to get started.</p>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = tenants.map(tenant => {
        const isSuspended = (tenant.status || '').toLowerCase() === 'suspended' || (tenant.status || '').toLowerCase() === 'cancelled';
        const accessDropdownId = `access-dropdown-${tenant.id}`;
        return `
        <tr>
            <td>${escapeHtml(tenant.name)}</td>
            <td>
                <a href="https://${tenant.subdomain}.pharmasight.com" target="_blank">
                    ${tenant.subdomain}.pharmasight.com
                </a>
            </td>
            <td>
                ${escapeHtml(tenant.admin_email)}<br>
                ${tenant.phone ? `<small style="color: #666;">${escapeHtml(tenant.phone)}</small>` : '<small style="color: #999;">No phone</small>'}
            </td>
            <td>
                <span class="badge badge-${getStatusClass(tenant.status)}">
                    ${tenant.status}
                </span>
            </td>
            <td>${formatTrialEnd(tenant)}</td>
            <td>${formatDate(tenant.created_at)}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="viewTenant('${tenant.id}')" title="View / edit details, status & trial end date">
                    View
                </button>
                <button class="btn btn-sm btn-secondary" onclick="createInviteWithId('${tenant.id}')">
                    Invite
                </button>
                <div class="access-actions" style="display: inline-block; position: relative;">
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleAccessDropdown('${tenant.id}')" title="Extend trial, pause or resume access">
                        Access
                    </button>
                    <div id="${accessDropdownId}" class="access-dropdown" style="display: none;">
                        <button type="button" onclick="extendTrialDays('${tenant.id}', 7); closeAccessDropdown('${tenant.id}')">Extend +7 days</button>
                        <button type="button" onclick="extendTrialDays('${tenant.id}', 30); closeAccessDropdown('${tenant.id}')">Extend +30 days</button>
                        ${!isSuspended ? `<button type="button" onclick="setTenantStatus('${tenant.id}', 'suspended'); closeAccessDropdown('${tenant.id}')">Pause access</button>` : ''}
                        ${isSuspended ? `<button type="button" onclick="setTenantStatus('${tenant.id}', 'trial'); closeAccessDropdown('${tenant.id}')">Resume (trial)</button>` : ''}
                    </div>
                </div>
                <button class="btn btn-sm btn-danger" onclick="deleteTenant('${tenant.id}')" title="Remove tenant from list">
                    Delete
                </button>
            </td>
        </tr>
    `;
    }).join('');
}

function getStatusClass(status) {
    const classes = {
        'trial': 'warning',
        'active': 'success',
        'suspended': 'danger',
        'cancelled': 'secondary',
        'past_due': 'warning'
    };
    return classes[status] || 'secondary';
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString();
}

function formatTrialEnd(tenant) {
    if (!tenant.trial_ends_at) return '—';
    const end = new Date(tenant.trial_ends_at);
    const now = new Date();
    const daysLeft = Math.ceil((end - now) / (1000 * 60 * 60 * 24));
    const dateStr = end.toLocaleDateString();
    if (tenant.status === 'trial' && daysLeft <= 0) return `<span title="${dateStr}">Expired</span>`;
    if (tenant.status === 'trial' && daysLeft > 0) return `<span title="${dateStr}">${dateStr} <small>(${daysLeft}d)</small></span>`;
    return dateStr;
}

function setTrialDays(days) {
    const input = document.getElementById('tenant-trial-ends-at');
    if (!input) return;
    const d = new Date();
    d.setDate(d.getDate() + days);
    input.value = d.toISOString().slice(0, 10);
}

/** Extend or reduce trial by adding N days to current trial_ends_at (or from today if null/past). */
async function extendTrialDays(tenantId, addDays) {
    const tenant = tenants.find(t => t.id === tenantId);
    if (!tenant) return;
    let newEnd = new Date();
    if (tenant.trial_ends_at) {
        const end = new Date(tenant.trial_ends_at);
        if (end > newEnd) newEnd = end;
    }
    newEnd.setDate(newEnd.getDate() + addDays);
    const trial_ends_at = newEnd.toISOString().slice(0, 10) + 'T12:00:00.000Z';
    try {
        await window.API.admin.tenants.update(tenantId, { trial_ends_at });
        showNotification(`Trial ${addDays >= 0 ? 'extended' : 'reduced'} by ${Math.abs(addDays)} days`, 'success');
        await loadTenants();
    } catch (e) {
        showNotification('Failed to update trial: ' + (e.message || 'Unknown error'), 'error');
    }
}

/** Set tenant status (e.g. suspended to pause, trial/active to resume). */
async function setTenantStatus(tenantId, newStatus) {
    const tenant = tenants.find(t => t.id === tenantId);
    if (!tenant) return;
    const labels = { suspended: 'Pause access', active: 'Resume (active)', trial: 'Resume (trial)' };
    const action = labels[newStatus] || newStatus;
    try {
        await window.API.admin.tenants.update(tenantId, { status: newStatus });
        showNotification(`Organization ${action.toLowerCase()} updated`, 'success');
        await loadTenants();
    } catch (e) {
        showNotification('Failed to update status: ' + (e.message || 'Unknown error'), 'error');
    }
}

function updatePagination() {
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    const pageInfo = document.getElementById('page-info');
    
    if (prevBtn) prevBtn.disabled = currentPage === 1;
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
    if (pageInfo) pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
}

function handleSearch(e) {
    const search = e.target.value.trim();
    loadTenants(1, search, document.getElementById('status-filter')?.value || '');
}

function handleStatusFilter(e) {
    const status = e.target.value;
    loadTenants(1, document.getElementById('tenant-search')?.value || '', status);
}

function changePage(delta) {
    const newPage = currentPage + delta;
    if (newPage >= 1 && newPage <= totalPages) {
        loadTenants(newPage);
    }
}

function showCreateTenantModal() {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>Create new organization</h2>
            <form id="create-tenant-form">
                <div class="form-group">
                    <label>Company Name <span style="color: red;">*</span></label>
                    <input type="text" name="name" required>
                </div>
                <div class="form-group">
                    <label>Admin Email <span style="color: red;">*</span></label>
                    <input type="email" name="admin_email" required placeholder="admin@company.com">
                    <small style="color: #666;">Used for communication (password resets, etc.)</small>
                </div>
                <div class="form-group">
                    <label>Admin Full Name <span style="color: red;">*</span></label>
                    <input type="text" name="admin_full_name" required placeholder="Dr. Jackson or Sarah Wambui">
                    <small style="color: #666;">Used to generate username (e.g., "Dr. Jackson" → "D-JACKSON")</small>
                </div>
                <div class="form-group">
                    <label>Phone Number</label>
                    <input type="tel" name="phone" placeholder="+254...">
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="this.closest('.modal').remove()">
                        Cancel
                    </button>
                    <button type="submit" class="btn btn-primary">
                        Create
                    </button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    modal.querySelector('form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        await createTenant({
            name: formData.get('name'),
            admin_email: formData.get('admin_email'),
            admin_full_name: formData.get('admin_full_name'),
            phone: formData.get('phone') || null
        });
        modal.remove();
    });
}

async function createTenant(data) {
    try {
        const response = await window.API.admin.tenants.create(data);
        if (response) {
            showNotification('Organization created successfully', 'success');
            await loadTenants();
        } else {
            showNotification('Failed to create organization', 'error');
        }
    } catch (error) {
        console.error('Error creating organization:', error);
        showNotification('Error creating organization: ' + (error.message || 'Unknown error'), 'error');
    }
}

// Wrapper function to handle onclick
async function createInviteWithId(tenantId) {
    await createInvite(tenantId);
}

async function createInvite(tenantId) {
    // Find the button BEFORE async operations and save original text
    const buttons = document.querySelectorAll(`button[onclick*="createInviteWithId('${tenantId}')"]`);
    const button = buttons.length > 0 ? buttons[0] : null;
    const originalText = button ? button.textContent : 'Invite';
    
    try {
        // Show loading state
        if (button) {
            button.disabled = true;
            button.textContent = 'Creating...';
        }
        
        const response = await window.API.admin.tenants.invites.create(tenantId, {
            expires_in_days: 7,
            send_email: true
        });
        
        if (response && response.token) {
            const tenant = tenants.find(t => t.id === tenantId);
            // Use server-provided URL (from APP_PUBLIC_URL) so link works when opened on Render; fallback to current origin
            const url = (response.setup_url && response.setup_url.trim()) || `${window.location.origin}/setup?token=${response.token}`;
            const emailSent = response.email_sent === true;
            
            if (emailSent && window.showNotification) {
                window.showNotification(`Invite created. Email queued for ${tenant?.admin_email || 'their email'} (check Render logs for delivery status).`, 'success');
            } else if (!emailSent && window.showNotification) {
                window.showNotification('Invite created. Email not sent — SMTP not configured. Check Render environment variables (SMTP_HOST, SMTP_USER, SMTP_PASSWORD).', 'warning');
            }
            
            showInviteModal({
                url,
                tenantName: tenant?.name || 'Organization',
                username: response.username,
                emailSent,
                adminEmail: tenant?.admin_email || ''
            });
        } else {
            throw new Error('Invalid response from server');
        }
    } catch (error) {
        console.error('Error creating invite:', error);
        const errorMsg = error.message || 'Unknown error';
        const errorDetail = error.data?.detail || error.data?.message || '';
        const fullErrorMsg = errorDetail ? `${errorMsg}: ${errorDetail}` : errorMsg;
        
        if (window.showNotification) {
            window.showNotification('Error creating invite: ' + fullErrorMsg, 'error');
        } else {
            alert('Error creating invite: ' + fullErrorMsg);
        }
    } finally {
        // ALWAYS restore button state, even on error
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }
}

function showInviteModal(opts) {
    const { url, tenantName, username, emailSent, adminEmail } = opts;
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;';

    const statusMsg = emailSent
        ? `The invite email has been queued for <strong>${escapeHtml(adminEmail)}</strong>. If SMTP is configured, they will receive it shortly. Check Render logs for delivery status.`
        : 'Email could not be sent because SMTP is not configured. Share the link below with the client so they can complete setup. To enable email, set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD in Render environment variables.';

    modal.innerHTML = `
        <div class="modal-content" style="background: white; padding: 30px; border-radius: 8px; max-width: 600px; width: 90%;">
            <h2 style="margin-top: 0;">${emailSent ? 'Invite Sent' : 'Invite Link Created'}</h2>
            <p><strong>Organization:</strong> ${escapeHtml(tenantName)}</p>
            ${username ? `<p><strong>Generated Username:</strong> <code style="background: #f0f0f0; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${escapeHtml(username)}</code></p>
            <p style="color: #666; font-size: 14px;">They will use this username to log in after setting their password.</p>` : ''}
            <p>${statusMsg}</p>
            <div style="background: #f5f5f5; padding: 15px; border-radius: 4px; margin: 15px 0; word-break: break-all; font-family: monospace; font-size: 12px;">
                ${escapeHtml(url)}
            </div>
            <div style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px;">
                <button class="btn btn-secondary" data-action="close">Close</button>
                <button class="btn btn-primary" data-action="copy" data-invite-url="">Copy link</button>
            </div>
        </div>
    `;

    const copyBtn = modal.querySelector('[data-action="copy"]');
    copyBtn.dataset.inviteUrl = url;
    copyBtn.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(url);
            if (window.showNotification) window.showNotification('Link copied to clipboard', 'success');
            else alert('Link copied!');
        } catch (e) {
            if (window.showNotification) window.showNotification('Could not copy link', 'error');
            else alert('Could not copy. Please select and copy the link manually.');
        }
    });

    modal.querySelector('[data-action="close"]').addEventListener('click', () => modal.remove());

    document.body.appendChild(modal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });
}

async function deleteTenant(tenantId) {
    const tenant = tenants.find(t => t.id === tenantId);
    const name = tenant ? tenant.name : 'this organization';
    if (!confirm(`Remove "${name}" from the list? It will be marked as cancelled and will no longer appear. You can create a new organization with the same details later.`)) {
        return;
    }
    try {
        await window.API.admin.tenants.delete(tenantId);
        if (window.showNotification) window.showNotification('Organization removed from list.', 'success');
        await loadTenants();
    } catch (error) {
        const msg = error?.data?.detail || error?.message || 'Failed to remove organization';
        if (window.showNotification) window.showNotification(msg, 'error');
    }
}

function viewTenant(tenantId) {
    const tenant = tenants.find(t => t.id === tenantId);
    if (!tenant) {
        if (window.showNotification) window.showNotification('Organization not found', 'error');
        return;
    }
    showTenantDetailModal(tenant);
}

async function showTenantDetailModal(tenant) {
    // Single-DB multi-company: no per-tenant database or storage config in UI.
    const isProvisioned = !!tenant.is_provisioned;

    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000; overflow-y: auto;';
    
    modal.innerHTML = `
        <div class="modal-content" style="background: white; padding: 30px; border-radius: 8px; max-width: 800px; width: 90%; margin: 20px;">
            <h2 style="margin-top: 0;">Organization details</h2>
            <form id="tenant-edit-form">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px;">
                    <div class="form-group">
                        <label><strong>Company Name:</strong></label>
                        <input type="text" name="name" value="${escapeHtml(tenant.name)}" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                    </div>
                    <div>
                        <strong>Subdomain:</strong>
                        <p><a href="https://${tenant.subdomain}.pharmasight.com" target="_blank">${tenant.subdomain}.pharmasight.com</a></p>
                    </div>
                    <div class="form-group">
                        <label><strong>Admin Email:</strong></label>
                        <input type="email" name="admin_email" value="${escapeHtml(tenant.admin_email)}" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                        <small style="color: #666;">Used for communication (password resets, etc.)</small>
                    </div>
                    <div class="form-group">
                        <label><strong>Admin Full Name:</strong></label>
                        <input type="text" name="admin_full_name" value="${escapeHtml(tenant.admin_full_name || '')}" placeholder="Dr. Jackson" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                        <small style="color: #666;">For username generation (e.g., "Dr. Jackson" → "D-JACKSON")</small>
                    </div>
                    <div class="form-group">
                        <label><strong>Phone Number:</strong></label>
                        <input type="tel" name="phone" value="${escapeHtml(tenant.phone || '')}" placeholder="+254..." style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                    </div>
                    <div class="form-group">
                        <label><strong>Status:</strong></label>
                        <select name="status" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                            <option value="trial" ${tenant.status === 'trial' ? 'selected' : ''}>Trial</option>
                            <option value="active" ${tenant.status === 'active' ? 'selected' : ''}>Active</option>
                            <option value="suspended" ${tenant.status === 'suspended' ? 'selected' : ''}>Suspended</option>
                            <option value="past_due" ${tenant.status === 'past_due' ? 'selected' : ''}>Past due</option>
                            <option value="cancelled" ${tenant.status === 'cancelled' ? 'selected' : ''}>Cancelled</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label><strong>Trial ends at:</strong></label>
                        <input type="date" id="tenant-trial-ends-at" value="${tenant.trial_ends_at ? new Date(tenant.trial_ends_at).toISOString().slice(0, 10) : ''}" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                        <small style="color: #666;">Controls how many days the client can use the app on trial. Leave empty for no trial end.</small>
                        <div style="margin-top: 6px;">
                            <button type="button" class="btn btn-sm btn-secondary" onclick="window.setTrialDays(14)">+14 days</button>
                            <button type="button" class="btn btn-sm btn-secondary" onclick="window.setTrialDays(30)">+30 days</button>
                            <button type="button" class="btn btn-sm btn-secondary" onclick="window.setTrialDays(-7)">−7 days</button>
                            <button type="button" class="btn btn-sm btn-secondary" onclick="window.setTrialDays(0)">Set to today</button>
                        </div>
                    </div>
                    <div>
                        <strong>Created:</strong>
                        <p>${formatDate(tenant.created_at)}</p>
                    </div>
                </div>
                <div style="margin-top: 24px; padding: 16px; background: #f0f7ff; border-radius: 8px; border: 1px solid #c5d9f0;">
                    <p style="margin: 0 0 6px 0;"><strong>Data &amp; storage</strong></p>
                    <p style="margin: 0; color: #555; font-size: 0.9rem;">This organization uses the shared app database. Data is isolated by company. Storage (logos, PO PDFs) uses the app-wide Supabase project; assets are scoped by organization.</p>
                </div>
                <div style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0;">
                    <button type="button" class="btn btn-secondary" onclick="this.closest('.modal').remove()">Close</button>
                    <button type="button" class="btn btn-secondary" id="tenant-create-invite-btn" onclick="createInviteWithId('${tenant.id}')">Create Invite</button>
                    <button type="submit" class="btn btn-primary">Save Changes</button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Handle form submission
    const form = modal.querySelector('#tenant-edit-form');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(form);
        const trialEndInput = modal.querySelector('#tenant-trial-ends-at');
        const trialEndVal = trialEndInput && trialEndInput.value ? trialEndInput.value : null;
        const updateData = {
            name: formData.get('name'),
            admin_email: formData.get('admin_email'),
            admin_full_name: formData.get('admin_full_name') || null,
            phone: formData.get('phone') || null,
            status: formData.get('status') || undefined,
            trial_ends_at: trialEndVal ? new Date(trialEndVal + 'T12:00:00Z').toISOString() : null
        };
        
        try {
            const response = await window.API.admin.tenants.update(tenant.id, updateData);
            if (response) {
                if (window.showNotification) {
                    window.showNotification('Organization updated successfully', 'success');
                }
                modal.remove();
                await loadTenants(); // Refresh the list
            }
        } catch (error) {
            console.error('Error updating tenant:', error);
            let errorMsg = 'Unknown error';
            const detail = error?.data?.detail ?? error?.response?.data?.detail;
            if (detail) {
                errorMsg = Array.isArray(detail)
                    ? detail.map((d) => (d && typeof d.msg === 'string' ? d.msg : JSON.stringify(d))).join('; ')
                    : (typeof detail === 'string' ? detail : JSON.stringify(detail));
            } else if (error?.message && String(error.message) !== '[object Object]') {
                errorMsg = error.message;
            }
            if (window.showNotification) {
                window.showNotification('Error updating organization: ' + errorMsg, 'error');
            } else {
                alert('Error updating organization: ' + errorMsg);
            }
        }
    });
    
    // Close on background click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function toggleAccessDropdown(tenantId) {
    const id = `access-dropdown-${tenantId}`;
    const el = document.getElementById(id);
    if (!el) return;
    const isOpen = el.style.display === 'block';
    document.querySelectorAll('.access-dropdown').forEach(d => { d.style.display = 'none'; });
    el.style.display = isOpen ? 'none' : 'block';
}

function closeAccessDropdown(tenantId) {
    const el = document.getElementById(`access-dropdown-${tenantId}`);
    if (el) el.style.display = 'none';
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.access-actions')) {
        document.querySelectorAll('.access-dropdown').forEach(d => { d.style.display = 'none'; });
    }
});

// Export for global access
window.viewTenant = viewTenant;
window.deleteTenant = deleteTenant;
window.createInvite = createInvite;
window.createInviteWithId = createInviteWithId;
window.setTrialDays = setTrialDays;
window.extendTrialDays = extendTrialDays;
window.setTenantStatus = setTenantStatus;
window.toggleAccessDropdown = toggleAccessDropdown;
window.closeAccessDropdown = closeAccessDropdown;
