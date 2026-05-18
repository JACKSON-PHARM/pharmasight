// Cash & Liquidity

async function renderFinanceCash() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API) return;

    const range = FO.defaultDateRange();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-wallet"></i> Cash &amp; Liquidity</h2>
                <p>How much money do we have? Cashbook and net liquidity position.</p>
            </div>
            ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
            <div id="fccCashOut"><p style="opacity:0.7;">Select period, then refresh.</p></div>
            <p class="fcc-gov-link"><a href="#" id="fccCashTreasury">Treasury movement detail →</a></p>
        </div>`;

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    FO.bindRefresh(load);
    document.getElementById('fccCashTreasury')?.addEventListener('click', (e) => {
        e.preventDefault();
        if (typeof loadPage === 'function') loadPage('finance', 'treasury');
    });

    async function load() {
        const out = document.getElementById('fccCashOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const p = FO.readFilterParams();
        try {
            const data = await API.financeCommandCenter.overview({
                from_date: p.since,
                to_date: p.until,
                branch_id: p.branch_id,
            });
            const s = data.position_strip || {};
            out.innerHTML = `
                <div class="fcc-strip">
                    <div class="fcc-card"><div class="fcc-card-label">Cash available</div><div class="fcc-card-value">${FO.fmtMoney(s.cash_available)}</div><div class="fcc-card-sub">Operational cashbook</div></div>
                    <div class="fcc-card"><div class="fcc-card-label">Cash (GL)</div><div class="fcc-card-value">${FO.fmtMoney(s.cash_gl)}</div><div class="fcc-card-sub">Posted general ledger</div></div>
                    <div class="fcc-card"><div class="fcc-card-label">Receivables</div><div class="fcc-card-value">${FO.fmtMoney(s.customer_receivables)}</div></div>
                    <div class="fcc-card"><div class="fcc-card-label">Payables</div><div class="fcc-card-value">${FO.fmtMoney(s.supplier_payables)}</div></div>
                    <div class="fcc-card ${s.net_liquidity_position >= 0 ? 'fcc-card--positive' : 'fcc-card--negative'}">
                        <div class="fcc-card-label">Net liquidity</div>
                        <div class="fcc-card-value">${FO.fmtMoney(s.net_liquidity_position)}</div>
                        <div class="fcc-card-sub">Cash + AR − AP</div>
                    </div>
                </div>`;
            out.innerHTML = out.innerHTML.replace(/<\/?motion\b/gi, (m) => m.replace(/motion/gi, 'div'));
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

window.renderFinanceCash = renderFinanceCash;
