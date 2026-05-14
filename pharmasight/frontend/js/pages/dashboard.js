// Dashboard Page - Heavy metrics load on demand (Apply only). Cached by date range + branch.

// Cached expiring list for CSV export (set when modal opens)
let cachedExpiringList = [];
// Cached order book pending list for quick preview
let cachedOrderBookPendingToday = [];
// Expiring-soon days window (company setting)
let cachedExpiringSoonDays = 365;

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

    var trialExpired =
        (window.SubscriptionUI && window.SubscriptionUI.effectiveAccess && window.SubscriptionUI.effectiveAccess() === 'trial_expired') ||
        (window.__authMe && window.__authMe.subscription_access === 'trial_expired');
    if (trialExpired) {
        const toolbar = page.querySelector('.dashboard-toolbar');
        const hint = page.querySelector('.dashboard-hint');
        const grid = document.getElementById('dashboardStatsGrid');
        if (toolbar) toolbar.style.display = 'none';
        if (hint) hint.style.display = 'none';
        if (grid) grid.style.display = 'none';
        let panel = document.getElementById('trialExpiredPanel');
        if (!panel) {
            panel = document.createElement('div');
            panel.id = 'trialExpiredPanel';
            const anchor = page.querySelector('.dashboard-toolbar');
            if (anchor && anchor.parentNode) {
                anchor.parentNode.insertBefore(panel, anchor);
            } else {
                page.appendChild(panel);
            }
        }
        panel.className = 'card trial-expired-card';
        panel.style.display = 'block';
        panel.innerHTML =
            '<div style="padding: 2rem; text-align: center; max-width: 36rem; margin: 0 auto;">' +
            '<h2 style="margin: 0 0 0.5rem;">Trial ended</h2>' +
            '<p style="color: var(--text-secondary); margin-bottom: 1rem;">Your SightOps trial has ended. Upgrade to continue using sales, inventory, purchases, and reports.</p>' +
            '<p style="color: var(--text-secondary); font-size: 0.875rem;">Contact support to upgrade your subscription.</p>' +
            '</div>';
        return;
    }

    const expiredPanel = document.getElementById('trialExpiredPanel');
    if (expiredPanel) expiredPanel.style.display = 'none';
    const toolbarRestore = page.querySelector('.dashboard-toolbar');
    const hintRestore = page.querySelector('.dashboard-hint');
    const gridRestore = document.getElementById('dashboardStatsGrid');
    if (toolbarRestore) toolbarRestore.style.display = '';
    if (hintRestore) hintRestore.style.display = '';
    if (gridRestore) gridRestore.style.display = '';

    const branchId = getBranchIdForStock();
    const cardIds = ['totalItems', 'totalStock', 'totalStockValue', 'todaySales', 'ordersProcessed', 'creditReturnsCount', 'todayGrossProfit', 'expiringItems', 'orderBookPendingToday', 'belowMarginCount'];

    // Reset cards to placeholder (no auto-fetch)
    cardIds.forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.textContent = '—';
    });
    const salesLabel = document.getElementById('dashboardSalesLabel');
    if (salesLabel) salesLabel.textContent = 'Net sales incl. VAT (select range & Apply)';
    const salesSub = document.getElementById('dashboardSalesSubline');
    if (salesSub) salesSub.textContent = '';
    const ordersSubReset = document.getElementById('ordersProcessedSub');
    if (ordersSubReset) ordersSubReset.textContent = '';
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

    // Load "Items in database" as soon as dashboard is shown (no Apply needed) so it updates after import
    if (typeof CONFIG !== 'undefined' && CONFIG.COMPANY_ID && typeof API !== 'undefined' && API.items && typeof API.items.count === 'function') {
        API.items.count(CONFIG.COMPANY_ID).then(function (d) {
            const el = document.getElementById('totalItems');
            if (el) el.textContent = (d && d.count != null) ? d.count : 0;
        }).catch(function () {});
    }
}

async function applyDashboardFilters() {
    const active = (typeof currentPage !== 'undefined' ? currentPage : (window.currentPage || ''));
    if (active !== 'dashboard') return;
    if (
        (window.SubscriptionUI && window.SubscriptionUI.effectiveAccess && window.SubscriptionUI.effectiveAccess() === 'trial_expired') ||
        (window.__authMe && window.__authMe.subscription_access === 'trial_expired')
    ) {
        return;
    }
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
    if (salesLabel) salesLabel.textContent = 'Net sales incl. VAT';

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
            const [gpRes, bmRes] = await Promise.all([
                API.sales.getGrossProfit(branchId, gpParams),
                (API.sales && typeof API.sales.getBelowMarginSummary === 'function')
                    ? API.sales.getBelowMarginSummary(branchId, gpParams).catch(() => null)
                    : Promise.resolve(null),
            ]);
            rangeData = {
                sales_exclusive: parseFloat(gpRes.sales_exclusive || 0), // gross sales (before credit notes)
                sales_inclusive: parseFloat(gpRes.sales_inclusive || 0), // gross sales inclusive of VAT (before credit notes)
                net_sales_exclusive: parseFloat(gpRes.net_sales_exclusive || 0), // sales after credit notes
                net_sales_inclusive: parseFloat(gpRes.net_sales_inclusive || 0),
                credit_notes_inclusive: parseFloat(gpRes.credit_notes_inclusive || 0),
                credit_note_document_count: parseInt(gpRes.credit_note_document_count || 0, 10),
                gross_profit: parseFloat(gpRes.gross_profit || 0),
                margin_percent: parseFloat(gpRes.margin_percent || 0),
                invoice_count: parseInt(gpRes.invoice_count || 0, 10),
                start_date: gpRes.start_date,
                end_date: gpRes.end_date,
                below_margin_lines: bmRes ? parseInt(bmRes.line_count || 0, 10) : 0,
                sustainable_min_margin_pct: bmRes ? (bmRes.sustainable_min_margin_pct || '') : ''
            };
            dashboardCache.range = { key: rangeKey, data: rangeData, ts: now };
        }

        if (!kpisData) {
            const promises = [];
            const kpis = {};
            // Load company expiring window once per Apply (fallback 365).
            // NOTE: Expiring KPI requests must wait for this value to avoid
            // race-condition fallback to 365 while drill-down later uses setting.
            const expiringDaysPromise =
                (API.company && typeof API.company.getSettings === 'function' && CONFIG && CONFIG.COMPANY_ID)
                    ? API.company.getSettings(CONFIG.COMPANY_ID, 'expiring_soon_days')
                        .then(function (d) {
                            const raw = d ? d.value : null;
                            const n = parseInt(raw, 10);
                            cachedExpiringSoonDays = (isFinite(n) && n >= 1 && n <= 3650) ? n : 365;
                            return cachedExpiringSoonDays;
                        })
                        .catch(function () {
                            cachedExpiringSoonDays = 365;
                            return cachedExpiringSoonDays;
                        })
                    : Promise.resolve().then(function () {
                        cachedExpiringSoonDays = 365;
                        return cachedExpiringSoonDays;
                    });
            promises.push(expiringDaysPromise);
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
                promises.push(expiringDaysPromise.then(function (days) {
                    return API.inventory.getExpiringCount(branchId, days)
                        .then(function (d) {
                            kpis.expiringCount = (d.count != null ? d.count : 0);
                            kpis.expiringValue = (d.total_value != null ? Number(d.total_value) : 0);
                        })
                        .catch(function () { kpis.expiringCount = 0; kpis.expiringValue = 0; });
                }));
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
        const ordersProcessedSubEl = document.getElementById('ordersProcessedSub');
        const creditReturnsCountEl = document.getElementById('creditReturnsCount');
        const todayGrossProfitEl = document.getElementById('todayGrossProfit');
        const todayGrossProfitMetaEl = document.getElementById('todayGrossProfitMeta');
        const expiringItemsEl = document.getElementById('expiringItems');
        const expiringItemsMetaEl = document.getElementById('expiringItemsMeta');
        const orderBookPendingEl = document.getElementById('orderBookPendingToday');
        const belowMarginEl = document.getElementById('belowMarginCount');

        if (totalItemsEl) totalItemsEl.textContent = (kpisData.itemsCount != null ? kpisData.itemsCount : '—');
        if (totalStockEl) totalStockEl.textContent = (kpisData.stockCount != null ? kpisData.stockCount : '—');
        if (totalStockValueEl) totalStockValueEl.textContent = (kpisData.stockValue != null ? (typeof formatCurrency === 'function' ? formatCurrency(kpisData.stockValue) : kpisData.stockValue) : '—');
        const netSalesInc = (rangeData.net_sales_inclusive != null && !isNaN(rangeData.net_sales_inclusive))
            ? rangeData.net_sales_inclusive
            : (parseFloat(rangeData.sales_inclusive || 0));
        const grossInc = parseFloat(rangeData.sales_inclusive || 0);
        const cnInc = parseFloat(rangeData.credit_notes_inclusive || 0);
        if (todaySalesEl) todaySalesEl.textContent = typeof formatCurrency === 'function' ? formatCurrency(netSalesInc) : netSalesInc;
        const salesSubEl = document.getElementById('dashboardSalesSubline');
        if (salesSubEl) {
            if (cnInc > 0 && typeof formatCurrency === 'function') {
                salesSubEl.textContent = 'Gross ' + formatCurrency(grossInc) + ' − credits ' + formatCurrency(cnInc);
            } else {
                salesSubEl.textContent = '';
            }
        }
        if (ordersProcessedEl) ordersProcessedEl.textContent = rangeData.invoice_count != null ? rangeData.invoice_count : '—';
        if (ordersProcessedSubEl) {
            const ncn = rangeData.credit_note_document_count != null ? rangeData.credit_note_document_count : 0;
            ordersProcessedSubEl.textContent = ncn > 0 ? (ncn + ' credit note' + (ncn === 1 ? '' : 's') + ' in range (sale date)') : '';
        }
        if (creditReturnsCountEl) {
            const ncn = rangeData.credit_note_document_count != null ? rangeData.credit_note_document_count : 0;
            creditReturnsCountEl.textContent = ncn > 0 ? String(ncn) : '0';
        }
        if (todayGrossProfitEl) todayGrossProfitEl.textContent = typeof formatCurrency === 'function' ? formatCurrency(rangeData.gross_profit) : rangeData.gross_profit;
        if (todayGrossProfitMetaEl) {
            todayGrossProfitMetaEl.textContent =
                'Gross Profit • Margin ' + (rangeData.margin_percent != null ? rangeData.margin_percent.toFixed(1) : '0') + '% (on net sales ex VAT)';
        }
        if (expiringItemsEl) expiringItemsEl.textContent = (kpisData.expiringCount != null ? kpisData.expiringCount : '—');
        if (expiringItemsMetaEl) {
            const ev = (kpisData.expiringValue != null ? Number(kpisData.expiringValue) : 0);
            const valueText = (typeof formatCurrency === 'function') ? formatCurrency(ev) : String(ev);
            expiringItemsMetaEl.textContent = 'Expiring Soon • Value: ' + valueText;
        }
        if (orderBookPendingEl) orderBookPendingEl.textContent = (kpisData.orderBookPending != null ? kpisData.orderBookPending : '—');
        if (belowMarginEl) belowMarginEl.textContent = (rangeData.below_margin_lines != null ? rangeData.below_margin_lines : '—');

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
            const cost = (r.last_wholesale_unit_cost != null ? Number(r.last_wholesale_unit_cost) : 0);
            const supplier = (typeof escapeHtml === 'function' ? escapeHtml(r.supplier_name || '') : (r.supplier_name || '')).replace(/"/g, '&quot;');
            const qty = (typeof formatNumber === 'function' ? formatNumber(r.quantity_needed) : (r.quantity_needed != null ? r.quantity_needed : 0));
            const unit = (typeof escapeHtml === 'function' ? escapeHtml(r.unit_name || '') : (r.unit_name || '')).replace(/"/g, '&quot;');
            return '<tr><td>' + name + '</td><td style="text-align: right;">' + (typeof formatCurrency === 'function' ? formatCurrency(cost) : String(cost)) + '</td><td>' + (supplier || '—') + '</td><td style="text-align: right;">' + qty + ' ' + (unit || '') + '</td></tr>';
        }).join('');

        const tableContent = `
            <div style="max-height: 60vh; overflow-y: auto; margin-bottom: 1rem;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background: white;">
                        <tr>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: left;">Item</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align: right;">Last wholesale cost</th>
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

async function showOrdersProcessedModal() {
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }
    if (!API.sales || typeof API.sales.getOrdersProcessedItemsSummary !== 'function') {
        if (typeof showToast === 'function') showToast('Orders summary not available.', 'warning');
        return;
    }

    const params = getDashboardParams();
    const qp = {};
    if (params && params.preset && params.preset !== 'custom') qp.preset = params.preset;
    if (params && params.preset === 'custom') {
        if (params.startDate) qp.start_date = params.startDate;
        if (params.endDate) qp.end_date = params.endDate;
    }
    qp.limit = 400;

    const content = '<div class="spinner" style="margin: 2rem auto;"></div><p style="text-align: center;">Loading order items...</p>';
    const footer = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
    if (typeof showModal === 'function') showModal('Orders Processed — Item Summary', content, footer, 'modal-large');

    try {
        const res = await API.sales.getOrdersProcessedItemsSummary(branchId, qp);
        const rows = (res && Array.isArray(res.rows)) ? res.rows : [];
        if (!rows.length) {
            const empty = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No processed order items in this range.</p>';
            if (typeof showModal === 'function') showModal('Orders Processed — Item Summary', empty, footer, 'modal-large');
            return;
        }
        const tr = rows.map(function (r) {
            const item = (typeof escapeHtml === 'function') ? escapeHtml(r.item_name || '—') : (r.item_name || '—');
            const unit = (typeof escapeHtml === 'function') ? escapeHtml(r.unit_name || '') : (r.unit_name || '');
            const qty = (typeof formatNumber === 'function') ? formatNumber(r.quantity || 0) : String(r.quantity || 0);
            const freq = (r.frequency != null ? Number(r.frequency) : 0);
            const up = (typeof formatCurrency === 'function') ? formatCurrency(r.unit_price || 0) : String(r.unit_price || 0);
            const tp = (typeof formatCurrency === 'function') ? formatCurrency(r.total_price || 0) : String(r.total_price || 0);
            return `
                <tr>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${item}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${qty} ${unit}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${freq}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${up}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${tp}</td>
                </tr>
            `;
        }).join('');
        const table = `
            <div style="max-height: 65vh; overflow:auto;">
                <table style="width:100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background: white;">
                        <tr>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Item</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Quantities</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Frequency</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Unit price</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Total price</th>
                        </tr>
                    </thead>
                    <tbody>${tr}</tbody>
                </table>
            </div>
        `;
        if (typeof showModal === 'function') showModal('Orders Processed — Item Summary', table, footer, 'modal-large');
    } catch (e) {
        console.error('Orders processed summary failed:', e);
        const msg = `<p style="color: var(--danger-color); padding: 1rem;">Failed to load summary.</p>`;
        if (typeof showModal === 'function') showModal('Orders Processed — Item Summary', msg, footer, 'modal-large');
    }
}

async function showCreditReturnsItemsModal() {
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }
    if (!API.sales || typeof API.sales.getCreditNotesItemsSummary !== 'function') {
        if (typeof showToast === 'function') showToast('Credit returns summary not available.', 'warning');
        return;
    }

    const params = getDashboardParams();
    const qp = {};
    if (params && params.preset && params.preset !== 'custom') qp.preset = params.preset;
    if (params && params.preset === 'custom') {
        if (params.startDate) qp.start_date = params.startDate;
        if (params.endDate) qp.end_date = params.endDate;
    }
    qp.limit = 400;

    const content = '<div class="spinner" style="margin: 2rem auto;"></div><p style="text-align: center;">Loading credited items...</p>';
    const footer = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
    if (typeof showModal === 'function') {
        showModal('Customer credits — Item summary (by original sale date)', content, footer, 'modal-large');
    }

    try {
        const res = await API.sales.getCreditNotesItemsSummary(branchId, qp);
        const rows = (res && Array.isArray(res.rows)) ? res.rows : [];
        if (!rows.length) {
            const empty = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No credited line items in this range (credits are matched to the invoice sale date).</p>';
            if (typeof showModal === 'function') showModal('Customer credits — Item summary (by original sale date)', empty, footer, 'modal-large');
            return;
        }
        const tr = rows.map(function (r) {
            const item = (typeof escapeHtml === 'function') ? escapeHtml(r.item_name || '—') : (r.item_name || '—');
            const unit = (typeof escapeHtml === 'function') ? escapeHtml(r.unit_name || '') : (r.unit_name || '');
            const qty = (typeof formatNumber === 'function') ? formatNumber(r.quantity || 0) : String(r.quantity || 0);
            const freq = (r.frequency != null ? Number(r.frequency) : 0);
            const up = (typeof formatCurrency === 'function') ? formatCurrency(r.unit_price || 0) : String(r.unit_price || 0);
            const tp = (typeof formatCurrency === 'function') ? formatCurrency(r.total_price || 0) : String(r.total_price || 0);
            return (
                '<tr>' +
                '<td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">' + item + '</td>' +
                '<td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">' + qty + ' ' + unit + '</td>' +
                '<td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">' + freq + '</td>' +
                '<td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">' + up + '</td>' +
                '<td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">' + tp + '</td>' +
                '</tr>'
            );
        }).join('');
        const table = (
            '<p style="font-size:0.8rem;color:var(--text-secondary);margin:0 0 0.75rem 0;">Totals reduce net sales on the <strong>original invoice date</strong>, even if the credit note is dated later.</p>' +
            '<div style="max-height: 65vh; overflow:auto;">' +
            '<table style="width:100%; border-collapse: collapse;">' +
            '<thead style="position: sticky; top: 0; background: white;">' +
            '<tr>' +
            '<th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Item</th>' +
            '<th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Qty returned</th>' +
            '<th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Lines</th>' +
            '<th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Avg unit (excl.)</th>' +
            '<th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Total (excl.)</th>' +
            '</tr></thead><tbody>' + tr + '</tbody></table></div>'
        );
        if (typeof showModal === 'function') showModal('Customer credits — Item summary (by original sale date)', table, footer, 'modal-large');
    } catch (e) {
        console.error('Credit returns summary failed:', e);
        const msg = '<p style="color: var(--danger-color); padding: 1rem;">Failed to load summary.</p>';
        if (typeof showModal === 'function') showModal('Customer credits — Item summary (by original sale date)', msg, footer, 'modal-large');
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
    const days = cachedExpiringSoonDays || 365;
    if (typeof showModal === 'function') showModal(`Expiring Soon (within ${days} days)`, content, footer, 'modal-large');

    try {
        const list = await API.inventory.getExpiringList(branchId, days);
        cachedExpiringList = list || [];

        if (!list || list.length === 0) {
            const emptyContent = `<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No items expiring within the next ${days} days.</p>`;
            const emptyFooter = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
            if (typeof showModal === 'function') showModal(`Expiring Soon (within ${days} days)`, emptyContent, emptyFooter, 'modal-large');
            return;
        }

        const rows = list.map(function (r) {
            const name = (typeof escapeHtml === 'function' ? escapeHtml(r.item_name || '') : (r.item_name || '')).replace(/"/g, '&quot;');
            const batch = (typeof escapeHtml === 'function' ? escapeHtml(r.batch_number || '') : (r.batch_number || '')).replace(/"/g, '&quot;');
            const expiry = r.expiry_date ? (typeof formatDate === 'function' ? formatDate(r.expiry_date) : r.expiry_date) : '—';
            const qtyDisplay = r.quantity_display != null ? (typeof escapeHtml === 'function' ? escapeHtml(r.quantity_display) : r.quantity_display) : ((typeof formatNumber === 'function' ? formatNumber(r.quantity) : r.quantity) + ' ' + (r.retail_unit || r.base_unit || ''));
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
            <p style="color: var(--text-secondary); font-size: 0.875rem;">${list.length} batch(es) expiring within ${days} days</p>
        `;
        const modalFooter = '<button class="btn btn-outline" onclick="exportExpiringToCsv()"><i class="fas fa-file-csv"></i> Export CSV</button><button class="btn btn-outline" onclick="closeModal()">Close</button>';
        if (typeof showModal === 'function') showModal(`Expiring Soon (within ${days} days)`, tableContent, modalFooter, 'modal-large');
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
        const qty = r.quantity_display != null ? r.quantity_display : (r.quantity + ' ' + (r.retail_unit || r.base_unit || ''));
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

async function showBelowMarginModal() {
    const branchId = getBranchIdForStock();
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return;
    }
    if (!API.sales || typeof API.sales.getBelowMarginDetails !== 'function') {
        if (typeof showToast === 'function') showToast('Below-margin report not available.', 'warning');
        return;
    }

    const params = getDashboardParams();
    const qp = {};
    if (params && params.preset && params.preset !== 'custom') qp.preset = params.preset;
    if (params && params.preset === 'custom') {
        if (params.startDate) qp.start_date = params.startDate;
        if (params.endDate) qp.end_date = params.endDate;
    }

    const content = '<div class="spinner" style="margin: 2rem auto;"></div><p style="text-align: center;">Loading report...</p>';
    const footer = '<button class="btn btn-outline" onclick="closeModal()">Close</button>';
    if (typeof showModal === 'function') showModal('Sold below sustainable margin', content, footer, 'modal-large');

    try {
        const res = await API.sales.getBelowMarginDetails(branchId, { ...qp, limit: 300, offset: 0 });
        const rows = (res && Array.isArray(res.rows)) ? res.rows : [];
        if (!rows.length) {
            const empty = '<p style="padding: 2rem; text-align: center; color: var(--text-secondary);">No below-margin sales in this range.</p>';
            if (typeof showModal === 'function') showModal('Sold below sustainable margin', empty, footer, 'modal-large');
            return;
        }
        const tr = rows.map(r => {
            const d = (r.invoice_date || '').slice(0, 10);
            const inv = r.invoice_no || '—';
            const cust = r.customer_name || 'Walk-in';
            const item = r.item_name || '—';
            const unit = r.unit_name || '';
            const qty = (r.quantity_sale_unit != null ? Number(r.quantity_sale_unit) : 0);
            const base = (r.quantity_base_unit != null ? Number(r.quantity_base_unit) : 0);
            const price = (r.unit_price_exclusive != null ? Number(r.unit_price_exclusive) : 0);
            const mp = (r.computed_margin_pct != null ? Number(r.computed_margin_pct) : null);
            const minp = (r.sustainable_min_margin_pct != null ? Number(r.sustainable_min_margin_pct) : null);
            const fm = (v) => (v == null || isNaN(v)) ? '—' : (v.toFixed(1) + '%');
            const fc = (v) => (typeof formatCurrency === 'function') ? formatCurrency(v) : String(v);
            const esc = (v) => (typeof escapeHtml === 'function') ? escapeHtml(v) : String(v);
            return `
                <tr>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color);">${d}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color);">${esc(inv)}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color);">${esc(cust)}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color);">${esc(item)}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color); text-align:right;">${(typeof formatNumber==='function')?formatNumber(qty):qty} ${esc(unit)}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color); text-align:right;">${(typeof formatNumber==='function')?formatNumber(base):base}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color); text-align:right;">${fc(price)}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color); text-align:right;">${fm(mp)}</td>
                    <td style="padding:0.5rem; border-bottom:1px solid var(--border-color); text-align:right;">${fm(minp)}</td>
                </tr>
            `;
        }).join('');
        const table = `
            <div style="max-height: 65vh; overflow:auto;">
                <table style="width:100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background: white;">
                        <tr>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:left;">Date</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:left;">Invoice</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:left;">Account</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:left;">Item</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:right;">Units sold</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:right;">Pieces (base)</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:right;">Price/Unit</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:right;">Margin</th>
                            <th style="padding:0.5rem; border-bottom:2px solid var(--border-color); text-align:right;">Min</th>
                        </tr>
                    </thead>
                    <tbody>${tr}</tbody>
                </table>
            </div>
        `;
        if (typeof showModal === 'function') showModal('Sold below sustainable margin', table, footer, 'modal-large');
    } catch (e) {
        console.error('Below margin modal failed:', e);
        const msg = `<p style="color: var(--danger-color); padding: 1rem;">Failed to load report.</p>`;
        if (typeof showModal === 'function') showModal('Sold below sustainable margin', msg, footer, 'modal-large');
    }
}

// Export
window.loadDashboard = loadDashboard;
window.applyDashboardFilters = applyDashboardFilters;
window.showOrderBookPendingTodayModal = showOrderBookPendingTodayModal;
window.openOrderBookFromDashboard = openOrderBookFromDashboard;
window.showOrdersProcessedModal = showOrdersProcessedModal;
window.showCreditReturnsItemsModal = showCreditReturnsItemsModal;
window.showExpiringSoonModal = showExpiringSoonModal;
window.exportExpiringToCsv = exportExpiringToCsv;
window.openFinancialReportsFromDashboard = openFinancialReportsFromDashboard;
window.showBelowMarginModal = showBelowMarginModal;
