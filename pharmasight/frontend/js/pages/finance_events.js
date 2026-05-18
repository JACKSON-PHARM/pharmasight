// Financial Event Explorer — lineage observability (Stage 1)

async function renderFinanceEvents() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    const range = FO.defaultDateRange();
    let registryTypes = [];

    try {
        const reg = await API.financeOps.events.registry();
        registryTypes = (reg && reg.events) || [];
    } catch (_) {}

    const typeOptions = registryTypes.map((e) => ({
        value: e.event_type,
        label: L.eventLabel(e.event_type),
    }));

    root.innerHTML = FO.pageShell(
        'Financial Event Explorer',
        'fa-stream',
        `
        ${FO.filterToolbarHtml({ since: range.since, until: range.until, showEventType: true, eventTypeOptions: typeOptions })}
        <div id="foEventsTable"><p style="opacity:0.7;">Loading financial activity…</p></div>
        <div id="foEventDetail" style="display:none;margin-top:1.25rem;"></div>
        `
    );

    const branchSel = document.getElementById('foBranch');
    await FO.populateBranchSelect(branchSel, CONFIG.BRANCH_ID);
    FO.bindRefresh(loadEventsList);
    await loadEventsList();

    async function loadEventsList() {
        const tableEl = document.getElementById('foEventsTable');
        if (!tableEl) return;
        tableEl.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        const detailEl = document.getElementById('foEventDetail');
        if (detailEl) detailEl.style.display = 'none';

        const p = FO.readFilterParams();
        try {
            const rows = await API.financeOps.events.list({
                branch_id: p.branch_id,
                event_type: p.event_type || undefined,
                occurred_from: p.since,
                occurred_to: p.until,
                limit: 100,
            });
            if (!rows || rows.length === 0) {
                tableEl.innerHTML =
                    '<p style="opacity:0.7;margin:0;">No financial activity in this period. Post sales, payments, expenses, or insurance activity to emit events.</p>';
                return;
            }
            const body = rows
                .map((ev) => {
                    const id = ev.id;
                    const amtClass =
                        ev.economic_direction === 'inflow' || ev.economic_direction === 'reduction'
                            ? 'ok'
                            : ev.economic_direction === 'outflow' || ev.economic_direction === 'accrual'
                              ? 'info'
                              : 'muted';
                    return `<tr data-event-id="${FO.escapeHtml(id)}" style="cursor:pointer;">
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml((ev.occurred_at || '').slice(0, 16).replace('T', ' '))}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml(L.eventLabel(ev.event_type))}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml(L.domainLabel(ev.operational_domain))}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);text-align:right;">${FO.fmtMoney(ev.amount, ev.currency_code)}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.statusPill(L.directionLabel(ev.economic_direction), amtClass)}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);font-size:0.85rem;">${FO.escapeHtml(ev.source_reference || L.sourceEntityLabel(ev.source_entity_type))}</td>
                    </tr>`;
                })
                .join('');
            tableEl.innerHTML = `
                <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;font-size:0.92rem;">
                        <thead><tr style="text-align:left;">
                            <th style="padding:0.5rem 0.75rem;">When</th>
                            <th style="padding:0.5rem 0.75rem;">Activity</th>
                            <th style="padding:0.5rem 0.75rem;">Module</th>
                            <th style="padding:0.5rem 0.75rem;text-align:right;">Amount</th>
                            <th style="padding:0.5rem 0.75rem;">Movement</th>
                            <th style="padding:0.5rem 0.75rem;">Reference</th>
                        </tr></thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
                <p style="font-size:0.8rem;opacity:0.75;margin:0.75rem 0 0;">Showing up to 100 events. Select a row for lineage, settlements, and posting eligibility.</p>`;

            tableEl.querySelectorAll('tr[data-event-id]').forEach((tr) => {
                tr.addEventListener('click', () => openEventDetail(tr.getAttribute('data-event-id')));
            });
        } catch (err) {
            FO.showError(tableEl, err);
        }
    }

    async function openEventDetail(eventId) {
        const detailEl = document.getElementById('foEventDetail');
        if (!detailEl || !eventId) return;
        detailEl.style.display = 'block';
        detailEl.innerHTML = '<p style="opacity:0.7;">Loading details…</p>';

        try {
            const lineage = await API.financeOps.events.get(eventId);
            const ev = lineage.event;
            const settles = (lineage.settlement_links && lineage.settlement_links.as_settlement) || [];
            const settledBy = (lineage.settlement_links && lineage.settlement_links.settled_by) || [];

            let eligibilityHtml = '';
            try {
                const elig = await API.financeOps.accounting.eligibility(eventId, false);
                const tone = elig.eligible ? 'ok' : 'warn';
                eligibilityHtml = `
                    <div style="margin-top:0.75rem;">
                        <strong>Journal posting</strong>
                        ${FO.statusPill(elig.eligible ? 'Eligible for proposal' : 'Not eligible', tone)}
                        ${elig.reasons && elig.reasons.length ? `<ul style="margin:0.35rem 0 0 1rem;font-size:0.88rem;">${elig.reasons.map((r) => `<li>${FO.escapeHtml(r)}</li>`).join('')}</ul>` : ''}
                        <div style="margin-top:0.5rem;">
                            <button type="button" class="btn btn-secondary btn-sm" id="foGenProposalBtn"><i class="fas fa-file-alt"></i> Generate journal proposal</button>
                            <a href="#finance-proposals" class="btn btn-link btn-sm" style="margin-left:0.5rem;">Open proposal inbox</a>
                        </div>
                    </div>`;
            } catch (eligErr) {
                eligibilityHtml = `<p style="font-size:0.88rem;opacity:0.8;margin-top:0.5rem;">Posting eligibility: ${FO.escapeHtml((eligErr && eligErr.message) || 'unavailable (permission or event state)')}</p>`;
            }

            const settlementRows = [...settles, ...settledBy]
                .map(
                    (sl) =>
                        `<tr>
                            <td style="padding:0.35rem 0.5rem;">${FO.escapeHtml(L.settlementSemanticLabel(sl.settlement_semantic))}</td>
                            <td style="padding:0.35rem 0.5rem;text-align:right;">${FO.fmtMoney(sl.amount_settled)}</td>
                        </tr>`
                )
                .join('');

            detailEl.innerHTML = `
                <div class="card" style="border:1px solid var(--border-color);">
                    <div class="card-header"><h4 style="margin:0;">${FO.escapeHtml(L.eventLabel(ev.event_type))}</h4></div>
                    <div class="card-body">
                        ${FO.renderKeyValueTable(ev, [
                            ['When', 'occurred_at'],
                            ['Amount', 'amount'],
                            ['Module', 'operational_domain'],
                            ['Source', 'source_entity_type'],
                            ['Reference', 'source_reference'],
                            ['Status', 'operational_status'],
                        ])}
                        ${settlementRows ? `<h5 style="margin:1rem 0 0.35rem;">Applied payments & settlements</h5>
                            <table style="width:100%;"><tbody>${settlementRows}</tbody></table>` : ''}
                        ${lineage.reversals && lineage.reversals.length ? `<p style="margin-top:0.75rem;font-size:0.88rem;"><strong>Related reversals:</strong> ${lineage.reversals.length}</p>` : ''}
                        ${eligibilityHtml}
                        <details style="margin-top:1rem;font-size:0.85rem;">
                            <summary style="cursor:pointer;">Technical reference (for auditors)</summary>
                            <pre style="white-space:pre-wrap;margin:0.5rem 0 0;font-size:0.78rem;opacity:0.9;">${FO.escapeHtml(JSON.stringify({ id: ev.id, event_type: ev.event_type, idempotency_key: ev.idempotency_key }, null, 2))}</pre>
                        </details>
                    </div>
                </div>`;

            const genBtn = document.getElementById('foGenProposalBtn');
            if (genBtn) {
                genBtn.onclick = async () => {
                    try {
                        const res = await API.financeOps.accounting.generate({ financial_event_id: eventId });
                        if (typeof showToast === 'function') showToast(res.message || 'Proposal created', 'success');
                        window.location.hash = '#finance-proposals';
                        if (typeof window.loadFinance === 'function') window.loadFinance('proposals');
                    } catch (e) {
                        if (typeof showToast === 'function') showToast((e && e.message) || 'Failed to generate proposal', 'error');
                    }
                };
            }
        } catch (err) {
            FO.showError(detailEl, err);
        }
    }
}

window.renderFinanceEvents = renderFinanceEvents;
