// Posting failures — unresolved GL posting issues

async function renderFinancePostingFailures() {
    const FO = window.FinanceOps;
    const root = document.getElementById('financeContent');
    if (!root || !FO || !API || !API.accountingGl) return;

    root.innerHTML = `
        <div class="fcc-scope">
            <div class="fcc-hero">
                <h2><i class="fas fa-exclamation-triangle"></i> Posting failures</h2>
                <p>Operations that failed to post to the general ledger — resolve before period close.</p>
            </div>
            <div class="fcc-toolbar">
                <button type="button" class="btn btn-primary" id="foRefreshBtn"><i class="fas fa-sync-alt"></i> Refresh</button>
            </div>
            <div id="fccFailuresOut"><p style="opacity:0.7;">Loading…</p></div>
        </div>`;

    document.getElementById('foRefreshBtn').onclick = load;
    await load();

    async function load() {
        const out = document.getElementById('fccFailuresOut');
        if (!out) return;
        out.innerHTML = '<p style="opacity:0.7;">Loading…</p>';
        try {
            const data = await API.accountingGl.postingFailures({ unresolved_only: true, limit: 100 });
            const items = data.items || data.failures || [];
            if (!items.length) {
                out.innerHTML = '<p style="opacity:0.7;">No unresolved posting failures.</p>';
                return;
            }
            out.innerHTML = `
                <table class="fcc-table">
                    <thead><tr>
                        <th>When</th><th>Operation</th><th>Error</th><th></th>
                    </tr></thead>
                    <tbody>
                    ${items
                        .map(
                            (f) => `<tr>
                        <td>${FO.fmtDateTime(f.created_at || f.occurred_at)}</td>
                        <td>${FO.escapeHtml(f.source_type || f.posting_kind || '—')}</td>
                        <td>${FO.escapeHtml((f.error_message || f.message || '').slice(0, 120))}</td>
                        <td><button type="button" class="btn btn-sm btn-secondary" data-resolve="${FO.escapeHtml(f.id)}">Resolve</button></td>
                    </tr>`
                        )
                        .join('')}
                    </tbody>
                </table>`;
            out.querySelectorAll('[data-resolve]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    try {
                        await API.accountingGl.resolvePostingFailure(btn.getAttribute('data-resolve'));
                        await load();
                    } catch (err) {
                        alert(err.message || String(err));
                    }
                });
            });
        } catch (err) {
            FO.showError(out, err);
        }
    }
}

window.renderFinancePostingFailures = renderFinancePostingFailures;
