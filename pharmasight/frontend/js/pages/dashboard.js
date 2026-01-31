// Dashboard Page

async function loadDashboard() {
    // Strict page ownership: only run dashboard logic when dashboard is the active page
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'dashboard') {
        return;
    }
    const page = document.getElementById('dashboard');
    if (!page) return;
    // Skip items/company API when no company (avoids /api/items/company/null and 422)
    if (!CONFIG.COMPANY_ID) {
        const ti = document.getElementById('totalItems');
        if (ti) ti.textContent = '0';
        const ts = document.getElementById('totalStock');
        if (ts) ts.textContent = formatCurrency(0);
        const td = document.getElementById('todaySales');
        if (td) td.textContent = '0';
        const ex = document.getElementById('expiringItems');
        if (ex) ex.textContent = '0';
        return;
    }
    
    // Load stats
    try {
        // TODO: Implement actual stats loading
        // For now, show placeholders
        document.getElementById('totalItems').textContent = '0';
        document.getElementById('totalStock').textContent = formatCurrency(0);
        document.getElementById('todaySales').textContent = formatCurrency(0);
        document.getElementById('expiringItems').textContent = '0';
        
        // Load items count (use count endpoint for better performance)
        if (CONFIG.COMPANY_ID) {
            try {
                const countData = await API.items.count(CONFIG.COMPANY_ID);
                document.getElementById('totalItems').textContent = countData.count || 0;
            } catch (error) {
                // Fallback to list if count endpoint fails
                console.warn('Count endpoint failed, using list:', error);
                const items = await API.items.list(CONFIG.COMPANY_ID, { include_units: false, limit: 1 });
                // Note: This won't give accurate count, but prevents timeout
                document.getElementById('totalItems').textContent = '...';
            }
        }
        
        // Load stock summary
        if (CONFIG.BRANCH_ID && API.inventory && typeof API.inventory.getAllStock === 'function') {
            try {
                const stock = await API.inventory.getAllStock(CONFIG.BRANCH_ID);
                // Calculate total value (simplified)
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

