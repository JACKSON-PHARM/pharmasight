// Operational Financial Command Center — Overview (default Finance landing)

async function renderFinanceOverview() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API) return;

    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-chart-pie"></i> Financial position</h2>
                <p>State of the business — cash, receivables, payables, and profit for the selected period.</p>
            </div>
            <div class="fcc-toolbar">
                <div class="form-group">
                    <label class="form-label">View</label>
                    <select class="form-select" id="fccScope">
                        <option value="branch">This branch</option>
                        <option value="company">Whole company</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Branch</label>
                    <select class="form-select" id="fccBranch"></select>
                </div>
                <div class="form-group">
                    <label class="form-label">From</label>
                    <input type="date" class="form-input" id="fccFrom" value="${FO.escapeHtml(range.since)}">
                </div>
                <div class="form-group">
                    <label class="form-label">To</label>
                    <input type="date" class="form-input" id="fccUntil" value="${FO.escapeHtml(range.until)}">
                </div>
                <button type="button" class="btn btn-primary" id="fccRefresh"><i class="fas fa-sync-alt"></i> Refresh</button>
            </div>
            <div id="fccAlerts"></div>
            <div id="fccStrip"></div>
            <div id="fccBranches"></div>
            <div class="fcc-section" id="fccReceivables"></div>
            <div class="fcc-section" id="fccPayables"></div>
            <div class="fcc-gov-link">
                Advanced: <a href="#" data-finance-sub="reconciliation">GL reconciliation</a> ·
                <a href="#" data-finance-sub="posting-failures">Posting failures</a> ·
                <a href="#" data-finance-sub="confidence">Governance tools</a>
            </div>
        </div>`;

    const branchSel = document.getElementById('fccBranch');
    const scopeSel = document.getElementById('fccScope');
    await FO.populateBranchSelect(branchSel, CONFIG.BRANCH_ID);

    function syncBranchVisibility() {
        const isCompany = scopeSel && scopeSel.value === 'company';
        const fg = branchSel && branchSel.closest('.form-group');
        if (fg) fg.style.display = isCompany ? 'none' : '';
    }
    scopeSel.addEventListener('change', syncBranchVisibility);
    syncBranchVisibility();

    document.getElementById('fccRefresh').addEventListener('click', loadOverview);
    root.querySelectorAll('[data-finance-sub]').forEach((a) => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            const sub = a.getAttribute('data-finance-sub');
            if (typeof loadPage === 'function') loadPage('finance', sub);
        });
    });

    await loadOverview();

    async function loadOverview() {
        const strip = document.getElementById('fccStrip');
        const alertsEl = document.getElementById('fccAlerts');
        if (strip) strip.innerHTML = '<p style="opacity:0.7;">Loading financial position…</p>';
        const from = document.getElementById('fccFrom').value;
        const until = document.getElementById('fccUntil').value;
        const companyWide = scopeSel && scopeSel.value === 'company';
        const branchId = companyWide ? null : branchSel.value || CONFIG.BRANCH_ID;
        try {
            const data = await API.financeCommandCenter.overview({
                from_date: from,
                to_date: until,
                branch_id: branchId || undefined,
            });
            renderAlerts(alertsEl, data.alerts || [], FO);
            renderStrip(strip, data.position_strip, FO);
            renderBranches(document.getElementById('fccBranches'), data.branch_performance || [], FO);
            renderReceivables(document.getElementById('fccReceivables'), data.top_receivables || [], FO);
            renderPayables(document.getElementById('fccPayables'), data.top_payables || [], FO);
        } catch (err) {
            FO.showError(strip, err);
        }
    }
}

function renderAlerts(el, alerts, FO) {
    if (!el) return;
    el.innerHTML = alerts.length
        ? alerts
              .map(
                  (a) =>
                      `<div class="fcc-alert fcc-alert--${FO.escapeHtml(a.level || 'info')}">${FO.escapeHtml(a.message)}</div>`
              )
              .join('')
        : '';
}

function renderStrip(el, p, FO) {
    if (!el || !p) return;
    const netCls = p.net_liquidity_position >= 0 ? 'fcc-card--positive' : 'fcc-card--negative';
    const profCls = p.profit_this_period >= 0 ? 'fcc-card--positive' : 'fcc-card--negative';
    const cards = [
        { label: 'Cash available', value: p.cash_available, sub: 'Operational cashbook' },
        { label: 'Customer receivables', value: p.customer_receivables, sub: 'Outstanding credit sales' },
        { label: 'Supplier payables', value: p.supplier_payables, sub: 'Owed to suppliers' },
        { label: 'Net liquidity', value: p.net_liquidity_position, sub: 'Cash + AR − AP', cls: netCls },
        { label: 'Profit this period', value: p.profit_this_period, sub: `Revenue ${FO.fmtMoney(p.revenue_this_period)}`, cls: profCls },
        { label: 'Expense burn', value: p.expense_burn_this_period, sub: 'GL operating expenses' },
    ];
    el.innerHTML = `<div class="fcc-strip">${cards
        .map(
            (c) => `
        <div class="fcc-card ${c.cls || ''}">
            <div class="fcc-card-label">${FO.escapeHtml(c.label)}</div>
            <div class="fcc-card-value">${FO.fmtMoney(c.value)}</div>
            <div class="fcc-card-sub">${FO.escapeHtml(c.sub)}</div>
        </div>`
        )
        .join('')}</div>`;
}

function healthBadge(kind, FO) {
    const k = (kind || '').toLowerCase();
    const map = { healthy: 'healthy', warning: 'warning', critical: 'critical', loss: 'loss', overspending: 'warning' };
    const cls = map[k] || 'warning';
    const label = (kind || '—').replace(/_/g, ' ');
    return `<span class="fcc-badge fcc-badge--${cls}">${FO.escapeHtml(label)}</span>`;
}

function renderBranches(el, rows, FO) {
    if (!el) return;
    if (!rows.length) {
        el.innerHTML = '<div class="fcc-section"><h4>Branch performance</h4><p style="opacity:0.7;">No branches.</p></div>';
        return;
    }
    el.innerHTML = `
        <div class="fcc-section">
            <h4><i class="fas fa-code-branch"></i> Branch performance</h4>
            <div style="overflow-x:auto;">
            <table class="fcc-table">
                <thead><tr>
                    <th>Branch</th><th class="num">Revenue</th><th class="num">Profit</th><th class="num">Expenses</th>
                    <th class="num">Stock value</th><th>Stock risk</th><th>Cash</th><th>Profitability</th>
                </tr></thead>
                <tbody>
                ${rows
                    .map(
                        (r) => `<tr>
                    <td>${FO.escapeHtml(r.branch_name)}${r.is_hq ? ' <small>(HQ)</small>' : ''}</td>
                    <td class="num">${FO.fmtMoney(r.revenue)}</td>
                    <td class="num">${FO.fmtMoney(r.profit)}</td>
                    <td class="num">${FO.fmtMoney(r.expenses)}</td>
                    <td class="num">${FO.fmtMoney(r.stock_value)}</td>
                    <td>${healthBadge(r.stock_risk, FO)}</td>
                    <td>${healthBadge(r.cash_health, FO)}</td>
                    <td>${healthBadge(r.profit_health, FO)}</td>
                </tr>`
                    )
                    .join('')}
                </tbody>
            </table>
            </div>
        </div>`;
}

function renderReceivables(el, rows, FO) {
    if (!el) return;
    el.innerHTML = `
        <h4><i class="fas fa-hand-holding-usd"></i> Who owes you (top receivables)</h4>
        ${
            rows.length
                ? `<table class="fcc-table"><thead><tr><th>Customer</th><th class="num">Outstanding</th><th>Risk</th></tr></thead><tbody>
            ${rows
                .map(
                    (r) => `<tr><td>${FO.escapeHtml(r.customer_name)}</td><td class="num">${FO.fmtMoney(r.outstanding)}</td><td>${healthBadge(r.risk, FO)}</td></tr>`
                )
                .join('')}
            </tbody></table>`
                : '<p style="opacity:0.7;">No outstanding customer balances.</p>'
        }
        <p style="margin-top:0.5rem;"><a href="#" data-finance-sub="receivables">View all receivables →</a></p>`;
    el.querySelector('[data-finance-sub]')?.addEventListener('click', (e) => {
        e.preventDefault();
        if (typeof loadPage === 'function') loadPage('finance', 'receivables');
    });
}

function renderPayables(el, rows, FO) {
    if (!el) return;
    el.innerHTML = `
        <h4><i class="fas fa-truck"></i> Who you owe (top payables)</h4>
        ${
            rows.length
                ? `<table class="fcc-table"><thead><tr><th>Supplier</th><th class="num">Outstanding</th></tr></thead><tbody>
            ${rows.map((r) => `<tr><td>${FO.escapeHtml(r.supplier_name)}</td><td class="num">${FO.fmtMoney(r.outstanding)}</td></tr>`).join('')}
            </tbody></table>`
                : '<p style="opacity:0.7;">No outstanding supplier balances.</p>'
        }
        <p style="margin-top:0.5rem;"><a href="#" data-finance-sub="payables">View all payables →</a></p>`;
    el.querySelector('[data-finance-sub]')?.addEventListener('click', (e) => {
        e.preventDefault();
        if (typeof loadPage === 'function') loadPage('finance', 'payables');
    });
}

window.renderFinanceOverview = renderFinanceOverview;
