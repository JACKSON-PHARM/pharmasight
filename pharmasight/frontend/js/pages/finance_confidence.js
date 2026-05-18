// Branch Financial Confidence — progressive authority gate

async function renderFinanceConfidence() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    const range = FO.defaultDateRange();
    root.innerHTML = FO.pageShell(
        'Financial Confidence',
        'fa-chart-line',
        `
        <p style="margin:0 0 1rem;opacity:0.85;font-size:0.92rem;">
            How mature governed finance is for this branch. Authority increases progressively — projections are never globally authoritative.
        </p>
        ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
        <div id="foConfidenceResult"><p style="opacity:0.7;">Select branch and period, then refresh.</p></div>
        `
    );

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    FO.bindRefresh(loadConfidence);

    async function loadConfidence() {
        const out = document.getElementById('foConfidenceResult');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Assessing…</p>';
        const p = FO.readFilterParams();
        try {
            const data = await API.financeOps.intelligence.branchConfidence({
                branch_id: p.branch_id,
                since: p.since,
                until: p.until,
            });
            out.innerHTML = renderConfidenceView(data, FO, L);
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

function renderConfidenceView(data, FO, L) {
    const level = data.authority_level || 'reconciliation_only';
    const tone =
        level === 'projection_trusted'
            ? 'ok'
            : level === 'projection_assisted'
              ? 'info'
              : level === 'shadow'
                ? 'warn'
                : 'muted';
    const caps = data.authority_capabilities || {};
    const signals = data.signals || [];
    const snap = data.governance_snapshot || {};

    const capRows = Object.entries(caps)
        .map(
            ([k, v]) =>
                `<li>${FO.escapeHtml(k.replace(/_/g, ' '))}: <strong>${v ? 'yes' : 'no'}</strong></li>`
        )
        .join('');

    function formatSignalValue(s) {
        const v = s.value;
        if (s.signal_id === 'cashbook_match_rate' && v && typeof v === 'object') {
            return `${FO.escapeHtml(String(v.matched_rows ?? '—'))} / ${FO.escapeHtml(String(v.cashbook_rows ?? '—'))} rows (${FO.escapeHtml(String(v.pct ?? '—'))}%)`;
        }
        if (s.signal_id === 'lineage_coverage' && v != null) {
            return `${FO.escapeHtml(String(Math.round(Number(v) * 1000) / 10))}% event volume vs cashbook`;
        }
        if (typeof v === 'object') return FO.escapeHtml(JSON.stringify(v));
        return FO.escapeHtml(String(v ?? '—'));
    }

    const driftByType = snap.drift_by_type || {};
    const driftPills = Object.keys(driftByType)
        .map((k) => `${FO.escapeHtml(L.driftLabel(k))}: ${driftByType[k]}`)
        .join(' · ');

    const signalRows = signals
        .map(
            (s) => `
        <tr>
            <td style="padding:0.5rem 0.75rem;">${FO.escapeHtml(s.label)}</td>
            <td style="padding:0.5rem 0.75rem;">${FO.escapeHtml(String(s.score))} / ${FO.escapeHtml(String(s.max_score))}<br><span style="font-size:0.8rem;opacity:0.8;">${formatSignalValue(s)}</span></td>
            <td style="padding:0.5rem 0.75rem;font-size:0.88rem;opacity:0.9;">${FO.escapeHtml(s.explanation)}</td>
        </tr>`
        )
        .join('');

    return `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem;margin-bottom:1rem;">
            <div class="card" style="border:1px solid var(--border-color);padding:1rem;">
                <div style="font-size:0.8rem;opacity:0.75;">Confidence score</div>
                <div style="font-size:2rem;font-weight:700;">${FO.escapeHtml(String(data.confidence_score ?? '—'))}</div>
            </div>
            <div class="card" style="border:1px solid var(--border-color);padding:1rem;">
                <div style="font-size:0.8rem;opacity:0.75;">Authority level</div>
                <div style="margin-top:0.35rem;">${FO.statusPill(L.authorityLevelLabel(level), tone)}</div>
            </div>
        </div>
        <div style="margin-bottom:1rem;font-size:0.9rem;">
            <strong>What this branch may use:</strong>
            <ul style="margin:0.5rem 0 0 1.1rem;">${capRows}</ul>
        </div>
        <div style="margin-bottom:1rem;font-size:0.88rem;opacity:0.85;">
            Strict matches: <strong>${snap.matched_entry_count ?? '—'}</strong> / ${snap.cashbook_entry_count ?? 0} cashbook rows ·
            Lineage events in period: <strong>${snap.lineage_event_count ?? 0}</strong> ·
            Replay backlog: <strong>${snap.replay_backlog ?? 0}</strong>
            ${driftPills ? `<div style="display:block;margin-top:0.35rem;">Drift breakdown: ${driftPills}</div>` : ''}
            <div style="display:block;margin-top:0.35rem;">
                <a href="#finance-treasury">Treasury intelligence</a> ·
                <a href="#finance-events">Trace lineage (governance)</a>
            </div>
        </div>
        <table class="table" style="width:100%;font-size:0.9rem;">
            <thead><tr><th>Signal</th><th>Score</th><th>Meaning</th></tr></thead>
            <tbody>${signalRows || '<tr><td colspan="3">No signals</td></tr>'}</tbody>
        </table>`;
}
