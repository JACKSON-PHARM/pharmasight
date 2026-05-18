// Receivables — collection decisions

async function renderFinanceReceivables() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API) return;

    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-hand-holding-usd"></i> Receivables</h2>
                <p>Who owes you — outstanding balances and aging for collection decisions.</p>
            </div>
            ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
            <div id="fccReceivablesOut"><p style="opacity:0.7;">Select branch, then refresh.</p></div>
        </div>`;
    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    FO.bindRefresh(load);

    async function load() {
        const out = document.getElementById('fccReceivablesOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const p = FO.readFilterParams();
        try {
            const [enriched, aging] = await Promise.all([
                API.customers.listEnriched({ branch_id: p.branch_id }),
                API.customers.getAging({ branch_id: p.branch_id, as_of_date: p.until }),
            ]);
            const rows = Array.isArray(enriched) ? enriched : enriched?.items || enriched?.customers || [];
            const agingRows = aging?.buckets || aging?.customers || aging?.rows || [];
            const agingById = {};
            (Array.isArray(agingRows) ? agingRows : []).forEach((a) => {
                const id = a.customer_id || a.id;
                if (id) agingById[id] = a;
            });
            const withBal = rows
                .map((c) => {
                    const bal = parseFloat(c.balance ?? c.outstanding_balance ?? c.total_outstanding ?? 0);
                    const ag = agingById[c.id] || {};
                    const days = ag.max_days ?? ag.days_outstanding ?? ag.oldest_days ?? null;
                    return {
                        name: c.name || c.customer_name || 'Customer',
                        outstanding: bal,
                        days,
                        risk: bal <= 0 ? 'healthy' : days >= 90 ? 'critical' : days >= 45 ? 'warning' : 'moderate',
                    };
                })
                .filter((r) => r.outstanding > 0.01)
                .sort((a, b) => b.outstanding - a.outstanding);

            if (!withBal.length) {
                out.innerHTML = '<p style="opacity:0.7;">No outstanding customer balances for this branch.</p>';
                return;
            }
            out.innerHTML = `
                <table class="fcc-table">
                    <thead><tr>
                        <th>Customer</th><th class="num">Outstanding</th><th>Aging</th><th>Risk</th>
                    </tr></thead>
                    <tbody>
                    ${withBal
                        .map(
                            (r) => `<tr>
                        <td>${FO.escapeHtml(r.name)}</td>
                        <td class="num">${FO.fmtMoney(r.outstanding)}</td>
                        <td>${r.days != null ? `${FO.escapeHtml(String(r.days))} days` : '—'}</td>
                        <td><span class="fcc-badge fcc-badge--${r.risk === 'critical' ? 'critical' : r.risk === 'warning' ? 'warning' : 'healthy'}">${FO.escapeHtml(r.risk)}</span></td>
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

window.renderFinanceReceivables = renderFinanceReceivables;
