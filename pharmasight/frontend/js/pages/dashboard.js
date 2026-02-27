// Dashboard Page - Heavy metrics load on demand (Apply only). Cached by date range + branch.

// Cached expiring list for CSV export (set when modal opens)
let cachedExpiringList = [];
// Cached order book pending list for quick preview
let cachedOrderBookPendingToday = [];

// Cache for dashboard metrics: key = branchId + preset + start + end (for range data), branchId only for KPIs
const DASHBOARD_CACHE_TTL_MS = 2 * 60 * 1000; // 2 minutes
let dashboardCache = {
    range: null,   // { key, data, ts } for gross profit / sales / orders
    kpis: null     // { branchId, data, ts } for items, stock, value, expiring, orderBook
};

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

function getDashboardParams() {
    const preset = (document.getElementById('dashboardPreset') && document.getElementById('dashboardPreset').value) || 'today';
    let startDate = null;
    let endDate = null;
    if (preset === 'custom') {
        const startEl = document.getElementById('dashboardStartDate');
        const endEl = document.getElementById('dashboardEndDate');
        if (startEl && startEl.value) startDate = startEl.value;
        if (endEl && endEl.value) endDate = endEl.value;
    }
    return { preset: preset, startDate: startDate, endDate: endDate };
}

function cacheKeyForRange(branchId, params) {
    return branchId + '|' + (params.preset || '') + '|' + (params.startDate || '') + '|' + (params.endDate || '');
}

async function loadDashboard() {
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'dashboard') return;
    const page = document.getElementById('dashboard');
    if (!page) return;

    const branchId = getBranchIdForStock();
    const cardIds = ['totalItems', 'totalStock', 'totalStockValue', 'todaySales', 'ordersProcessed', 'todayGrossProfit', 'expiringItems', 'orderBookPendingToday'];

    // Reset cards to placeholder (no auto-fetch)
    cardIds.forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.textContent = '—';
    });
    const salesLabel = document.getElementById('dashboardSalesLabel');
    if (salesLabel) salesLabel.textContent = 'Sales (select range & Apply)';
    const gpMeta = document.getElementById('todayGrossProfitMeta');
    if (gpMeta) gpMeta.textContent = 'Gross Profit';

    // Show/hide cards by permission (same as before)
    for (let i = 0; i < cardIds.length; i++) {
        const card = document.getElementById(cardIds[i])?.closest('.stat-card');
        if (card) card.style.display = '';
    }
    if (typeof window.Permissions !== 'undefined' && window.Permissions.getUserPermissions && window.Permissions.canViewDashboardCard) {
        let permissionsLoaded = false;
        try {
            const perms = await window.Permissions.getUserPermissions(branchId);
            permissionsLoaded = perms && perms.size > 0;
        } catch (e) {
            console.warn('Dashboard: could not load permissions, showing all cards.', e);
        }
        let visibleCount = 0;
        for (let i = 0; i < cardIds.length; i++) {
            const card = document.getElementById(cardIds[i])?.closest('.stat-card');
            if (card) {
                let canView = true;
                try {
                    canView = !permissionsLoaded || await window.Permissions.canViewDashboardCard(cardIds[i], branchId);
                } catch (e) {
                    console.warn('Dashboard: permission check failed for card', cardIds[i], e);
                }
                card.style.display = canView ? '' : 'none';
                if (canView) visibleCount++;
            }
        }
        if (visibleCount === 0) {
            cardIds.forEach(function (id) {
                const card = document.getElementById(id)?.closest('.stat-card');
                if (card) card.style.display = '';
            });
        }
    }

    // Toolbar: preset change toggles custom range visibility
    const presetSelect = document.getElementById('dashboardPreset');
    const customRange = document.getElementById('dashboardCustomRange');
    if (presetSelect && customRange) {
        function toggleCustom() {
            customRange.style.display = (presetSelect.value === 'custom') ? 'flex' : 'none';
        }
        presetSelect.onchange = toggleCustom;
        toggleCustom();
    }

    // Set default custom dates to today if empty
    const startInput = document.getElementById('dashboardStartDate');
    const endInput = document.getElementById('dashboardEndDate');
    if (startInput && endInput) {
        const today = new Date().toISOString().slice(0, 10);
        if (!startInput.value) startInput.value = today;
        if (!endInput.value) endInput.value = today;
    }

    // Apply button: fetch metrics only on click
    const applyBtn = document.getElementById('dashboardApplyBtn');
    if (applyBtn) {
        applyBtn.onclick = function () { applyDashboardFilters(); };
    }
}

async function applyDashboardFilters() {
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'dashboard') return;
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }
    if (!CONFIG || !CONFIG.COMPANY_ID) {
        if (typeof showToast === 'function') showToast('Company not set.', 'warning');
        return;
    }

    const params = getDashboardParams();
    const rangeKey = cacheKeyForRange(branchId, params);
    const grid = document.getElementById('dashboardStatsGrid');

    // Show loading state
    if (grid) grid.querySelectorAll('.stat-card').forEach(function (card) { card.classList.add('stat-card-loading'); });

    const salesLabel = document.getElementById('dashboardSalesLabel');
    if (salesLabel) salesLabel.textContent = 'Sales';

    try {
        const now = Date.now();
        let rangeData = null;
        let kpisData = null;

        if (dashboardCache.range && dashboardCache.range.key === rangeKey && (now - dashboardCache.range.ts) < DASHBOARD_CACHE_TTL_MS) {
            rangeData = dashboardCache.range.data;
        }
        if (dashboardCache.kpis && dashboardCache.kpis.branchId === branchId && (now - dashboardCache.kpis.ts) < DASHBOARD_CACHE_TTL_MS) {
            kpisData = dashboardCache.kpis.data;
        }

        const gpParams = {};
        if (params.preset && params.preset !== 'custom') {
            gpParams.preset = params.preset;
        } else if (params.startDate && params.endDate) {
            gpParams.start_date = params.startDate;
            gpParams.end_date = params.endDate;
        } else {
            gpParams.preset = 'today';
        }

        if (!rangeData) {
            const userId = (window.Permissions && window.Permissions.getSalesViewPermissions)
                ? await window.Permissions.getSalesViewPermissions(branchId).then(function (p) {
                    return (!p.canViewAll && p.canViewOwn) ? (CONFIG.USER_ID || null) : null;
                })
                : (CONFIG.USER_ID || null);
            const gpRes = await API.sales.getGrossProfit(branchId, gpParams);
            rangeData = {
                sales_exclusive: parseFloat(gpRes.sales_exclusive || 0),
                gross_profit: parseFloat(gpRes.gross_profit || 0),
                margin_percent: parseFloat(gpRes.margin_percent || 0),
                invoice_count: parseInt(gpRes.invoice_count || 0, 10),
                start_date: gpRes.start_date,
                end_date: gpRes.end_date
            };
            dashboardCache.range = { key: rangeKey, data: rangeData, ts: now };
        }

        if (!kpisData) {
            const promises = [];
            const kpis = {};
            if (API.items && typeof API.items.count === 'function') {
                promises.push(API.items.count(CONFIG.COMPANY_ID).then(function (d) { kpis.itemsCount = (d.count != null ? d.count : 0); }).catch(function () { kpis.itemsCount = 0; }));
            }
            if (API.inventory && typeof API.inventory.getItemsInStockCount === 'function') {
                promises.push(API.inventory.getItemsInStockCount(branchId).then(function (d) { kpis.stockCount = (d.count != null ? d.count : 0); }).catch(function () { kpis.stockCount = 0; }));
            }
            if (API.inventory && typeof API.inventory.getTotalStockValue === 'function') {
                promises.push(API.inventory.getTotalStockValue(branchId).then(function (d) { kpis.stockValue = d.total_value; }).catch(function () { kpis.stockValue = null; }));
            }
            if (API.inventory && typeof API.inventory.getExpiringCount === 'function') {
                promises.push(API.inventory.getExpiringCount(branchId, 365).then(function (d) { kpis.expiringCount = (d.count != null ? d.count : 0); }).catch(function () { kpis.expiringCount = 0; }));
            }
            if (API.orderBook && typeof API.orderBook.getTodaySummary === 'function') {
                promises.push(API.orderBook.getTodaySummary(branchId, CONFIG.COMPANY_ID, 50).then(function (s) {
                    kpis.orderBookPending = (s && s.pending_count != null ? s.pending_count : 0);
                    cachedOrderBookPendingToday = (s && s.entries) ? s.entries : [];
                }).catch(function () { kpis.orderBookPending = 0; cachedOrderBookPendingToday = []; }));
            }
            await Promise.all(promises);
            kpisData = kpis;
            dashboardCache.kpis = { branchId: branchId, data: kpisData, ts: now };
        }

        // Fill range-based cards
        const totalItemsEl = document.getElementById('totalItems');
        const totalStockEl = document.getElementById('totalStock');
        const totalStockValueEl = document.getElementById('totalStockValue');
        const todaySalesEl = document.getElementById('todaySales');
        const ordersProcessedEl = document.getElementById('ordersProcessed');
        const todayGrossProfitEl = document.getElementById('todayGrossProfit');
        const todayGrossProfitMetaEl = document.getElementById('todayGrossProfitMeta');
        const expiringItemsEl = document.getElementById('expiringItems');
        const orderBookPendingEl = document.getElementById('orderBookPendingToday');

        if (totalItemsEl) totalItemsEl.textContent = (kpisData.itemsCount != null ? kpisData.itemsCount : '—');
        if (totalStockEl) totalStockEl.textContent = (kpisData.stockCount != null ? kpisData.stockCount : '—');
        if (totalStockValueEl) totalStockValueEl.textContent = (kpisData.stockValue != null ? (typeof formatCurrency === 'function' ? formatCurrency(kpisData.stockValue) : kpisData.stockValue) : '—');
        if (todaySalesEl) todaySalesEl.textContent = typeof formatCurrency === 'function' ? formatCurrency(rangeData.sales_exclusive) : rangeData.sales_exclusive;
        if (ordersProcessedEl) ordersProcessedEl.textContent = rangeData.invoice_count != null ? rangeData.invoice_count : '—';
        if (todayGrossProfitEl) todayGrossProfitEl.textContent = typeof formatCurrency === 'function' ? formatCurrency(rangeData.gross_profit) : rangeData.gross_profit;
        if (todayGrossProfitMetaEl) todayGrossProfitMetaEl.textContent = 'Gross Profit • Margin ' + (rangeData.margin_percent != null ? rangeData.margin_percent.toFixed(1) : '0') + '%';
        if (expiringItemsEl) expiringItemsEl.textContent = (kpisData.expiringCount != null ? kpisData.expiringCount : '—');
        if (orderBookPendingEl) orderBookPendingEl.textContent = (kpisData.orderBookPending != null ? kpisData.orderBookPending : '—');

    } catch (error) {
        console.error('Error loading dashboard:', error);
        if (typeof showToast === 'function') showToast('Error loading dashboard data', 'error');
    } finally {
        if (grid) grid.querySelectorAll('.stat-card').forEach(function (card) { card.classList.remove('stat-card-loading'); });
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
    if (typeof window.loadPage === 'function') {
        window.loadPage('reports-financial');
    } else {
        window.location.hash = '#reports-financial';
    }
}

// Export
window.loadDashboard = loadDashboard;
window.applyDashboardFilters = applyDashboardFilters;
window.showOrderBookPendingTodayModal = showOrderBookPendingTodayModal;
window.openOrderBookFromDashboard = openOrderBookFromDashboard;
window.showExpiringSoonModal = showExpiringSoonModal;
window.exportExpiringToCsv = exportExpiringToCsv;
window.openFinancialReportsFromDashboard = openFinancialReportsFromDashboard;
