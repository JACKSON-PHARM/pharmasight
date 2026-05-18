// Finance Operations Console — Stage 1 observability router

const FINANCE_OPS_SUBPAGES = {
    events: { title: 'Event Explorer', loader: 'renderFinanceEvents' },
    projections: { title: 'Projection Explorer', loader: 'renderFinanceProjections' },
    proposals: { title: 'Proposal Inbox', loader: 'renderFinanceProposals' },
    integrity: { title: 'Replay & Integrity', loader: 'renderFinanceIntegrity' },
    reconciliation: { title: 'Treasury Reconciliation', loader: 'renderFinanceReconciliation' },
};

async function loadFinance(subPage) {
    const page = document.getElementById('finance');
    if (!page) return;

    const key = subPage && FINANCE_OPS_SUBPAGES[subPage] ? subPage : 'events';
    const meta = FINANCE_OPS_SUBPAGES[key];

    page.innerHTML = `
        <div id="financeContent" style="max-width:1200px;">
            <p style="opacity:0.7;">Loading ${meta.title}…</p>
        </div>`;

    const loaderName = meta.loader;
    const loader = typeof window[loaderName] === 'function' ? window[loaderName] : null;
    if (!loader) {
        const root = document.getElementById('financeContent');
        if (root) {
            root.innerHTML =
                '<div class="card"><div class="card-body"><p>Finance Operations module failed to load. Refresh the page.</p></div></div>';
        }
        return;
    }
    await loader();
}

window.loadFinance = loadFinance;
