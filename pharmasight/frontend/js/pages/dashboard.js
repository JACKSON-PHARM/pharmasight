// Dashboard Page

// Cached expiring list for CSV export (set when modal opens)
let cachedExpiringList = [];
// Cached order book pending list for quick preview
let cachedOrderBookPendingToday = [];

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
        const tsv = document.getElementById('totalStockValue');
        if (tsv) tsv.textContent = '—';
        const td = document.getElementById('todaySales');
        if (td) td.textContent = formatCurrency(0);
        const ex = document.getElementById('expiringItems');
        if (ex) ex.textContent = '0';
        return;
    }

    // Use session branch (same as header) so dashboard matches branch context
    const branchId = getBranchIdForStock();
    
    const cardIds = ['totalItems', 'totalStock', 'totalStockValue', 'todaySales', 'todayGrossProfit', 'expiringItems', 'orderBookPendingToday'];
    // Reset all cards visible first so a previous load cannot leave them hidden
    for (const cardId of cardIds) {
        const card = document.getElementById(cardId)?.closest('.stat-card');
        if (card) card.style.display = '';
    }
    // Check permissions and hide/show cards accordingly.
    // Fail-open: if permissions could not be loaded (empty set), show all cards so dashboard is never blank.
    // Also fail-open: if we would hide every card, show all (avoids blank dashboard after data fetch).
    if (typeof window.Permissions !== 'undefined' && window.Permissions.getUserPermissions && window.Permissions.canViewDashboardCard) {
        let permissionsLoaded = false;
        try {
            const perms = await window.Permissions.getUserPermissions(branchId);
            permissionsLoaded = perms && perms.size > 0;
        } catch (e) {
            console.warn('Dashboard: could not load permissions, showing all cards.', e);
        }
        let visibleCount = 0;
        for (const cardId of cardIds) {
            const card = document.getElementById(cardId)?.closest('.stat-card');
            if (card) {
                let canView = true;
                try {
                    canView = !permissionsLoaded || await window.Permissions.canViewDashboardCard(cardId, branchId);
                } catch (e) {
                    console.warn('Dashboard: permission check failed for card', cardId, e);
                }
                card.style.display = canView ? '' : 'none';
                if (canView) visibleCount++;
            }
        }
        // If permission check hid every card, show all so dashboard is never blank
        if (visibleCount === 0) {
            for (const cardId of cardIds) {
                const card = document.getElementById(cardId)?.closest('.stat-card');
                if (card) card.style.display = '';
            }
        }
    }

    // Placeholders first
    document.getElementById('totalItems').textContent = '0';
    document.getElementById('totalStock').textContent = '0';
    if (document.getElementById('totalStockValue')) {
        document.getElementById('totalStockValue').textContent = '—';
    }
    document.getElementById('todaySales').textContent = formatCurrency(0);
    const gpEl = document.getElementById('todayGrossProfit');
    if (gpEl) gpEl.textContent = formatCurrency(0);
    const gpMeta = document.getElementById('todayGrossProfitMeta');
    if (gpMeta) gpMeta.textContent = 'Gross Profit (Today)';
    document.getElementById('expiringItems').textContent = '0';
    const ob = document.getElementById('orderBookPendingToday');
    if (ob) ob.textContent = '0';

    try {
        // Items in database (all company items, with or without stock)
        if (CONFIG.COMPANY_ID && API.items && typeof API.items.count === 'function') {
            try {
                const itemsCountData = await API.items.count(CONFIG.COMPANY_ID);
                const totalInDb = itemsCountData.count != null ? itemsCountData.count : 0;
                const totalItemsEl = document.getElementById('totalItems');
                if (totalItemsEl) totalItemsEl.textContent = totalInDb;
            } catch (err) {
                console.warn('Items count (database) failed:', err);
            }
        }

        // Unique items in stock (distinct items with stock > 0 at this branch)
        if (branchId && API.inventory && typeof API.inventory.getItemsInStockCount === 'function') {
            try {
                const countData = await API.inventory.getItemsInStockCount(branchId);
                const uniqueInStock = countData.count != null ? countData.count : 0;
                const totalStockEl = document.getElementById('totalStock');
                if (totalStockEl) totalStockEl.textContent = uniqueInStock;
            } catch (err) {
                console.warn('Items-in-stock count failed:', err);
            }
        }

        // Today's sales - check permissions to determine if user sees own sales or all sales
        if (branchId && API.sales && typeof API.sales.getTodaySummary === 'function') {
            try {
                let userId = null;
                // Check if user can view all sales or only their own
                if (typeof window.Permissions !== 'undefined' && window.Permissions.getSalesViewPermissions) {
                    const salesPerms = await window.Permissions.getSalesViewPermissions(branchId);
                    // If user can only view own sales, filter by user_id
                    if (!salesPerms.canViewAll && salesPerms.canViewOwn) {
                        userId = CONFIG.USER_ID || null;
                    }
                    // If user can't view any sales, don't show the card (already hidden above)
                } else {
                    // Fallback: show own sales only
                    userId = CONFIG.USER_ID || null;
                }
                const summary = await API.sales.getTodaySummary(branchId, userId);
                const total = parseFloat(summary.total_inclusive || summary.total_exclusive || 0);
                document.getElementById('todaySales').textContent = formatCurrency(total);
            } catch (err) {
                console.warn('Today summary failed:', err);
            }
        }

        // Today's gross profit (Sales exclusive - COGS), requires cost permissions.
        if (branchId && API.sales && typeof API.sales.getGrossProfit === 'function') {
            try {
                // If the card is hidden by permissions, skip work.
                const gpCard = document.getElementById('todayGrossProfit')?.closest('.stat-card');
                if (gpCard && gpCard.style.display === 'none') {
                    // noop
                } else {
                    const res = await API.sales.getGrossProfit(branchId, { preset: 'today' });
                    const gp = parseFloat(res.gross_profit || 0);
                    const margin = parseFloat(res.margin_percent || 0);
                    const gpEl2 = document.getElementById('todayGrossProfit');
                    if (gpEl2) gpEl2.textContent = formatCurrency(gp);
                    const meta = document.getElementById('todayGrossProfitMeta');
                    if (meta) meta.textContent = `Gross Profit (Today) • Margin ${margin.toFixed(1)}%`;
                }
            } catch (err) {
                console.warn('Today gross profit failed:', err);
                const gpEl2 = document.getElementById('todayGrossProfit');
                if (gpEl2) gpEl2.textContent = formatCurrency(0);
                const meta = document.getElementById('todayGrossProfitMeta');
                if (meta) meta.textContent = 'Gross Profit (Today)';
            }
        }

        // Soon to expire count (batches expiring within 365 days)
        if (branchId && API.inventory && typeof API.inventory.getExpiringCount === 'function') {
            try {
                const expiringData = await API.inventory.getExpiringCount(branchId, 365);
                const expiringCount = expiringData.count != null ? expiringData.count : 0;
                document.getElementById('expiringItems').textContent = expiringCount;
            } catch (err) {
                console.warn('Expiring count endpoint not available:', err);
                document.getElementById('expiringItems').textContent = '0';
            }
        }

        // totalStock card is set above from getItemsInStockCount (unique items); no separate API needed

        // Stock value in KES (monetary)
        if (branchId && API.inventory && typeof API.inventory.getTotalStockValue === 'function') {
            try {
                const valueData = await API.inventory.getTotalStockValue(branchId);
                const totalValue = valueData.total_value != null ? valueData.total_value : 0;
                const totalStockValueEl = document.getElementById('totalStockValue');
                if (totalStockValueEl) totalStockValueEl.textContent = formatCurrency(totalValue);
            } catch (err) {
                console.warn('Total stock value endpoint not available:', err);
                const totalStockValueEl = document.getElementById('totalStockValue');
                if (totalStockValueEl) totalStockValueEl.textContent = '—';
            }
        }

        // Order book pending today (count + cache preview list)
        if (branchId && API.orderBook && typeof API.orderBook.getTodaySummary === 'function') {
            try {
                const summary = await API.orderBook.getTodaySummary(branchId, CONFIG.COMPANY_ID, 50);
                const pendingCount = summary && summary.pending_count != null ? summary.pending_count : 0;
                const el = document.getElementById('orderBookPendingToday');
                if (el) el.textContent = pendingCount;
                cachedOrderBookPendingToday = (summary && summary.entries) ? summary.entries : [];
            } catch (err) {
                console.warn('Order book today summary failed:', err);
                const el = document.getElementById('orderBookPendingToday');
                if (el) el.textContent = '0';
                cachedOrderBookPendingToday = [];
            }
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

async function showOrderBookPendingTodayModal() {
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }
    if (!API.orderBook || typeof API.orderBook.getTodaySummary !== 'function') {
        if (typeof showToast === 'function') showToast('Order book summary not available.', 'warning');
        return;
    }

    const content = '<div class="spinner" style="margin: 2rem auto;"></div><p style="text-align: center;">Loading order book...</p>';
    const footer = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
    if (typeof showModal === 'function') showModal('Order Book Pending (Today)', content, footer, 'modal-large');

    try {
        const summary = await API.orderBook.getTodaySummary(branchId, CONFIG.COMPANY_ID, 200);
        const list = (summary && summary.entries) ? summary.entries : [];
        cachedOrderBookPendingToday = list;

        if (!list || list.length === 0) {
            const emptyContent = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No pending order book items for today.</p>';
            const emptyFooter = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
            if (typeof showModal === 'function') showModal('Order Book Pending (Today)', emptyContent, emptyFooter, 'modal-large');
            return;
        }

        const rows = list.map(function (r) {
            const name = (typeof escapeHtml === 'function' ? escapeHtml(r.item_name || '') : (r.item_name || '')).replace(/"/g, '&quot;');
            const sku = (typeof escapeHtml === 'function' ? escapeHtml(r.item_sku || '') : (r.item_sku || '')).replace(/"/g, '&quot;');
            const supplier = (typeof escapeHtml === 'function' ? escapeHtml(r.supplier_name || '') : (r.supplier_name || '')).replace(/"/g, '&quot;');
            const qty = (typeof formatNumber === 'function' ? formatNumber(r.quantity_needed) : (r.quantity_needed != null ? r.quantity_needed : 0));
            const unit = (typeof escapeHtml === 'function' ? escapeHtml(r.unit_name || '') : (r.unit_name || '')).replace(/"/g, '&quot;');
            return '<tr><td>' + name + '</td><td><code>' + (sku || '—') + '</code></td><td>' + (supplier || '—') + '</td><td style="text-align: right;">' + qty + ' ' + (unit || '') + '</td></tr>';
        }).join('');

        const tableContent = `
            <div style="max-height: 60vh; overflow-y: auto; margin-bottom: 1rem;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background: white;">
                        <tr>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">SKU</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">Supplier</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: right;">Qty Needed</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <p style="color: var(--text-secondary); font-size: 0.875rem;">${list.length} pending item(s) shown (today)</p>
        `;

        const modalFooter = `
            <button class="btn btn-primary" onclick="if(window.openOrderBookFromDashboard) window.openOrderBookFromDashboard()">
                <i class="fas fa-clipboard-list"></i> Open Order Book
            </button>
            <button class="btn btn-outline" onclick="closeModal()">Close</button>
        `;
        if (typeof showModal === 'function') showModal('Order Book Pending (Today)', tableContent, modalFooter, 'modal-large');
    } catch (err) {
        console.error('Failed to load order book today summary:', err);
        const errContent = '<p style="padding: 2rem; text-align: center; color: var(--danger-color);">Failed to load order book. ' + (err.message || '') + '</p>';
        const errFooter = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
        if (typeof showModal === 'function') showModal('Order Book Pending (Today)', errContent, errFooter, 'modal-large');
    }
}

function openOrderBookFromDashboard() {
    if (typeof closeModal === 'function') closeModal();
    if (typeof window.loadPage === 'function') window.loadPage('purchases');
    if (typeof window.loadPurchaseSubPage === 'function') {
        setTimeout(function () {
            window.loadPurchaseSubPage('order-book');
        }, 200);
    }
}

/**
 * Show drill-down modal for Expiring Soon card.
 * Fetches expiring batches and displays table with Export CSV button.
 */
async function showExpiringSoonModal() {
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }
    if (!API.inventory || typeof API.inventory.getExpiringList !== 'function') {
        if (typeof showToast === 'function') showToast('Expiring list not available.', 'warning');
        return;
    }

    const content = '<div class="spinner" style="margin: 2rem auto;"></div><p style="text-align: center;">Loading expiring items...</p>';
    const footer = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
    if (typeof showModal === 'function') showModal('Expiring Soon (within 365 days)', content, footer, 'modal-large');

    try {
        const list = await API.inventory.getExpiringList(branchId, 365);
        cachedExpiringList = list || [];

        if (!list || list.length === 0) {
            const emptyContent = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items expiring within the next 365 days.</p>';
            const emptyFooter = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
            if (typeof showModal === 'function') showModal('Expiring Soon (within 365 days)', emptyContent, emptyFooter, 'modal-large');
            return;
        }

        const rows = list.map(function (r) {
            const name = (typeof escapeHtml === 'function' ? escapeHtml(r.item_name || '') : (r.item_name || '')).replace(/"/g, '&quot;');
            const batch = (typeof escapeHtml === 'function' ? escapeHtml(r.batch_number || '') : (r.batch_number || '')).replace(/"/g, '&quot;');
            const expiry = r.expiry_date ? (typeof formatDate === 'function' ? formatDate(r.expiry_date) : r.expiry_date) : '—';
            const qtyDisplay = r.quantity_display != null ? (typeof escapeHtml === 'function' ? escapeHtml(r.quantity_display) : r.quantity_display) : ((typeof formatNumber === 'function' ? formatNumber(r.quantity) : r.quantity) + ' ' + (r.base_unit || ''));
            return '<tr><td>' + name + '</td><td><code>' + batch + '</code></td><td>' + expiry + '</td><td style="text-align: right;">' + qtyDisplay + '</td></tr>';
        }).join('');

        const tableContent = `
            <div style="max-height: 60vh; overflow-y: auto; margin-bottom: 1rem;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background: white;">
                        <tr>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">Batch</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">Expiry Date</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: right;">Quantity</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <p style="color: var(--text-secondary); font-size: 0.875rem;">${list.length} batch(es) expiring within 365 days</p>
        `;
        const modalFooter = '<button class="btn btn-outline" onclick="exportExpiringToCsv()"><i class="fas fa-file-csv"></i> Export CSV</button><button class="btn btn-outline" onclick="closeModal()">Close</button>';
        if (typeof showModal === 'function') showModal('Expiring Soon (within 365 days)', tableContent, modalFooter, 'modal-large');
    } catch (err) {
        console.error('Failed to load expiring list:', err);
        const errContent = '<p style="padding: 2rem; text-align: center; color: var(--danger-color);">Failed to load expiring items. ' + (err.message || '') + '</p>';
        const errFooter = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
        if (typeof showModal === 'function') showModal('Expiring Soon', errContent, errFooter, 'modal-large');
    }
}

/**
 * Export cached expiring list to CSV file.
 */
function exportExpiringToCsv() {
    if (!cachedExpiringList || cachedExpiringList.length === 0) {
        if (typeof showToast === 'function') showToast('No data to export.', 'warning');
        return;
    }
    const escapeCsv = function (v) {
        if (v == null) return '';
        var s = String(v);
        if (s.indexOf(',') >= 0 || s.indexOf('"') >= 0 || s.indexOf('\n') >= 0) {
            return '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
    };
    const headers = ['Item Name', 'Batch', 'Expiry Date', 'Quantity'];
    const rows = cachedExpiringList.map(function (r) {
        const qty = r.quantity_display != null ? r.quantity_display : (r.quantity + ' ' + (r.base_unit || ''));
        return [r.item_name || '', r.batch_number || '', r.expiry_date || '', qty].map(escapeCsv).join(',');
    });
    const csv = [headers.map(escapeCsv).join(','), rows.join('\n')].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'expiring-soon-' + new Date().toISOString().slice(0, 10) + '.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    if (typeof showToast === 'function') showToast('CSV exported.', 'success');
}

function openFinancialReportsFromDashboard() {
    // Navigate to financial reports (default: today)
    if (typeof window.loadPage === 'function') {
        window.loadPage('reports-financial');
    } else {
        window.location.hash = '#reports-financial';
    }
}

// Export
window.loadDashboard = loadDashboard;
window.showOrderBookPendingTodayModal = showOrderBookPendingTodayModal;
window.openOrderBookFromDashboard = openOrderBookFromDashboard;
window.showExpiringSoonModal = showExpiringSoonModal;
window.exportExpiringToCsv = exportExpiringToCsv;
window.openFinancialReportsFromDashboard = openFinancialReportsFromDashboard;

