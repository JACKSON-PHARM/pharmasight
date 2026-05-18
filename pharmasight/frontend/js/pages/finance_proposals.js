// Journal Proposal Inbox — generate → approve → post (interpretation only)

async function renderFinanceProposals() {
    const FO = window.FinanceOps;
    const L = window.FinanceOpsLabels;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.financeOps) return;

    root.innerHTML = FO.pageShell(
        'Journal Proposal Inbox',
        'fa-inbox',
        `
        <p style="margin:0 0 1rem;opacity:0.85;font-size:0.92rem;">Derived journal interpretations from financial activity. Approving and posting does not change operational records or stored GL balances.</p>
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;" id="foProposalTabs">
            <button type="button" class="btn btn-secondary btn-sm fo-prop-tab active" data-status="">All</button>
            <button type="button" class="btn btn-secondary btn-sm fo-prop-tab" data-status="draft">Draft</button>
            <button type="button" class="btn btn-secondary btn-sm fo-prop-tab" data-status="approved">Approved</button>
            <button type="button" class="btn btn-secondary btn-sm fo-prop-tab" data-status="posted">Posted</button>
        </div>
        <div id="foProposalsTable"><p style="opacity:0.7;">Loading proposals…</p></div>
        <div id="foProposalDetail" style="display:none;margin-top:1rem;"></div>
        `
    );

    let statusFilter = '';
    document.querySelectorAll('.fo-prop-tab').forEach((btn) => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.fo-prop-tab').forEach((b) => b.classList.remove('active'));
            btn.classList.add('active');
            statusFilter = btn.getAttribute('data-status') || '';
            loadProposals();
        });
    });

    await loadProposals();

    async function loadProposals() {
        const tableEl = document.getElementById('foProposalsTable');
        const detailEl = document.getElementById('foProposalDetail');
        if (!tableEl) return;
        if (detailEl) detailEl.style.display = 'none';
        tableEl.innerHTML = '<p style="opacity:0.7;">Loading…</p>';

        try {
            const rows = await API.financeOps.accounting.listProposals({
                status: statusFilter || undefined,
                branch_id: CONFIG.BRANCH_ID,
                limit: 100,
            });
            if (!rows || rows.length === 0) {
                tableEl.innerHTML =
                    '<p style="opacity:0.7;margin:0;">No proposals yet. Open the Event Explorer and generate a proposal from an eligible activity.</p>';
                return;
            }
            const body = rows
                .map((p) => {
                    const st = (p.status || '').toLowerCase();
                    const tone =
                        st === 'posted' ? 'ok' : st === 'approved' ? 'info' : st === 'draft' ? 'warn' : 'muted';
                    return `<tr data-proposal-id="${FO.escapeHtml(p.id)}" style="cursor:pointer;">
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml(p.proposal_number || p.id.slice(0, 8))}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.statusPill(L.proposalStatusLabel(p.status), tone)}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);text-align:right;">${FO.fmtMoney(p.total_amount, p.currency_code)}</td>
                        <td style="padding:0.6rem 0.75rem;border-bottom:1px solid var(--border-color);">${FO.escapeHtml((p.occurred_at || '').slice(0, 10))}</td>
                    </tr>`;
                })
                .join('');
            tableEl.innerHTML = `
                <table style="width:100%;border-collapse:collapse;">
                    <thead><tr><th style="text-align:left;padding:0.5rem 0.75rem;">Proposal</th><th style="text-align:left;">Status</th><th style="text-align:right;">Amount</th><th style="text-align:left;">Date</th></tr></thead>
                    <tbody>${body}</tbody>
                </table>`;
            tableEl.querySelectorAll('tr[data-proposal-id]').forEach((tr) => {
                tr.addEventListener('click', () => openProposal(tr.getAttribute('data-proposal-id')));
            });
        } catch (err) {
            FO.showError(tableEl, err);
        }
    }

    async function openProposal(proposalId) {
        const detailEl = document.getElementById('foProposalDetail');
        if (!detailEl) return;
        detailEl.style.display = 'block';
        detailEl.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        try {
            const p = await API.financeOps.accounting.getProposal(proposalId);
            const lines = (p.lines || [])
                .map(
                    (ln) =>
                        `<tr>
                            <td style="padding:0.35rem 0.5rem;">${FO.escapeHtml(ln.account_semantic || '—')}</td>
                            <td style="padding:0.35rem 0.5rem;">${FO.escapeHtml(ln.line_direction || '—')}</td>
                            <td style="padding:0.35rem 0.5rem;text-align:right;">${FO.fmtMoney(ln.amount, p.currency_code)}</td>
                            <td style="padding:0.35rem 0.5rem;font-size:0.85rem;">${FO.escapeHtml(ln.description || '')}</td>
                        </tr>`
                )
                .join('');
            const st = (p.status || '').toLowerCase();
            let actions = '';
            if (st === 'draft') {
                actions = `<button type="button" class="btn btn-primary btn-sm" id="foApproveBtn">Approve</button>`;
            } else if (st === 'approved') {
                actions = `<button type="button" class="btn btn-primary btn-sm" id="foPostBtn">Post</button>`;
            } else if (st === 'posted') {
                actions = `<button type="button" class="btn btn-secondary btn-sm" id="foReverseBtn">Create reversal proposal</button>`;
            }

            detailEl.innerHTML = `
                <div class="card" style="border:1px solid var(--border-color);">
                    <div class="card-body">
                        <h4 style="margin:0 0 0.5rem;">${FO.escapeHtml(p.proposal_number || 'Proposal')} ${FO.statusPill(L.proposalStatusLabel(p.status), st === 'posted' ? 'ok' : 'info')}</h4>
                        <p style="font-size:0.88rem;margin:0 0 0.75rem;">Source activity: <code style="font-size:0.8rem;">${FO.escapeHtml(p.source_financial_event_id || '—')}</code></p>
                        ${lines ? `<table style="width:100%;margin-bottom:0.75rem;"><thead><tr><th>Account interpretation</th><th>Direction</th><th style="text-align:right;">Amount</th><th>Note</th></tr></thead><tbody>${lines}</tbody></table>` : ''}
                        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">${actions}</div>
                    </div>
                </div>`;

            const approveBtn = document.getElementById('foApproveBtn');
            const postBtn = document.getElementById('foPostBtn');
            const reverseBtn = document.getElementById('foReverseBtn');
            if (approveBtn) {
                approveBtn.onclick = () => act(() => API.financeOps.accounting.approve(proposalId));
            }
            if (postBtn) {
                postBtn.onclick = () => act(() => API.financeOps.accounting.post(proposalId));
            }
            if (reverseBtn) {
                reverseBtn.onclick = () => act(() => API.financeOps.accounting.reverse(proposalId));
            }

            async function act(fn) {
                try {
                    const res = await fn();
                    if (typeof showToast === 'function') showToast(res.message || 'Done', 'success');
                    await loadProposals();
                    await openProposal(proposalId);
                } catch (e) {
                    if (typeof showToast === 'function') showToast((e && e.message) || 'Action failed', 'error');
                }
            }
        } catch (err) {
            FO.showError(detailEl, err);
        }
    }
}

window.renderFinanceProposals = renderFinanceProposals;
