// Stock Take Admin Dashboard
// For admins to manage multi-user stock take sessions

let currentSession = null;
let progressPollingInterval = null;

async function loadStockTakeAdmin() {
    const page = document.getElementById('stock-take-admin');
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
        
        renderStockTakeAdminPage();
        await loadSessions();
    } catch (error) {
        console.error('Error loading stock take admin:', error);
        page.innerHTML = `
            <div class="card">
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i>
                    <p>Error loading stock take admin: ${error.message}</p>
                </div>
            </div>
        `;
    }
}

function renderStockTakeAdminPage() {
    // Support both stock-take-admin and unified stock-take page
    const page = document.getElementById('stock-take-admin') || document.getElementById('stock-take');
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

async function showCreateSessionModal() {
    try {
        // Get list of users for counter selection
        const usersResponse = await API.users.list();
        const users = usersResponse.users || [];
        
        // Filter to users with counter role or all users
        const counterUsers = users.filter(u => 
            u.branch_roles && u.branch_roles.some(br => 
                br.branch_id === CONFIG.BRANCH_ID && 
                (br.role_name === 'counter' || br.role_name === 'admin' || br.role_name === 'auditor')
            )
        );
        
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <div class="modal-header">
                    <h3>Create Stock Take Session</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <div style="margin-bottom: 1rem;">
                        <label>Multi-User Session</label>
                        <input type="checkbox" id="isMultiUser" checked>
                        <small style="display: block; color: var(--text-secondary); margin-top: 0.25rem;">
                            Allow multiple counters to participate
                        </small>
                    </div>
                    
                    <div style="margin-bottom: 1rem;">
                        <label>Allowed Counters</label>
                        <div style="max-height: 200px; overflow-y: auto; border: 1px solid var(--border-color); padding: 0.5rem; border-radius: 4px;">
                            ${counterUsers.map(user => `
                                <label style="display: block; padding: 0.5rem; cursor: pointer;">
                                    <input type="checkbox" value="${user.id}" class="counter-checkbox">
                                    ${escapeHtml(user.full_name || user.email)}
                                </label>
                            `).join('')}
                        </div>
                        <small style="color: var(--text-secondary);">
                            Select users who can count items in this session
                        </small>
                    </div>
                    
                    <div style="margin-bottom: 1rem;">
                        <label>Notes (Optional)</label>
                        <textarea id="sessionNotes" class="form-input" rows="3" placeholder="Add any notes about this stock take session..."></textarea>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">Cancel</button>
                    <button class="btn btn-primary" onclick="createSession()">Create Session</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    } catch (error) {
        console.error('Error showing create session modal:', error);
        alert('Error loading users: ' + error.message);
    }
}

async function createSession() {
    try {
        const isMultiUser = document.getElementById('isMultiUser').checked;
        const checkboxes = document.querySelectorAll('.counter-checkbox:checked');
        const allowedCounters = Array.from(checkboxes).map(cb => cb.value);
        const notes = document.getElementById('sessionNotes').value;
        
        const sessionData = {
            branch_id: CONFIG.BRANCH_ID,
            is_multi_user: isMultiUser,
            allowed_counters: allowedCounters,
            assigned_shelves: {}, // Can be enhanced later
            notes: notes || null
        };
        
        const currentUser = await getCurrentUser();
        if (!currentUser) {
            alert('Unable to get current user');
            return;
        }
        
        await API.stockTake.createSession(sessionData, currentUser.id);
        
        // Close modal
        document.querySelector('.modal').remove();
        
        // Reload sessions
        await loadSessions();
        
        showNotification('Session created successfully', 'success');
    } catch (error) {
        console.error('Error creating session:', error);
        alert('Error creating session: ' + error.message);
    }
}

async function startSession(sessionId) {
    try {
        const currentUser = await getCurrentUser();
        if (!currentUser) {
            alert('Unable to get current user');
            return;
        }
        
        await API.stockTake.startSession(sessionId, currentUser.id);
        await loadSessions();
        showNotification('Session started successfully', 'success');
    } catch (error) {
        console.error('Error starting session:', error);
        alert('Error starting session: ' + error.message);
    }
}

async function pauseSession(sessionId) {
    try {
        const currentUser = await getCurrentUser();
        if (!currentUser) {
            alert('Unable to get current user');
            return;
        }
        
        await API.stockTake.updateSession(sessionId, { status: 'PAUSED' }, currentUser.id);
        await loadSessions();
        showNotification('Session paused', 'info');
    } catch (error) {
        console.error('Error pausing session:', error);
        alert('Error pausing session: ' + error.message);
    }
}

async function viewSessionDetails(sessionId) {
    try {
        const session = await API.stockTake.getSession(sessionId);
        currentSession = session;
        
        const detailsContainer = document.getElementById('sessionDetails');
        const titleContainer = document.getElementById('sessionDetailsTitle');
        const contentContainer = document.getElementById('sessionDetailsContent');
        
        detailsContainer.style.display = 'block';
        titleContainer.textContent = `Session: ${session.session_code}`;
        
        // Get progress
        const progress = await API.stockTake.getProgress(sessionId);
        
        contentContainer.innerHTML = `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
                <div class="card">
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">Status</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">
                        <span class="badge ${getStatusBadgeClass(session.status)}">${session.status}</span>
                    </div>
                </div>
                <div class="card">
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">Progress</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">${progress.progress_percent.toFixed(1)}%</div>
                </div>
                <div class="card">
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">Items Counted</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">${progress.total_counted} / ${progress.total_items}</div>
                </div>
                <div class="card">
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">Active Locks</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">${progress.total_locked}</div>
                </div>
            </div>
            
            <h4>Counter Progress</h4>
            <div style="margin-bottom: 2rem;">
                ${progress.counters.map(counter => `
                    <div class="card" style="margin-bottom: 1rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <strong>${escapeHtml(counter.counter_name)}</strong>
                            <span>${counter.progress_percent.toFixed(1)}%</span>
                        </div>
                        <div class="progress" style="height: 20px; margin-bottom: 0.5rem;">
                            <div class="progress-bar" style="width: ${counter.progress_percent}%;"></div>
                        </div>
                        <div style="font-size: 0.875rem; color: var(--text-secondary);">
                            Counted: ${counter.items_counted} / ${counter.items_assigned} items
                            ${counter.assigned_shelves.length > 0 ? `| Shelves: ${counter.assigned_shelves.join(', ')}` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
            
            <h4>Recent Counts</h4>
            <div class="table-container" style="max-height: 300px; overflow-y: auto;">
                <table style="width: 100%;">
                    <thead>
                        <tr>
                            <th>Item</th>
                            <th>Counter</th>
                            <th>Counted</th>
                            <th>System</th>
                            <th>Variance</th>
                            <th>Time</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${progress.recent_counts.map(count => `
                            <tr>
                                <td>${escapeHtml(count.item_name || 'Unknown')}</td>
                                <td>${escapeHtml(count.counter_name || 'Unknown')}</td>
                                <td>${count.counted_quantity}</td>
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
        
        // Start polling for progress updates if session is active
        if (session.status === 'ACTIVE') {
            startProgressPolling(sessionId);
        } else {
            stopProgressPolling();
        }
        
        // Scroll to details
        detailsContainer.scrollIntoView({ behavior: 'smooth' });
    } catch (error) {
        console.error('Error loading session details:', error);
        alert('Error loading session details: ' + error.message);
    }
}

function startProgressPolling(sessionId) {
    stopProgressPolling(); // Clear any existing interval
    
    progressPollingInterval = setInterval(async () => {
        try {
            const progress = await API.stockTake.getProgress(sessionId);
            updateProgressUI(progress);
        } catch (error) {
            console.error('Error polling progress:', error);
        }
    }, 5000); // Poll every 5 seconds
}

function stopProgressPolling() {
    if (progressPollingInterval) {
        clearInterval(progressPollingInterval);
        progressPollingInterval = null;
    }
}

function updateProgressUI(progress) {
    // Update progress display if session details are visible
    const contentContainer = document.getElementById('sessionDetailsContent');
    if (!contentContainer || !currentSession) return;
    
    // Re-render progress section
    // This is a simplified update - in production, you'd update specific elements
    if (currentSession) {
        viewSessionDetails(currentSession.id);
    }
}

// Helper functions
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

async function getCurrentUser() {
    try {
        // Get current user from auth state or config
        if (window.authState && window.authState.user) {
            return window.authState.user;
        }
        // Fallback: try to get from localStorage or config
        const userId = localStorage.getItem('userId') || CONFIG.USER_ID;
        if (userId) {
            return { id: userId };
        }
        return null;
    } catch (error) {
        console.error('Error getting current user:', error);
        return null;
    }
}

function showNotification(message, type = 'info') {
    // Simple notification - can be enhanced with a toast library
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
    window.loadStockTakeAdmin = loadStockTakeAdmin;
    window.renderStockTakeAdminPage = renderStockTakeAdminPage;
    window.loadSessions = loadSessions;
    window.showCreateSessionModal = showCreateSessionModal;
    window.createSession = createSession;
    window.startSession = startSession;
    window.pauseSession = pauseSession;
    window.viewSessionDetails = viewSessionDetails;
}
