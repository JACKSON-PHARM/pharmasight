// Revenue Recovery & Exposure Intelligence

async function renderFinanceRecovery() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    const range = FO.defaultDateRange();
    root.innerHTML = FO.pageShell(
        'Revenue Recovery & Exposure',
        'fa-hand-holding-usd',
        `
        <p style="margin:0 0 1rem;opacity:0.85;font-size:0.92rem;">
            Who owes you money, what is aging, and which payers delay settlement — from operational balances with lineage period context.
        </p>
        ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
        <div id="foRecoveryResult"><p style="opacity:0.7;">Select branch and period, then refresh.</p></div>
        `
    );

    const outEl = document.getElementById('foRecoveryResult');
    if (outEl && outEl.innerHTML.includes('</div>')) {
        outEl.innerHTML = outEl.innerHTML.replace('</div>', '</div>');
    }

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    FO.bindRefresh(loadRecovery);

    async function loadRecovery() {
        const out = document.getElementById('foRecoveryResult');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const p = FO.readFilterParams();
        try {
            const data = await API.financeOps.intelligence.recoveryExposure({
                branch_id: p.branch_id,
                since: p.since,
                until: p.until,
            });
            out.innerHTML = renderRecoveryView(data, FO, L);
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

function renderRecoveryView(data, FO, L) {
    const h = data.headline || {};
    const doctrine = data.branch_doctrine || {};
    const aging = (data.questions && data.questions.what_is_at_risk && data.questions.what_is_at_risk.aging_buckets) || {};
    const who = (data.questions && data.questions.who_owes_us) || {};
    const wholesale = who.wholesale_invoices || [];
    const retailCredit = who.retail_credit_invoices || [];
    const payers = (data.questions && data.questions.which_insurers_delay) || [];
    const arSum = data.lineage_period_summary && data.lineage_period_summary.ar_recognized_vs_collected;
    const isRetailCounter = doctrine.interpretation === 'retail_cash_first';

    const agingHtml = Object.keys(aging)
        .map(
            (k) =>
                `<div><span style="opacity:0.8;">${FO.escapeHtml(L.agingLabel(k))}</span>: <strong>${FO.fmtMoney(aging[k])}</strong></div>`
        )
        .join('');

    const retailRows = retailCredit
        .slice(0, 25)
        .map(
            (r) => `
        <tr>
            <td>${FO.escapeHtml(r.document_no || '—')}</td>
            <td>${FO.escapeHtml(r.customer_name || '—')}</td>
            <td>${FO.escapeHtml(L.agingLabel(r.aging_bucket))}</td>
            <td style="text-align:right;">${FO.fmtMoney(r.balance)}</td>
        </tr>`
        )
        .join('');

    const invRows = wholesale
        .slice(0, 25)
        .map(
            (r) => `
        <tr>
            <td>${FO.escapeHtml(r.document_no || '—')}</td>
            <td>${FO.escapeHtml(r.customer_name || '—')}</td>
            <td>${FO.escapeHtml(L.agingLabel(r.aging_bucket))}</td>
            <td style="text-align:right;">${FO.fmtMoney(r.balance)}</td>
        </tr>`
        )
        .join('');

    const payerRows = payers
        .slice(0, 10)
        .map(
            (p) => `
        <tr>
            <td>${FO.escapeHtml(p.payer_name || '—')}</td>
            <td style="text-align:right;">${FO.fmtMoney(p.outstanding)}</td>
        </tr>`
        )
        .join('');

    const doctrineNote = doctrine.label
        ? `<div style="margin-bottom:1rem;padding:0.75rem 1rem;border-radius:8px;border:1px solid var(--border-color);font-size:0.88rem;">Branch fiscal doctrine: <strong>${FO.escapeHtml(doctrine.label)}</strong>. ${isRetailCounter ? 'Retail counter is cash-first — empty wholesale AR is expected.' : ''}</div>`
        : '';
    const atRisk =
        (h.deteriorating_wholesale_count || 0) + (h.deteriorating_retail_credit_count || 0);

    return `
        ${doctrineNote}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1rem;">
            <div class="card" style="padding:1rem;border:1px solid var(--border-color);">
                <div style="font-size:0.8rem;opacity:0.75;">Outstanding receivables</div>
                <strong style="font-size:1.25rem;">${FO.fmtMoney(h.total_outstanding_receivables)}</strong>
            </div>
            <div class="card" style="padding:1rem;border:1px solid var(--border-color);">
                <div style="font-size:0.8rem;opacity:0.75;">Insurance exposure</div>
                <strong style="font-size:1.25rem;">${FO.fmtMoney(h.total_insurance_exposure)}</strong>
            </div>
            <div class="card" style="padding:1rem;border:1px solid var(--border-color);">
                <div style="font-size:0.8rem;opacity:0.75;">At-risk debt (61+ days)</div>
                <strong style="font-size:1.25rem;">${FO.escapeHtml(String(atRisk || 0))}</strong> invoices
            </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">
            <div><h4 style="margin:0 0 0.5rem;">Aging exposure</h4>${agingHtml || '<p style="opacity:0.7;">None</p>'}</div>
            <div>
                <h4 style="margin:0 0 0.5rem;">Period lineage (non-authoritative)</h4>
                <div>Recognized: <strong>${FO.fmtMoney(arSum && arSum.recognized_accrual)}</strong></div>
                <div>Collected: <strong>${FO.fmtMoney(arSum && arSum.collected_inflow)}</strong></div>
            </div>
        </div>
        <h4>Retail credit customers</h4>
        <table class="table" style="width:100%;font-size:0.9rem;margin-bottom:1rem;">
            <thead><tr><th>Invoice</th><th>Customer</th><th>Aging</th><th style="text-align:right;">Balance</th></tr></thead>
            <tbody>${retailRows || '<tr><td colspan="4">No open retail credit balances (typical for cash-first retail)</td></tr>'}</tbody>
        </table>
        <h4>Who owes us (wholesale credit)</h4>
        <table class="table" style="width:100%;font-size:0.9rem;margin-bottom:1rem;">
            <thead><tr><th>Invoice</th><th>Customer</th><th>Aging</th><th style="text-align:right;">Balance</th></tr></thead>
            <tbody>${invRows || '<tr><td colspan="4">No open wholesale balances</td></tr>'}</tbody>
        </table>
        <h4>Payer delay (insurance)</h4>
        <table class="table" style="width:100%;font-size:0.9rem;">
            <thead><tr><th>Payer</th><th style="text-align:right;">Outstanding</th></tr></thead>
            <tbody>${payerRows || '<tr><td colspan="2">No open insurance exposure</td></tr>'}</tbody>
        </table>
        <p style="margin-top:1rem;font-size:0.85rem;opacity:0.8;">
            <a href="#finance-events">Trace activity</a> ·
            <a href="#finance-treasury">Treasury intelligence</a>
        </p>`;
}

