// Finance — Operational Financial Command Center

const FINANCE_OPS_SUBPAGES = {
    overview: { title: 'Overview', loader: 'renderFinanceOverview' },
    cash: { title: 'Cash & Liquidity', loader: 'renderFinanceCash' },
    receivables: { title: 'Receivables', loader: 'renderFinanceReceivables' },
    payables: { title: 'Payables', loader: 'renderFinancePayables' },
    branches: { title: 'Branch Performance', loader: 'renderFinanceBranches' },
    expenses: { title: 'Expenses', loader: 'renderFinanceExpenses' },
    inventory: { title: 'Inventory Exposure', loader: 'renderFinanceInventory' },
    profitability: { title: 'Profitability', loader: 'renderFinanceProfitability' },
    'slow-stock': { title: 'Slow-Moving Stock', loader: 'renderFinanceInventory' },
    'high-risk-customers': { title: 'High-Risk Customers', loader: 'renderFinanceReceivables' },
    claims: { title: 'Outstanding Claims', loader: 'renderFinanceRecovery' },
    'supplier-exposure': { title: 'Supplier Exposure', loader: 'renderFinancePayables' },
    'cash-pressure': { title: 'Cash Pressure', loader: 'renderFinanceReconciliation' },
    reconciliation: { title: 'Reconciliation', loader: 'renderFinanceGlReconciliation' },
    events: { title: 'Financial Activity', loader: 'renderFinanceEvents' },
    proposals: { title: 'Accounting Review', loader: 'renderFinanceProposals' },
    integrity: { title: 'Integrity & Replay', loader: 'renderFinanceIntegrity' },
    'posting-failures': { title: 'Posting Failures', loader: 'renderFinancePostingFailures' },
    confidence: { title: 'Financial Confidence', loader: 'renderFinanceConfidence' },
    treasury: { title: 'Treasury Intelligence', loader: 'renderFinanceReconciliation' },
    recovery: { title: 'Revenue Recovery', loader: 'renderFinanceRecovery' },
    projections: { title: 'Projection Explorer', loader: 'renderFinanceProjections' },
};

async function renderFinanceExpenses() {
    const root = document.getElementById('financeContent');
    if (!root) return;
    root.innerHTML = `
        <div class="fcc-scope fcc-hero">
            <h2><i class="fas fa-money-bill-wave"></i> Expenses</h2>
            <p>Operational expense detail lives in the Expenses module. Use Profitability here for GL expense burn vs revenue.</p>
            <p style="margin-top:1rem;"><a href="#" id="fccGoExpenses" class="btn btn-primary">Open Expenses module</a>
            · <a href="#" id="fccGoProfit">Profitability →</a></p>
        </div>`;
    document.getElementById('fccGoExpenses')?.addEventListener('click', (e) => {
        e.preventDefault();
        if (typeof loadPage === 'function') loadPage('expenses');
    });
    document.getElementById('fccGoProfit')?.addEventListener('click', (e) => {
        e.preventDefault();
        if (typeof loadPage === 'function') loadPage('finance', 'profitability');
    });
}

async function renderFinanceInventory() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO) return;
    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-boxes"></i> Inventory exposure</h2>
                <p>Cash locked in stock and liquidation pressure by branch (from command-center branch ranking).</p>
            </div>
            ${FO.filterToolbarHtml({ since: range.since, until: range.until, showBranch: false, showEventType: false })}
            <div id="fccInvOut"><p style="opacity:0.7;">Select period, then refresh.</p></div>
        </div>`;
    FO.bindRefresh(load);
    await load();
    async function load() {
        const out = document.getElementById('fccInvOut');
        if (!out || !API?.financeCommandCenter) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const from = document.getElementById('foDateFrom')?.value || range.since;
        const until = document.getElementById('foDateTo')?.value || range.until;
        try {
            const data = await API.financeCommandCenter.overview({ from_date: from, to_date: until });
            const rows = data.branch_performance || [];
            if (!rows.length) {
                out.innerHTML = '<p style="opacity:0.7;">No inventory exposure data.</p>';
                return;
            }
            out.innerHTML = `
                <table class="fcc-table">
                    <thead><tr><th>Branch</th><th class="num">Stock value</th><th>Stock risk</th><th>Profitability</th></tr></thead>
                    <tbody>${rows
                        .map(
                            (r) => `<tr>
                        <td>${FO.escapeHtml(r.branch_name)}</td>
                        <td class="num">${FO.fmtMoney(r.stock_value)}</td>
                        <td><span class="fcc-badge fcc-badge--${r.stock_risk === 'healthy' ? 'healthy' : 'warning'}">${FO.escapeHtml(r.stock_risk || '—')}</span></td>
                        <td><span class="fcc-badge fcc-badge--${r.profit_health === 'healthy' ? 'healthy' : 'warning'}">${FO.escapeHtml(r.profit_health || '—')}</span></td>
                    </tr>`
                        )
                        .join('')}</tbody>
                </table>
                <p class="fcc-gov-link" style="margin-top:1rem;">Near-expiry and sell-through detail: Inventory reports (coming).</p>`;
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

async function loadFinance(subPage) {
    const page = document.getElementById('finance');
    if (!page) return;

    const key = subPage && FINANCE_OPS_SUBPAGES[subPage] ? subPage : 'overview';
    const meta = FINANCE_OPS_SUBPAGES[key];

    page.innerHTML = `<div id="financeContent" class="fcc-scope-wrap"><p style="opacity:0.7;">Loading ${meta.title}…</p></div>`;

    const loader = typeof window[meta.loader] === 'function' ? window[meta.loader] : null;
    if (!loader) {
        const root = document.getElementById('financeContent');
        if (root) {
            root.innerHTML =
                '<div class="card"><div class="card-body"><p>Finance module failed to load. Refresh the page.</p></div></div>';
            root.innerHTML = root.innerHTML.replace(/<\/?motion\b/gi, (m) => m.replace(/motion/gi, 'div'));
        }
        return;
    }
    await loader();
}

window.loadFinance = loadFinance;
window.FINANCE_OPS_SUBPAGES = FINANCE_OPS_SUBPAGES;
window.renderFinanceExpenses = renderFinanceExpenses;
window.renderFinanceInventory = renderFinanceInventory;
