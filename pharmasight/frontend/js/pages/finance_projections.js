// Projection Explorer — lineage-derived movement & exposure (Stage 1)

async function renderFinanceProjections() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    const range = FO.defaultDateRange();
    let catalog = [];

    try {
        const reg = await API.financeOps.projections.registry();
        catalog = (reg && reg.projections) || [];
    } catch (_) {}

    const options = catalog
        .map((p) => {
            const id = p.projection_id || p.id;
            const title = p.title || L.projectionLabel(id);
            return `<option value="${FO.escapeHtml(id)}">${FO.escapeHtml(title)}</option>`;
        })
        .join('');

    root.innerHTML = FO.pageShell(
        'Projection Explorer',
        'fa-chart-area',
        `
        <p style="margin:0 0 1rem;opacity:0.85;font-size:0.92rem;">Period movement and exposure derived from financial activity — not stored balances. Use alongside Legacy Reports during validation.</p>
        <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:end;margin-bottom:1rem;">
            <div class="form-group" style="margin:0;min-width:220px;">
                <label class="form-label">Projection</label>
                <select class="form-select" id="foProjectionId">${options || '<option value="">No projections available</option>'}</select>
            </div>
            <div class="form-group" style="margin:0;min-width:200px;">
                <label class="form-label">Branch</label>
                <select class="form-select" id="foBranch">${FO.escapeHtml(CONFIG.BRANCH_ID || '')}</select>
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label">From</label>
                <input type="date" class="form-input" id="foDateFrom" value="${FO.escapeHtml(range.since)}">
            </div>
            <div class="form-group" style="margin:0;">
                <label class="form-label">To</label>
                <input type="date" class="form-input" id="foDateTo" value="${FO.escapeHtml(range.until)}">
            </div>
            <button type="button" class="btn btn-primary" id="foRunProjectionBtn"><i class="fas fa-play"></i> Run projection</button>
        </div>
        <div id="foProjectionResult"><p style="opacity:0.7;">Select a projection and run.</p></div>
        `
    );

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    const runBtn = document.getElementById('foRunProjectionBtn');
    if (runBtn) runBtn.onclick = runProjection;

    async function runProjection() {
        const out = document.getElementById('foProjectionResult');
        const sel = document.getElementById('foProjectionId');
        const pid = sel && sel.value;
        if (!out || !pid) return;
        out.innerHTML = '<p style="opacity:0.7;">Running…</p>';
        const branch_id = document.getElementById('foBranch')?.value || CONFIG.BRANCH_ID;
        const since = document.getElementById('foDateFrom')?.value;
        const until = document.getElementById('foDateTo')?.value;
        try {
            const res = await API.financeOps.projections.run(pid, { branch_id, since, until });
            const data = res.data || {};
            const freshness = data.freshness || {};
            const contract = data.contract || {};
            const summaryPairs = FO.summarizeProjectionData(data);
            const summaryTable =
                summaryPairs.length > 0
                    ? FO.renderKeyValueTable(
                          summaryPairs.reduce((acc, [label, key, val]) => {
                              acc[key] = val;
                              return acc;
                          }, {}),
                          summaryPairs.map(([label, key]) => [label, key])
                      )
                    : '<p style="opacity:0.7;">No movement figures in this result.</p>';

            out.innerHTML = `
                <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;">
                    ${FO.statusPill('Derived view', 'info')}
                    ${FO.statusPill('Not authoritative', 'muted')}
                    ${freshness.staleness ? FO.statusPill(`Freshness: ${freshness.staleness}`, 'ok') : ''}
                </div>
                ${data.disclaimer ? `<p style="font-size:0.88rem;margin:0 0 0.75rem;">${FO.escapeHtml(data.disclaimer)}</p>` : ''}
                <h4 style="margin:0 0 0.5rem;">${FO.escapeHtml(L.projectionLabel(pid))}</h4>
                ${summaryTable}
                <details style="margin-top:1rem;font-size:0.85rem;">
                    <summary style="cursor:pointer;">Replay & contract metadata</summary>
                    <pre style="white-space:pre-wrap;font-size:0.78rem;margin:0.5rem 0 0;">${FO.escapeHtml(JSON.stringify({ freshness, contract }, null, 2))}</pre>
                </details>`;
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

window.renderFinanceProjections = renderFinanceProjections;
