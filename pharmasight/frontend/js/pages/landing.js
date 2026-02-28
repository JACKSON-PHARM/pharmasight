/**
 * Landing Page - Lightweight home with minimal queries.
 * Shows welcome (user name, not email), current branch, quick stats, quick item search, and navigation tiles.
 */

/** Prefer full name or username over email for display (aligned with status bar). */
async function getLandingDisplayName(user) {
    if (!user) return 'User';
    if (user.full_name && user.full_name.trim()) return user.full_name.trim();
    if (user.username && user.username.trim()) return user.username.trim();
    if (user.user_metadata) {
        if (user.user_metadata.full_name && user.user_metadata.full_name.trim()) return user.user_metadata.full_name.trim();
        if (user.user_metadata.username && user.user_metadata.username.trim()) return user.user_metadata.username.trim();
    }
    const fromStorage = typeof localStorage !== 'undefined' && localStorage.getItem('pharmasight_username');
    if (fromStorage && fromStorage.trim()) return fromStorage.trim();
    if (typeof window.resolveUserDisplayName === 'function') {
        try { return await window.resolveUserDisplayName(user) || user.email || 'User'; } catch (_) {}
    }
    return user.email || 'User';
}

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
    const displayName = await getLandingDisplayName(user);
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

    // Item search is global (sticky bar); no per-page bind needed.
}

window.loadLanding = loadLanding;
window.getLandingDisplayName = getLandingDisplayName;
