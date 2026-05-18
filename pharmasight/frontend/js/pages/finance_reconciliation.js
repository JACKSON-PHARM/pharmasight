// Stage 2A / 2A.5 — Treasury Movement Reconciliation (coverage intelligence)

async function renderFinanceReconciliation() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    const range = FO.defaultDateRange();

    root.innerHTML = FO.pageShell(
        'Treasury Intelligence',
        'fa-wallet',
        `
        <p style="margin:0 0 1rem;opacity:0.85;font-size:0.92rem;">
            Branch liquidity and cash-movement health from governed lineage, with legacy cashbook as compatibility reference.
            Drift and coverage explain governance maturity — not “the projection is wrong.”
        </p>
        ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
        <button type="button" class="btn btn-primary" id="foRunReconcileBtn" style="margin-bottom:1rem;">
            <i class="fas fa-balance-scale"></i> Run reconciliation
        </button>
        <div id="foReconcileResult"><p style="opacity:0.7;">Select period and branch, then run reconciliation.</p></div>
        `
    );

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);
    document.getElementById('foRunReconcileBtn')?.addEventListener('click', runReconciliation);
    FO.bindRefresh(runReconciliation);

    async function runReconciliation() {
        const out = document.getElementById('foReconcileResult');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Reconciling…</p>';
        const p = FO.readFilterParams();
        try {
            const data = await API.financeOps.reconciliation.treasuryMovement({
                branch_id: p.branch_id,
                since: p.since,
                until: p.until,
            });
            out.innerHTML = renderReconciliationView(data, FO, L);
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

function renderReconciliationView(data, FO, L) {
    const legacy = data.legacy_cashbook || {};
    const proj = data.lineage_projection || {};
    const cmp = data.comparison || {};
    const gov = data.governance || {};
    const legSum = cmp.legitimacy_summary || {};
    const aligned = cmp.totals_aligned === true;
    const bypass = cmp.active_bypass_count || 0;

    const verdictTone = bypass > 0 ? 'err' : aligned ? 'ok' : 'warn';
    const verdictLabel = bypass > 0
        ? 'Critical: active bypasses'
        : aligned
          ? 'Totals aligned'
          : 'Coverage gap (expected)';

    const summaryCards = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:1rem;">
            <div class="card" style="border:1px solid var(--border-color);padding:1rem;">
                <div style="font-size:0.8rem;opacity:0.75;margin-bottom:0.35rem;">Legacy Cashbook (observational)</div>
                <div>In: <strong>${FO.fmtMoney(legacy.total_inflow)}</strong></div>
                <div>Out: <strong>${FO.fmtMoney(legacy.total_outflow)}</strong></div>
                <div>Net: <strong>${FO.fmtMoney(legacy.net_movement)}</strong></div>
                <div style="font-size:0.8rem;margin-top:0.35rem;opacity:0.7;">${legacy.entry_count || 0} entries</div>
            </div>
            <div class="card" style="border:1px solid var(--border-color);padding:1rem;">
                <div style="font-size:0.8rem;opacity:0.75;margin-bottom:0.35rem;">Lineage projection (governed)</div>
                <div>In: <strong>${FO.fmtMoney(proj.total_inflow)}</strong></div>
                <div>Out: <strong>${FO.fmtMoney(proj.total_outflow)}</strong></div>
                <div>Net: <strong>${FO.fmtMoney(proj.net_movement)}</strong></div>
                <div style="font-size:0.8rem;margin-top:0.35rem;opacity:0.7;">${proj.event_count || 0} events · coverage ${cmp.lineage_coverage_ratio != null ? (cmp.lineage_coverage_ratio * 100).toFixed(1) + '%' : '—'}</div>
            </div>
            <div class="card" style="border:1px solid var(--border-color);padding:1rem;">
                <div style="font-size:0.8rem;opacity:0.75;margin-bottom:0.35rem;">Governance</div>
                ${FO.statusPill(verdictLabel, verdictTone)}
                <div style="font-size:0.82rem;margin-top:0.5rem;opacity:0.85;">
                    Start: ${FO.escapeHtml(gov.governance_start_date || 'not yet emitted')}<br>
                    Matched: ${cmp.matched_entry_count || 0} / ${cmp.cashbook_entry_count || 0}
                </div>
            </div>
        </div>`;

    const legitimacyPills = Object.keys(legSum)
        .map((k) => {
            const tone =
                k === 'active_operational_bypass'
                    ? 'err'
                    : k === 'historical_legacy_record' || k === 'backfill_eligible'
                      ? 'info'
                      : k === 'replay_pending'
                        ? 'warn'
                        : 'muted';
            return FO.statusPill(`${L.legitimacyLabel(k)}: ${legSum[k]}`, tone);
        })
        .join(' ');

    const items = data.drift_items || [];
    const driftTable =
        items.length === 0
            ? '<p style="opacity:0.7;margin:0;">No entry-level drift in scope.</p>'
            : `<div style="overflow-x:auto;">
                <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
                    <thead><tr>
                        <th style="text-align:left;padding:0.45rem 0.5rem;">Classification</th>
                        <th style="text-align:left;">Module</th>
                        <th style="text-align:left;">Workflow</th>
                        <th style="text-align:left;">Document</th>
                        <th style="text-align:left;">Recommended action</th>
                        <th style="text-align:right;">Amount</th>
                    </tr></thead>
                    <tbody>${items
                        .map((d) => {
                            const leg = d.legitimacy || {};
                            const attr = d.attribution || {};
                            const sev =
                                leg.severity === 'error' || d.severity === 'error'
                                    ? 'err'
                                    : leg.severity === 'warning' || d.severity === 'warning'
                                      ? 'warn'
                                      : 'muted';
                            const cat =
                                leg.category_label ||
                                L.legitimacyLabel(leg.category) ||
                                L.driftLabel(d.drift_type);
                            const action =
                                leg.recommended_action ||
                                (d.detail && d.detail.recommended_action) ||
                                '—';
                            return `<tr>
                                <td style="padding:0.4rem 0.5rem;border-bottom:1px solid var(--border-color);">${FO.statusPill(cat, sev)}</td>
                                <td style="padding:0.4rem 0.5rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml(attr.operational_module || '—')}</td>
                                <td style="padding:0.4rem 0.5rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml(attr.workflow_label || '—')}</td>
                                <td style="padding:0.4rem 0.5rem;border-bottom:1px solid var(--border-color);font-size:0.82rem;">${FO.escapeHtml(attr.document_reference || attr.cashbook_reference || '—')}</td>
                                <td style="padding:0.4rem 0.5rem;border-bottom:1px solid var(--border-color);font-size:0.8rem;max-width:240px;">${FO.escapeHtml(action)}</td>
                                <td style="padding:0.4rem 0.5rem;border-bottom:1px solid var(--border-color);text-align:right;">${FO.escapeHtml(d.cashbook_amount || d.lineage_amount || '—')}</td>
                            </tr>`;
                        })
                        .join('')}</tbody>
                </table>
            </div>`;

    const truncNote = cmp.drift_truncated
        ? `<p style="font-size:0.8rem;opacity:0.75;">Showing first ${cmp.drift_display_limit || 300} rows by severity. Summary counts reflect all entries.</p>`
        : '';

    return `
        ${summaryCards}
        <div style="padding:0.75rem 1rem;border-radius:8px;background:var(--surface-alt,rgba(59,130,246,0.06));border:1px solid var(--border-color);margin-bottom:1rem;font-size:0.9rem;line-height:1.45;">
            ${FO.escapeHtml(cmp.period_interpretation || '')}
        </div>
        <h4 style="margin:0 0 0.5rem;">Coverage breakdown</h4>
        <div style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:0.35rem;">${legitimacyPills || FO.statusPill('No drift', 'ok')}</div>
        <h4 style="margin:0 0 0.5rem;">Drift detail</h4>
        ${driftTable}
        ${truncNote}
        <p style="font-size:0.8rem;opacity:0.75;margin:1rem 0 0;">
            Legacy cashbook is observational reference only. Run controlled backfill to materialize lineage — do not treat cashbook as authoritative when totals diverge.
        </p>
        <p style="margin:0.5rem 0 0;">
            <a href="#cashbook" class="btn btn-link btn-sm">Legacy Cashbook</a>
            <a href="#finance-integrity" class="btn btn-link btn-sm">Replay &amp; Integrity</a>
            <a href="#finance-projections" class="btn btn-link btn-sm">Projection Explorer</a>
        </p>`;
}

window.renderFinanceReconciliation = renderFinanceReconciliation;
