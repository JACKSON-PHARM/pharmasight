// Reports Page - Sales / Inventory / Financial

console.log('[REPORTS.JS] Script loading...');

let currentReportsSubPage = 'financial';

function _fmtDateInput(d) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

function _parseDateInput(v) {
    if (!v) return null;
    const parts = String(v).split('-');
    if (parts.length !== 3) return null;
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    if (isNaN(d.getTime())) return null;
    d.setHours(0, 0, 0, 0);
    return d;
}

function _startOfWeekMonday(d) {
    const x = new Date(d);
    const wd = x.getDay(); // 0..6 (Sun..Sat)
    const diff = (wd === 0 ? -6 : 1 - wd); // move to Monday
    x.setDate(x.getDate() + diff);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _endOfWeekSunday(d) {
    const s = _startOfWeekMonday(d);
    const e = new Date(s);
    e.setDate(e.getDate() + 6);
    e.setHours(0, 0, 0, 0);
    return e;
}

function _startOfMonth(d) {
    const x = new Date(d.getFullYear(), d.getMonth(), 1);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _endOfMonth(d) {
    const x = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _startOfYear(d) {
    const x = new Date(d.getFullYear(), 0, 1);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _endOfYear(d) {
    const x = new Date(d.getFullYear(), 11, 31);
    x.setHours(0, 0, 0, 0);
    return x;
}

function _computePresetRange(preset) {
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const p = (preset || '').toLowerCase();
    if (p === 'today') return { start: now, end: now };
    if (p === 'this_week') return { start: _startOfWeekMonday(now), end: _endOfWeekSunday(now) };
    if (p === 'last_week') {
        const end = new Date(_startOfWeekMonday(now));
        end.setDate(end.getDate() - 1);
        end.setHours(0, 0, 0, 0);
        const start = _startOfWeekMonday(end);
        return { start, end };
    }
    if (p === 'this_month') return { start: _startOfMonth(now), end: _endOfMonth(now) };
    if (p === 'last_month') {
        const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        prev.setHours(0, 0, 0, 0);
        return { start: _startOfMonth(prev), end: _endOfMonth(prev) };
    }
    if (p === 'this_year') return { start: _startOfYear(now), end: _endOfYear(now) };
    if (p === 'last_year') {
        const prev = new Date(now.getFullYear() - 1, 0, 1);
        prev.setHours(0, 0, 0, 0);
        return { start: _startOfYear(prev), end: _endOfYear(prev) };
    }
    return { start: now, end: now };
}

async function loadReports(subPage = null) {
    const page = document.getElementById('reports');
    if (!page) {
        console.error('[REPORTS] Page element not found');
        return;
    }
    const target = subPage || currentReportsSubPage || 'financial';
    await loadReportsSubPage(target);
}

async function loadReportsSubPage(subPage) {
    currentReportsSubPage = subPage || 'financial';
    const page = document.getElementById('reports');
    if (!page) return;

    // Basic shell
    const titleMap = {
        'sales': 'Sales Reports',
        'inventory': 'Inventory Reports',
        'financial': 'Financial Reports',
        'custom': 'Custom Reports'
    };
    const title = titleMap[currentReportsSubPage] || 'Reports';

    page.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-chart-bar"></i> ${title}</h3>
            </div>
            <div class="card-body" id="reportsBody">
                <div class="spinner" style="margin: 1rem auto;"></div>
            </div>
        </div>
    `;

    if (currentReportsSubPage !== 'financial') {
        const body = document.getElementById('reportsBody');
        if (body) {
            body.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    <p>This report is coming soon.</p>
                </div>
            `;
        }
        return;
    }

    await renderFinancialReports();
}

function _ensureBranchSelected() {
    const branchId = (typeof BranchContext !== 'undefined' && BranchContext.getBranch && BranchContext.getBranch()?.id) || CONFIG.BRANCH_ID || null;
    if (!branchId) {
        if (typeof showToast === 'function') showToast('Select a branch first.', 'warning');
        return null;
    }
    return branchId;
}

async function renderFinancialReports() {
    const body = document.getElementById('reportsBody');
    if (!body) return;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const defaultStart = _fmtDateInput(today);
    const defaultEnd = _fmtDateInput(today);

    body.innerHTML = `
        <div style="display:flex; flex-wrap:wrap; gap:0.75rem; align-items:end; margin-bottom: 1rem;">
            <div class="form-group" style="min-width: 220px; margin: 0;">
                <label class="form-label">Quick filter</label>
                <select class="form-input" id="plPreset">
                    <option value="today" selected>Today</option>
                    <option value="this_week">This week</option>
                    <option value="last_week">Last week</option>
                    <option value="this_month">This month</option>
                    <option value="last_month">Last month</option>
                    <option value="this_year">This year</option>
                    <option value="last_year">Last year</option>
                    <option value="custom">Custom</option>
                </select>
            </div>
            <div class="form-group" style="margin: 0;">
                <label class="form-label">Start date</label>
                <input type="date" class="form-input" id="plStart" value="${defaultStart}">
            </div>
            <div class="form-group" style="margin: 0;">
                <label class="form-label">End date</label>
                <input type="date" class="form-input" id="plEnd" value="${defaultEnd}">
            </div>
            <div style="margin: 0;">
                <button class="btn btn-primary" id="plApplyBtn"><i class="fas fa-filter"></i> Apply</button>
            </div>
        </div>

        <div class="stats-grid" style="margin-bottom: 1rem;">
            <div class="stat-card">
                <div class="stat-icon"><i class="fas fa-receipt"></i></div>
                <div class="stat-info">
                    <h3 id="plSales">—</h3>
                    <p>Sales (exclusive)</p>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="fas fa-boxes-stacked"></i></div>
                <div class="stat-info">
                    <h3 id="plCogs">—</h3>
                    <p>Cost of goods sold (COGS)</p>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="fas fa-chart-pie"></i></div>
                <div class="stat-info">
                    <h3 id="plGrossProfit">—</h3>
                    <p id="plMeta">Gross profit • Margin —</p>
                </div>
            </div>
        </div>

        <div class="card" style="margin-top: 0.5rem;">
            <div class="card-header">
                <h3 class="card-title"><i class="fas fa-calendar-day"></i> Breakdown</h3>
            </div>
            <div class="card-body" id="plBreakdown">
                <p style="color: var(--text-secondary);">Apply a filter to load results.</p>
            </div>
        </div>
    `;

    const presetEl = document.getElementById('plPreset');
    const startEl = document.getElementById('plStart');
    const endEl = document.getElementById('plEnd');
    const applyBtn = document.getElementById('plApplyBtn');

    function applyPreset(p) {
        if (p === 'custom') return;
        const r = _computePresetRange(p);
        startEl.value = _fmtDateInput(r.start);
        endEl.value = _fmtDateInput(r.end);
    }

    presetEl.addEventListener('change', () => {
        const p = presetEl.value;
        applyPreset(p);
    });

    applyBtn.addEventListener('click', async () => {
        await loadGrossProfitReport();
    });

    // Default: today
    await loadGrossProfitReport();
}

async function loadGrossProfitReport() {
    const branchId = _ensureBranchSelected();
    if (!branchId) return;

    const startEl = document.getElementById('plStart');
    const endEl = document.getElementById('plEnd');
    const salesEl = document.getElementById('plSales');
    const cogsEl = document.getElementById('plCogs');
    const gpEl = document.getElementById('plGrossProfit');
    const metaEl = document.getElementById('plMeta');
    const breakdownEl = document.getElementById('plBreakdown');

    if (!startEl || !endEl || !salesEl || !cogsEl || !gpEl || !metaEl || !breakdownEl) return;

    const sd = _parseDateInput(startEl.value);
    const ed = _parseDateInput(endEl.value);
    if (!sd || !ed) {
        if (typeof showToast === 'function') showToast('Please pick a valid start and end date.', 'warning');
        return;
    }

    const start = _fmtDateInput(sd);
    const end = _fmtDateInput(ed);

    breakdownEl.innerHTML = '<div class="spinner" style="margin: 1rem auto;"></div>';
    salesEl.textContent = '—';
    cogsEl.textContent = '—';
    gpEl.textContent = '—';
    metaEl.textContent = 'Gross profit • Margin —';

    try {
        if (!API || !API.sales || typeof API.sales.getGrossProfit !== 'function') {
            throw new Error('Gross profit API not available');
        }
        const res = await API.sales.getGrossProfit(branchId, { start_date: start, end_date: end, include_breakdown: true });
        const sales = parseFloat(res.sales_exclusive || 0);
        const cogs = parseFloat(res.cogs || 0);
        const gp = parseFloat(res.gross_profit || 0);
        const margin = parseFloat(res.margin_percent || 0);

        salesEl.textContent = (typeof formatCurrency === 'function') ? formatCurrency(sales) : String(sales);
        cogsEl.textContent = (typeof formatCurrency === 'function') ? formatCurrency(cogs) : String(cogs);
        gpEl.textContent = (typeof formatCurrency === 'function') ? formatCurrency(gp) : String(gp);
        metaEl.textContent = `Gross profit • Margin ${margin.toFixed(1)}%`;

        const rows = Array.isArray(res.breakdown) ? res.breakdown : [];
        if (!rows.length) {
            breakdownEl.innerHTML = '<p style="color: var(--text-secondary);">No transactions in this date range.</p>';
            return;
        }

        const tr = rows.map(r => {
            const d = (r.date || '').slice(0, 10);
            const s = parseFloat(r.sales_exclusive || 0);
            const c = parseFloat(r.cogs || 0);
            const g = parseFloat(r.gross_profit || 0);
            const m = parseFloat(r.margin_percent || 0);
            const fc = (v) => (typeof formatCurrency === 'function') ? formatCurrency(v) : String(v);
            return `
                <tr>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color);">${d}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${fc(s)}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${fc(c)}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${fc(g)}</td>
                    <td style="padding: 0.5rem; border-bottom: 1px solid var(--border-color); text-align:right;">${m.toFixed(1)}%</td>
                </tr>
            `;
        }).join('');

        breakdownEl.innerHTML = `
            <div style="overflow:auto;">
                <table style="width:100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:left;">Date</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Sales (excl)</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">COGS</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Gross profit</th>
                            <th style="padding: 0.5rem; border-bottom: 2px solid var(--border-color); text-align:right;">Margin</th>
                        </tr>
                    </thead>
                    <tbody>${tr}</tbody>
                </table>
            </div>
        `;
    } catch (err) {
        console.error('[REPORTS] Gross profit load failed:', err);
        breakdownEl.innerHTML = `<p style="color: var(--danger-color);">Failed to load report. ${(err && err.message) ? err.message : ''}</p>`;
        if (typeof showToast === 'function') showToast('Failed to load gross profit report', 'error');
    }
}

// Export
if (typeof window !== 'undefined') {
    window.loadReports = loadReports;
    window.loadReportsSubPage = loadReportsSubPage;
}

