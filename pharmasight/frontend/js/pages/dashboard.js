// Dashboard Page

/** Branch for stock/counts: session branch (same as header), then CONFIG, then localStorage. */
function getBranchIdForStock() {
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

async function loadDashboard() {
    // Strict page ownership: only run dashboard logic when dashboard is the active page
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'dashboard') {
        return;
    }
    const page = document.getElementById('dashboard');
    if (!page) return;
    // Skip when no company/branch (avoids invalid API calls)
    if (!CONFIG.COMPANY_ID) {
        const ti = document.getElementById('totalItems');
        if (ti) ti.textContent = '0';
        const ts = document.getElementById('totalStock');
        if (ts) ts.textContent = formatCurrency(0);
        const td = document.getElementById('todaySales');
        if (td) td.textContent = formatCurrency(0);
        const ex = document.getElementById('expiringItems');
        if (ex) ex.textContent = '0';
        return;
    }

    // Use session branch (same as header) so dashboard matches branch context
    const branchId = getBranchIdForStock();

    // Placeholders first
    document.getElementById('totalItems').textContent = '0';
    document.getElementById('totalStock').textContent = formatCurrency(0);
    document.getElementById('todaySales').textContent = formatCurrency(0);
    document.getElementById('expiringItems').textContent = '0';

    try {
        // Total items in stock (distinct items with stock > 0 at this branch)
        if (branchId && API.inventory && typeof API.inventory.getItemsInStockCount === 'function') {
            try {
                const countData = await API.inventory.getItemsInStockCount(branchId);
                document.getElementById('totalItems').textContent = countData.count != null ? countData.count : 0;
            } catch (err) {
                console.warn('Items-in-stock count failed:', err);
            }
        }

        // Today's sales for the logged-in user (per-user)
        if (branchId && API.sales && typeof API.sales.getTodaySummary === 'function') {
            try {
                const userId = CONFIG.USER_ID || null;
                const summary = await API.sales.getTodaySummary(branchId, userId);
                const total = parseFloat(summary.total_inclusive || summary.total_exclusive || 0);
                document.getElementById('todaySales').textContent = formatCurrency(total);
            } catch (err) {
                console.warn('Today summary failed:', err);
            }
        }

        // Load stock summary: show total units in stock (getAllStock returns items with stock > 0)
        if (branchId && API.inventory && typeof API.inventory.getAllStock === 'function') {
            try {
                const stockList = await API.inventory.getAllStock(branchId);
                const totalUnits = (stockList && Array.isArray(stockList)) ? stockList.reduce((sum, row) => sum + (Number(row.stock) || 0), 0) : 0;
                // totalStock card: show unit count (e.g. "1,234 units")
                const totalStockEl = document.getElementById('totalStock');
                if (totalStockEl) totalStockEl.textContent = totalUnits.toLocaleString() + ' unit' + (totalUnits !== 1 ? 's' : '');
            } catch (error) {
                console.warn('Failed to load stock summary:', error);
                const totalStockEl = document.getElementById('totalStock');
                if (totalStockEl) totalStockEl.textContent = formatCurrency(0);
            }
        } else {
            const totalStockEl = document.getElementById('totalStock');
            if (totalStockEl) totalStockEl.textContent = formatCurrency(0);
        }
    } catch (error) {
        console.error('Error loading dashboard:', error);
        // Only surface toast when user is already on dashboard (avoid noise during navigation)
        const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
        if (active === 'dashboard' && typeof showToast === 'function') {
            showToast('Error loading dashboard data', 'error');
        }
    }
}

// Export
window.loadDashboard = loadDashboard;

