// Replay & Integrity — emission failures and lineage checks

async function renderFinanceIntegrity() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    const range = FO.defaultDateRange();

    root.innerHTML = FO.pageShell(
        'Replay & Integrity',
        'fa-shield-alt',
        `
        ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: false })}
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;">
            <button type="button" class="btn btn-primary btn-sm" id="foCheckIntegrityBtn"><i class="fas fa-check-circle"></i> Check lineage integrity</button>
            <button type="button" class="btn btn-secondary btn-sm" id="foReplayAllBtn"><i class="fas fa-redo"></i> Replay unresolved failures</button>
        </div>
        <h4 style="margin:0 0 0.5rem;">Integrity findings</h4>
        <div id="foIntegrityFindings"><p style="opacity:0.7;font-size:0.9rem;">Run a check to scan for lineage issues.</p></div>
        <h4 style="margin:1.25rem 0 0.5rem;">Emission failures</h4>
        <div id="foEmissionFailures"><p style="opacity:0.7;">Loading…</p></div>
        `
    );

    await FO.populateBranchSelect(document.getElementById('foBranch'), CONFIG.BRANCH_ID);

    document.getElementById('foCheckIntegrityBtn')?.addEventListener('click', checkIntegrity);
    document.getElementById('foReplayAllBtn')?.addEventListener('click', replayAll);
    FO.bindRefresh(loadFailures);
    await loadFailures();

    async function checkIntegrity() {
        const el = document.getElementById('foIntegrityFindings');
        if (!el) return;
        el.innerHTML = '<p style="opacity:0.7;">Checking…</p>';
        const p = FO.readFilterParams();
        try {
            const findings = await API.financeOps.events.integrity({
                branch_id: p.branch_id,
                since: p.since,
            });
            if (!findings || findings.length === 0) {
                el.innerHTML = FO.statusPill('No integrity issues found in scope', 'ok');
                return;
            }
            el.innerHTML = `
                <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
                    <thead><tr><th style="text-align:left;padding:0.4rem 0.5rem;">Severity</th><th style="text-align:left;">Issue</th><th>Detail</th></tr></thead>
                    <tbody>${findings
                        .map(
                            (f) =>
                                `<tr>
                                    <td style="padding:0.4rem 0.5rem;">${FO.statusPill(f.severity || 'info', f.severity === 'error' ? 'err' : 'warn')}</td>
                                    <td style="padding:0.4rem 0.5rem;">${FO.escapeHtml(f.code || f.finding_type || '—')}</td>
                                    <td style="padding:0.4rem 0.5rem;font-size:0.85rem;">${FO.escapeHtml(f.message || f.detail || '')}</td>
                                </tr>`
                        )
                        .join('')}</tbody>
                </table>`;
        } catch (err) {
            FO.showError(el, err);
        }
    }

    async function loadFailures() {
        const el = document.getElementById('foEmissionFailures');
        if (!el) return;
        try {
            const rows = await API.financeOps.events.failures({ unresolved_only: true, limit: 50 });
            if (!rows || rows.length === 0) {
                el.innerHTML = '<p style="opacity:0.7;margin:0;">No unresolved emission failures.</p>';
                return;
            }
            el.innerHTML = `
                <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
                    <thead><tr><th>When</th><th>Activity</th><th>Source</th><th></th></tr></thead>
                    <tbody>${rows
                        .map(
                            (f) =>
                                `<tr>
                                    <td style="padding:0.4rem 0.5rem;">${FO.escapeHtml((f.created_at || '').slice(0, 16).replace('T', ' '))}</td>
                                    <td style="padding:0.4rem 0.5rem;">${FO.escapeHtml(L.eventLabel(f.event_type))}</td>
                                    <td style="padding:0.4rem 0.5rem;font-size:0.85rem;">${FO.escapeHtml(f.source_entity_type)}</td>
                                    <td style="padding:0.4rem 0.5rem;"><button type="button" class="btn btn-secondary btn-sm fo-replay-one" data-id="${FO.escapeHtml(f.id)}">Replay</button></td>
                                </tr>`
                        )
                        .join('')}</tbody>
                </table>`;
            el.querySelectorAll('.fo-replay-one').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    const id = btn.getAttribute('data-id');
                    try {
                        const res = await API.financeOps.events.replayFailure(id);
                        if (typeof showToast === 'function') showToast(res.message || res.result || 'Replayed', 'success');
                        await loadFailures();
                    } catch (e) {
                        if (typeof showToast === 'function') showToast((e && e.message) || 'Replay failed', 'error');
                    }
                });
            });
        } catch (err) {
            FO.showError(el, err);
        }
    }

    async function replayAll() {
        try {
            const outcomes = await API.financeOps.events.replayUnresolved({ limit: 50 });
            const n = Array.isArray(outcomes) ? outcomes.length : 0;
            if (typeof showToast === 'function') showToast(`Replay batch completed (${n} items)`, 'success');
            await loadFailures();
        } catch (e) {
            if (typeof showToast === 'function') showToast((e && e.message) || 'Batch replay failed', 'error');
        }
    }
}

window.renderFinanceIntegrity = renderFinanceIntegrity;
