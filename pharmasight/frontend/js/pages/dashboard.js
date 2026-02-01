// Dashboard Page

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

    // Placeholders first
    document.getElementById('totalItems').textContent = '0';
    document.getElementById('totalStock').textContent = formatCurrency(0);
    document.getElementById('todaySales').textContent = formatCurrency(0);
    document.getElementById('expiringItems').textContent = '0';

    try {
        // Total items in stock (distinct items with stock > 0 at this branch)
        if (CONFIG.BRANCH_ID && API.inventory && typeof API.inventory.getItemsInStockCount === 'function') {
            try {
                const countData = await API.inventory.getItemsInStockCount(CONFIG.BRANCH_ID);
                document.getElementById('totalItems').textContent = countData.count != null ? countData.count : 0;
            } catch (err) {
                console.warn('Items-in-stock count failed:', err);
            }
        }

        // Today's sales for the logged-in user (per-user)
        if (CONFIG.BRANCH_ID && API.sales && typeof API.sales.getTodaySummary === 'function') {
            try {
                const userId = CONFIG.USER_ID || null;
                const summary = await API.sales.getTodaySummary(CONFIG.BRANCH_ID, userId);
                const total = parseFloat(summary.total_inclusive || summary.total_exclusive || 0);
                document.getElementById('todaySales').textContent = formatCurrency(total);
            } catch (err) {
                console.warn('Today summary failed:', err);
            }
        }

        // Load stock value summary
        if (CONFIG.BRANCH_ID && API.inventory && typeof API.inventory.getAllStock === 'function') {
            try {
                const stock = await API.inventory.getAllStock(CONFIG.BRANCH_ID);
                // TODO: total value from stock * cost if needed
                document.getElementById('totalStock').textContent = formatCurrency(0);
            } catch (error) {
                console.warn('Failed to load stock summary:', error);
                document.getElementById('totalStock').textContent = formatCurrency(0);
            }
        } else {
            document.getElementById('totalStock').textContent = formatCurrency(0);
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

