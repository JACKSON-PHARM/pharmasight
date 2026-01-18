// Dashboard Page

async function loadDashboard() {
    const page = document.getElementById('dashboard');
    
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
        if (CONFIG.BRANCH_ID) {
            const stock = await API.inventory.getAllStock(CONFIG.BRANCH_ID);
            // Calculate total value (simplified)
            document.getElementById('totalStock').textContent = formatCurrency(0);
        }
        
    } catch (error) {
        console.error('Error loading dashboard:', error);
        showToast('Error loading dashboard data', 'error');
    }
}

// Export
window.loadDashboard = loadDashboard;

