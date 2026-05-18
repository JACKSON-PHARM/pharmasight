// Profitability — P&L for the period

async function renderFinanceProfitability() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.accountingGl) return;

    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-chart-line"></i> Profitability</h2>
                <p>Did we make money this period? GL-authoritative profit and loss.</p>
            </div>
            ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
            <div id="fccPnlOut"><p style="opacity:0.7;">Select branch and period, then refresh.</p></div>
        </div>`;

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    FO.bindRefresh(load);

    async function load() {
        const out = document.getElementById('fccPnlOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading P&amp;L…</p>';
        const p = FO.readFilterParams();
        try {
            const pnl = await API.accountingGl.profitAndLoss({
                from_date: p.since,
                to_date: p.until,
                branch_id: p.branch_id,
            });
            const lines = pnl.lines || pnl.accounts || [];
            const net = pnl.net_income ?? pnl.net_profit;
            const rev = pnl.revenue ?? pnl.total_revenue;
            const exp = pnl.operating_expenses ?? pnl.total_expenses;
            const gross = pnl.gross_profit;
            let body = '';
            if (rev != null || exp != null || net != null) {
                body += `<div class="fcc-strip" style="margin-bottom:1rem;">
                    ${rev != null ? `<div class="fcc-card"><div class="fcc-card-label">Revenue</div><div class="fcc-card-value">${FO.fmtMoney(rev)}</div></div>` : ''}
                    ${gross != null ? `<div class="fcc-card"><div class="fcc-card-label">Gross profit</div><div class="fcc-card-value">${FO.fmtMoney(gross)}</div></div>` : ''}
                    ${exp != null ? `<div class="fcc-card"><div class="fcc-card-label">Operating expenses</div><div class="fcc-card-value">${FO.fmtMoney(exp)}</div></div>` : ''}
                    ${net != null ? `<div class="fcc-card ${Number(net) >= 0 ? 'fcc-card--positive' : 'fcc-card--negative'}"><div class="fcc-card-label">Net income</div><div class="fcc-card-value">${FO.fmtMoney(net)}</div></div>` : ''}
                </div>`;
            }
            if (lines.length) {
                body += `<table class="fcc-table"><thead><tr><th>Account</th><th class="num">Amount</th></tr></thead><tbody>
                    ${lines
                        .map(
                            (l) =>
                                `<tr><td>${FO.escapeHtml(l.account_name || l.name || l.code || '')}</td><td class="num">${FO.fmtMoney(l.amount ?? l.balance)}</td></tr>`
                        )
                        .join('')}
                </tbody></table>`;
            } else if (!body) {
                body = '<p style="opacity:0.7;">No P&amp;L data. Ensure chart of accounts is provisioned and GL is posted.</p>';
            }
            out.innerHTML = body.replace(/<\/?motion\b/gi, (m) => m.replace(/motion/gi, 'div'));
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

window.renderFinanceProfitability = renderFinanceProfitability;
