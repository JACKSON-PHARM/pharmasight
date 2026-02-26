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

    // Skeleton loading state (removed when data loads below)
    var dashboardStatCards = document.querySelectorAll('#dashboard .stat-card');
    dashboardStatCards.forEach(function (card) { card.classList.add('stat-card-loading'); });

    try {
        var promises = [];
        if (CONFIG.COMPANY_ID && API.items && typeof API.items.count === 'function') {
            promises.push(API.items.count(CONFIG.COMPANY_ID).then(function (d) {
                var el = document.getElementById('totalItems');
                if (el) el.textContent = (d.count != null ? d.count : 0);
            }).catch(function (err) { console.warn('Items count (database) failed:', err); }));
        }
        if (branchId && API.inventory && typeof API.inventory.getItemsInStockCount === 'function') {
            promises.push(API.inventory.getItemsInStockCount(branchId).then(function (d) {
                var el = document.getElementById('totalStock');
                if (el) el.textContent = (d.count != null ? d.count : 0);
            }).catch(function (err) { console.warn('Items-in-stock count failed:', err); }));
        }
        if (branchId && API.sales && typeof API.sales.getTodaySummary === 'function') {
            promises.push((window.Permissions && window.Permissions.getSalesViewPermissions
                ? window.Permissions.getSalesViewPermissions(branchId).then(function (p) {
                    return (!p.canViewAll && p.canViewOwn) ? (CONFIG.USER_ID || null) : null;
                })
                : Promise.resolve(CONFIG.USER_ID || null)
            ).then(function (userId) {
                return API.sales.getTodaySummary(branchId, userId);
            }).then(function (s) {
                var total = parseFloat(s.total_inclusive || s.total_exclusive || 0);
                document.getElementById('todaySales').textContent = formatCurrency(total);
            }).catch(function (err) { console.warn('Today summary failed:', err); }));
        }
        if (branchId && API.sales && typeof API.sales.getGrossProfit === 'function') {
            promises.push((function () {
                var gpCard = document.getElementById('todayGrossProfit') && document.getElementById('todayGrossProfit').closest('.stat-card');
                if (gpCard && gpCard.style.display === 'none') return Promise.resolve();
                return API.sales.getGrossProfit(branchId, { preset: 'today' }).then(function (r) {
                    var gp = parseFloat(r.gross_profit || 0);
                    var margin = parseFloat(r.margin_percent || 0);
                    var el = document.getElementById('todayGrossProfit');
                    if (el) el.textContent = formatCurrency(gp);
                    var meta = document.getElementById('todayGrossProfitMeta');
                    if (meta) meta.textContent = 'Gross Profit (Today) • Margin ' + margin.toFixed(1) + '%';
                }).catch(function (err) {
                    console.warn('Today gross profit failed:', err);
                    var el = document.getElementById('todayGrossProfit');
                    if (el) el.textContent = formatCurrency(0);
                    var meta = document.getElementById('todayGrossProfitMeta');
                    if (meta) meta.textContent = 'Gross Profit (Today)';
                });
            })());
        }
        if (branchId && API.inventory && typeof API.inventory.getExpiringCount === 'function') {
            promises.push(API.inventory.getExpiringCount(branchId, 365).then(function (d) {
                document.getElementById('expiringItems').textContent = (d.count != null ? d.count : 0);
            }).catch(function (err) {
                console.warn('Expiring count endpoint not available:', err);
                document.getElementById('expiringItems').textContent = '0';
            }));
        }
        if (branchId && API.inventory && typeof API.inventory.getTotalStockValue === 'function') {
            promises.push(API.inventory.getTotalStockValue(branchId).then(function (d) {
                var el = document.getElementById('totalStockValue');
                if (el) el.textContent = (d.total_value != null ? formatCurrency(d.total_value) : '—');
            }).catch(function (err) {
                console.warn('Total stock value endpoint not available:', err);
                var el = document.getElementById('totalStockValue');
                if (el) el.textContent = '—';
            }));
        }
        if (branchId && API.orderBook && typeof API.orderBook.getTodaySummary === 'function') {
            promises.push(API.orderBook.getTodaySummary(branchId, CONFIG.COMPANY_ID, 50).then(function (s) {
                var el = document.getElementById('orderBookPendingToday');
                if (el) el.textContent = (s && s.pending_count != null ? s.pending_count : 0);
                cachedOrderBookPendingToday = (s && s.entries) ? s.entries : [];
            }).catch(function (err) {
                console.warn('Order book today summary failed:', err);
                var el = document.getElementById('orderBookPendingToday');
                if (el) el.textContent = '0';
                cachedOrderBookPendingToday = [];
            }));
        }
        await Promise.all(promises);
    } catch (error) {
        console.error('Error loading dashboard:', error);
        var active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
        if (active === 'dashboard' && typeof showToast === 'function') {
            showToast('Error loading dashboard data', 'error');
        }
    }
    dashboardStatCards = document.querySelectorAll('#dashboard .stat-card');
    dashboardStatCards.forEach(function (card) { card.classList.remove('stat-card-loading'); });
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

