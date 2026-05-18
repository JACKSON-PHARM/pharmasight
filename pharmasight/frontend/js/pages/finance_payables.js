// Payables — supplier exposure

async function renderFinancePayables() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API) return;

    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-truck"></i> Payables</h2>
                <p>Who you owe — outstanding supplier balances and procurement pressure.</p>
            </div>
            ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
            <div id="fccPayablesOut"><p style="opacity:0.7;">Select branch, then refresh.</p></div>
        </div>`;

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    FO.bindRefresh(load);

    async function load() {
        const out = document.getElementById('fccPayablesOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const p = FO.readFilterParams();
        try {
            const enriched = await API.suppliers.listEnriched({ branch_id: p.branch_id });
            const rows = Array.isArray(enriched) ? enriched : enriched?.items || enriched?.suppliers || [];
            const withBal = rows
                .map((s) => ({
                    name: s.name || s.supplier_name || 'Supplier',
                    outstanding: parseFloat(s.balance ?? s.outstanding_balance ?? s.total_outstanding ?? 0),
                }))
                .filter((r) => r.outstanding > 0.01)
                .sort((a, b) => b.outstanding - a.outstanding);

            if (!withBal.length) {
                out.innerHTML = '<p style="opacity:0.7;">No outstanding supplier balances for this branch.</p>';
                return;
            }
            out.innerHTML = `
                <table class="fcc-table">
                    <thead><tr><th>Supplier</th><th class="num">Outstanding</th></tr></thead>
                    <tbody>
                    ${withBal
                        .map(
                            (r) =>
                                `<tr><td>${FO.escapeHtml(r.name)}</td><td class="num">${FO.fmtMoney(r.outstanding)}</td></tr>`
                        )
                        .join('')}
                    </tbody>
                </table>`;
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

window.renderFinancePayables = renderFinancePayables;
