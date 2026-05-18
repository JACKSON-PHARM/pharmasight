// Branch performance — financial health by branch

async function renderFinanceBranches() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API) return;

    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-code-branch"></i> Branch performance</h2>
                <p>Which branches are financially weak? Revenue, profit, expenses, and stock risk.</p>
            </div>
            ${FO.filterToolbarHtml({ since: range.since, until: range.until, showBranch: false, showEventType: false })}
            <div id="fccBranchOut"><p style="opacity:0.7;">Select period, then refresh.</p></div>
        </div>`;
    FO.bindRefresh(load);
    await load();

    async function load() {
        const out = document.getElementById('fccBranchOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const from = document.getElementById('foDateFrom')?.value || range.since;
        const until = document.getElementById('foDateTo')?.value || range.until;
        try {
            const data = await API.financeCommandCenter.overview({
                from_date: from,
                to_date: until,
                branch_id: undefined,
            });
            const rows = data.branch_performance || [];
            if (!rows.length) {
                out.innerHTML = '<p style="opacity:0.7;">No branch data.</p>';
                return;
            }
            const badge = (kind) => {
                const k = (kind || '').toLowerCase();
                const cls = k === 'healthy' || k === 'strong' ? 'healthy' : k === 'critical' || k === 'loss' ? 'critical' : 'warning';
                return `<span class="fcc-badge fcc-badge--${cls}">${FO.escapeHtml((kind || '—').replace(/_/g, ' '))}</span>`;
            };
            out.innerHTML = `
                <table class="fcc-table">
                    <thead><tr>
                        <th>Branch</th><th class="num">Revenue</th><th class="num">Profit</th><th class="num">Expenses</th>
                        <th class="num">Stock</th><th>Stock risk</th><th>Cash</th><th>Profitability</th>
                    </tr></thead>
                    <tbody>
                    ${rows
                        .map(
                            (r) => `<tr>
                        <td>${FO.escapeHtml(r.branch_name)}${r.is_hq ? ' (HQ)' : ''}</td>
                        <td class="num">${FO.fmtMoney(r.revenue)}</td>
                        <td class="num">${FO.fmtMoney(r.profit)}</td>
                        <td class="num">${FO.fmtMoney(r.expenses)}</td>
                        <td class="num">${FO.fmtMoney(r.stock_value)}</td>
                        <td>${badge(r.stock_risk)}</td>
                        <td>${badge(r.cash_health)}</td>
                        <td>${badge(r.profit_health)}</td>
                    </tr>`
                        )
                        .join('')}
                    </tbody>
                </table>`;
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

window.renderFinanceBranches = renderFinanceBranches;
