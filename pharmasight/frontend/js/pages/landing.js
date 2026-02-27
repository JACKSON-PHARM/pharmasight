/**
 * Landing Page - Lightweight home with minimal queries.
 * Shows welcome, current branch, optional quick stats, and navigation tiles.
 * No heavy dashboard queries run here.
 */

function getBranchIdForLanding() {
    const branch = typeof BranchContext !== 'undefined' && BranchContext.getBranch ? BranchContext.getBranch() : null;
    if (branch && branch.id) return branch.id;
    if (typeof CONFIG !== 'undefined' && CONFIG.BRANCH_ID) return CONFIG.BRANCH_ID;
    try {
        const saved = localStorage.getItem('pharmasight_config');
        if (saved) {
            const c = JSON.parse(saved);
            if (c.BRANCH_ID) return c.BRANCH_ID;
        }
    } catch (e) { /* ignore */ }
    return null;
}

async function loadLanding() {
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'landing') return;
    const page = document.getElementById('landing');
    if (!page) return;

    const user = typeof AuthBootstrap !== 'undefined' && AuthBootstrap.getCurrentUser ? AuthBootstrap.getCurrentUser() : null;
    const displayName = (user?.user_metadata?.username) || (user?.email || user?.user_metadata?.full_name || 'User');
    const branch = typeof BranchContext !== 'undefined' && BranchContext.getBranch ? BranchContext.getBranch() : null;
    const branchName = branch ? (branch.name || 'This branch') : 'No branch selected';

    const welcomeEl = document.getElementById('landingWelcome');
    const branchEl = document.getElementById('landingBranch');
    if (welcomeEl) welcomeEl.textContent = 'Welcome, ' + (displayName || 'User');
    if (branchEl) branchEl.textContent = branchName;

    // Optional: one lightweight call for "pending orders today" (single count) - only if we have branch + company
    const branchId = getBranchIdForLanding();
    const pendingEl = document.getElementById('landingPendingOrders');
    if (pendingEl && branchId && typeof CONFIG !== 'undefined' && CONFIG.COMPANY_ID && typeof API !== 'undefined' && API.orderBook && typeof API.orderBook.getTodaySummary === 'function') {
        try {
            const summary = await API.orderBook.getTodaySummary(branchId, CONFIG.COMPANY_ID, 0);
            const count = (summary && summary.pending_count != null) ? summary.pending_count : 0;
            pendingEl.textContent = count;
        } catch (e) {
            pendingEl.textContent = '—';
        }
    } else if (pendingEl) {
        pendingEl.textContent = '—';
    }
}

window.loadLanding = loadLanding;
