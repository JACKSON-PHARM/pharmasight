// GL Reconciliation — control accounts vs subledgers

async function renderFinanceGlReconciliation() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.accountingGl) return;

    const today = FO.localDateStr();
    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-balance-scale"></i> Reconciliation</h2>
                <p>GL control accounts matched to operational subledgers (AR, AP, cash, VAT).</p>
            </div>
            <div class="fcc-toolbar">
                <div class="form-group">
                    <label class="form-label">Branch</label>
                    <select class="form-select" id="foBranch"></select>
                </div>
                <div class="form-group">
                    <label class="form-label">As of</label>
                    <input type="date" class="form-input" id="foAsOf" value="${FO.escapeHtml(today)}">
                </div>
                <button type="button" class="btn btn-primary" id="foRefreshBtn"><i class="fas fa-sync-alt"></i> Refresh</button>
            </div>
            <div id="fccReconOut"><p style="opacity:0.7;">Select branch and date, then refresh.</p></div>
        </div>`;
    root.innerHTML = root.innerHTML.replace(/<\/?motion\b/gi, (m) => m.replace(/motion/gi, 'div'));

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    document.getElementById('foRefreshBtn').onclick = load;

    async function load() {
        const out = document.getElementById('fccReconOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const branchId = document.getElementById('foBranch')?.value || CONFIG.BRANCH_ID;
        const asOf = document.getElementById('foAsOf')?.value || today;
        try {
            const data = await API.accountingGl.controlReconciliation({
                as_of_date: asOf,
                branch_id: branchId,
            });
            const controls = data.controls || [];
            const status = data.overall_status || 'unknown';
            out.innerHTML = `
                <p style="margin-bottom:0.75rem;">Overall: ${FO.statusPill(status, status === 'matched' ? 'ok' : 'warn')}</p>
                <table class="fcc-table">
                    <thead><tr>
                        <th>Control</th><th class="num">Subledger</th><th class="num">GL</th><th class="num">Delta</th><th>Status</th>
                    </tr></thead>
                    <tbody>
                    ${controls
                        .map(
                            (c) => `<tr>
                        <td>${FO.escapeHtml(c.label || c.control_role)}</td>
                        <td class="num">${FO.fmtMoney(c.subledger_balance)}</td>
                        <td class="num">${FO.fmtMoney(c.gl_balance)}</td>
                        <td class="num">${FO.fmtMoney(c.delta)}</td>
                        <td>${FO.statusPill(c.status, c.status === 'matched' ? 'ok' : 'warn')}</td>
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

window.renderFinanceGlReconciliation = renderFinanceGlReconciliation;
